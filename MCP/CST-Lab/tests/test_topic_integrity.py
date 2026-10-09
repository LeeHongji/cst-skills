"""Read-side integrity: edited contracts/manifests must fail independently of writers."""
import hashlib
import json
from pathlib import Path
import pytest
from cst_lab.topic_workspace import init_topic, init_design, validate_topic_workspace
from cst_lab.contracts import iteration_line


def workspace(root):
    topic = init_topic(root, topic_id="integrity-case", title="Integrity fixture",
                       shared_physics=["microstrip"], sources=[{"kind":"internal","citation":"test fixture"}])
    design = init_design(topic, design_id="lowpass", title="Lowpass", ports=2, acceptance=[
        dict(id="passband", metric="s2_1_db",band_ghz=[1.,2.],comparator=">",threshold=-1.,mode="pointwise")])
    attempt = design/'attempts/a01-baseline';attempt.mkdir()
    (attempt/'attempt.json').write_text(json.dumps(dict(schema_version=1,attempt_id="a01-baseline",
        design_id="lowpass",topic_id="integrity-case",topology_hash="a"*64,
        baseline_parameters={},approved_ranges={},max_iterations=3)),encoding="utf-8")
    (attempt/'iterations.jsonl').write_text(json.dumps(iteration_line(iter_number=0,provenance="legacy",audited=False))+"\n",encoding="utf-8")
    return topic,attempt


@pytest.mark.parametrize("row", [{"not_an_iteration":True},iteration_line(iter_number=0),iteration_line(iter_number=1,parent=99)])
def test_topic_rejects_manual_history_corruption(tmp_path,row):
    topic,attempt=workspace(tmp_path)
    assert validate_topic_workspace(topic)['status']=='valid'
    with (attempt/'iterations.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps(row)+'\n')
    assert validate_topic_workspace(topic)['status']=='invalid'


@pytest.mark.parametrize("damage", ['uncovered','duplicate','traversal','hash','pending','no-model','not-object'])
def test_topic_rejects_incomplete_or_tampered_manifest(tmp_path,damage):
    topic,attempt=workspace(tmp_path);e=attempt/'evidence';(e/'selected/Model').mkdir(parents=True)
    (e/'selected.cst').write_bytes(b'test project')
    (e/'response.s2p').write_text('# GHz S RI R 50\n1 0 0 1 0 1 0 0 0\n',encoding='utf-8')
    m=dict(topic_id='integrity-case',design_id='lowpass',attempt_id='a01-baseline',
           verification=dict(static_package='pass',cst_reopen='pass',ir_comparison='pass'),
           files=[dict(path=p.name,bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in e.iterdir() if p.is_file()])
    def save(): (e/'manifest.json').write_text(json.dumps(m),encoding='utf-8')
    save();assert validate_topic_workspace(topic)['status']=='valid'
    if damage=='uncovered': (e/'untracked.csv').write_text('x',encoding='utf-8')
    elif damage=='duplicate': m['files'].append(m['files'][0])
    elif damage=='traversal': m['files'][0]['path']='../attempt.json'
    elif damage=='hash': m['files'][0]['sha256']='0'*64
    elif damage=='pending': m['verification']['cst_reopen']='pending'
    elif damage=='no-model': (e/'selected/Model').rmdir()
    elif damage=='not-object': m=[]
    save();assert validate_topic_workspace(topic)['status']=='invalid'
