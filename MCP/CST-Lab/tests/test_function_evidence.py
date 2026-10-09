import json
import shutil
from pathlib import Path

import pytest

from cst_lab.contracts.attempt import write_attempt
from cst_lab.contracts.iterations import iteration_line
from cst_lab.function_contract import RunRequest
from cst_lab.function_evidence import publish_analysis,sha256,validate_revision
from cst_lab.jobs import JobStore
from cst_lab.paths import LabPaths
from cst_lab.topic_workspace import init_topic,init_design,validate_topic_workspace


@pytest.fixture
def published(tmp_path):
    shutil.copytree(Path(__file__).resolve().parents[3]/'brain/schemas',tmp_path/'brain/schemas')
    topic=init_topic(tmp_path,topic_id='evidence-test',title='Evidence test',
        shared_physics=['test only'],sources=[{'kind':'internal','citation':'synthetic test'}])
    design=init_design(topic,design_id='device',title='Device',ports=2,acceptance=[dict(
        id='rl',metric='s1_1_db',band_ghz=[1,2],comparator='<',threshold=-10,mode='pointwise')])
    paths=LabPaths.resolve(tmp_path)
    request=RunRequest.parse(dict(topic='evidence-test',design='device',attempt='a',
        request_id='one',why='Test immutable publication',inputs=['cst_runs/a.s2p']))
    attempt=request.attempt_path(tmp_path)
    write_attempt(attempt,dict(schema_version=1,topic_id='evidence-test',design_id='device',
        attempt_id='a',topology_hash='a'*64,baseline_parameters={},approved_ranges={},max_iterations=3),paths)
    store=JobStore(tmp_path,paths=paths);ref=store.submit(request)
    stage=tmp_path/'cst_runs/stage';stage.mkdir(parents=True)
    (stage/'analysis.json').write_text('{"test":true}')
    with store.claim(ref) as session:
        folder,hash_value=publish_analysis(stage,attempt,ref,paths)
        session.finish(iteration_line(iter_number=0,parent=None,status='completed',audited=False,
            provenance='native',duration_s=.1,execution_kind='offline',cache_hit=False,
            evidence=dict(kind='offline-analysis',revision=folder.name,manifest_sha256=hash_value)))
    return topic,folder,hash_value


def test_topic_links_revision_to_final_fact(published):
    topic,folder,hash_value=published
    assert validate_revision(folder,hash_value)['kind']=='offline-analysis'
    report=validate_topic_workspace(topic)
    assert report['status']=='valid',report
    assert report['evidence_packages']==1


@pytest.mark.parametrize('damage',['bytes','manifest','missing','orphan','empty-cache'])
def test_topic_rejects_damaged_or_unbound_revisions(published,damage):
    topic,folder,hash_value=published
    if damage=='bytes': (folder/'analysis.json').write_text('{"test":false}')
    elif damage=='manifest': (folder/'manifest.json').write_text('{}')
    elif damage=='missing': folder.rename(folder.with_name('unbound-revision'))
    elif damage=='orphan': shutil.copytree(folder,folder.with_name('orphan'))
    else: (folder/'Result').mkdir()
    report=validate_topic_workspace(topic)
    assert report['status']=='invalid',report


def test_manifest_structure_is_strict_even_without_external_hash(published):
    _,folder,_=published
    manifest=folder/'manifest.json';doc=json.loads(manifest.read_text())
    doc['files'][0]['bytes']=True
    manifest.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='invalid evidence file record'): validate_revision(folder)
