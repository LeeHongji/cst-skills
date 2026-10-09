"""Offline audit lifecycle and synthetic approval only in pytest workspaces."""
import asyncio
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/p) for p in ('MCP/CST','MCP/CST-CAD/src','MCP/CST-Lab/src')]
from cst_cad import ir
from cst_agent_api import FunctionService
from cst_review import approve_with_confirmation
from cst_lab.approval import ReviewAuthority, prepare_review, verify_approval
from cst_lab.contracts.attempt import write_attempt, ApprovalError
from cst_lab.contracts.design import write_design
from cst_lab.contracts.iterations import read_iterations
from cst_lab.function_audit import latest_review
from cst_lab.function_contract import RunRequest
from cst_lab.function_evidence import validate_revision
from cst_lab.function_model import load_model, prepare_simulation
from cst_lab.paths import LabPaths
from cst_lab.standing_authorization import enroll

@pytest.fixture
def context(tmp_path,monkeypatch):
    shutil.copytree(ROOT/'brain/schemas',tmp_path/'brain/schemas')
    paths=LabPaths.resolve(tmp_path)
    request=dict(topic='verification',design='lowpass',attempt='a',request_id='audit-one',
                 why='Synthetic offline CAD review verification',operation='audit',fidelity='offline')
    attempt=RunRequest.parse(request).attempt_path(tmp_path)
    design=attempt.parents[2];design.mkdir(parents=True)
    shutil.copy2(ROOT/'MCP/CST/tools/verification_lowpass.py',design/'model.py')
    write_design(design/'design.md',dict(schema_version=1,topic_id='verification',design_id='lowpass',title='Neutral audit',
        model='model.py',ports=2,acceptance=[dict(id='transmission',metric='s2_1_db',band_ghz=[.1,1.5],
        comparator='>=',threshold=-1,mode='pointwise')]),'Synthetic test, no CST.',paths)
    service=FunctionService(tmp_path)
    def forbidden(*args,**kwargs):raise AssertionError('offline audit tried to reach CST executor')
    monkeypatch.setattr('cst_function_executor.execute',forbidden)
    monkeypatch.setattr('cst_function_executor.cache_runtime_probe',forbidden)
    declare(attempt,paths)
    return service,request,attempt,paths

def declare(attempt,paths):
    document=load_model(attempt.parents[2]/'model.py',{})
    write_attempt(attempt,dict(schema_version=1,topic_id='verification',design_id='lowpass',attempt_id='a',
        topology_hash=ir.topology_hash(document),model_intent_id=document['model_intent_id'],
        baseline_parameters={p['name']:p['value'] for p in document['parameters']},approved_ranges={},max_iterations=20),paths)

def run(context,**changes):
    service,request,_,_=context
    ref=service.store.submit(RunRequest.parse(dict(request,**changes)))
    service.work(ref)
    return service.get(ref)

def approve(context):
    service,_,attempt,paths=context
    authority=ReviewAuthority(paths.registry_root/'approval')
    enroll(authority,workspace_root=service.root,topic_id='verification',approved_by='synthetic-user',
        statement='Synthetic test grant only',source='pytest')
    result=asyncio.run(approve_with_confirmation(attempt,{'l3':[13,15]},context=None,authority=authority,
        audit_html=latest_review(attempt,paths)))
    assert result['approved'] and result['human_reviewed'] is False
    return authority

def test_unapproved_audit_publishes_without_touching_attempt_or_cst(context):
    service,request,attempt,paths=context
    original=attempt.read_bytes()
    job=run(context)
    assert job['state']=='completed' and job['result']['acceptance']['status']=='not_evaluated'
    assert attempt.read_bytes()==original and not (attempt.parent/'audit.html').exists()
    row=read_iterations(attempt.parent/'iterations.jsonl',paths)[0]
    assert row['audited'] is False and row['evidence']['kind']=='model-audit' and row['drc']=='pass'
    assert all(name not in row for name in ('solver','metrics','execution'))
    summary=service.get(job['result']['artifacts']['audit.json'])['document']
    assert summary['readiness']=='ready_for_approval' and summary['approval_granted'] is False
    assert service.store.submit(RunRequest.parse(request))==job['ref']
    assert len(read_iterations(attempt.parent/'iterations.jsonl',paths))==1
    page=Path(service.get(job['result']['artifacts']['audit.html'])['path']).read_text(encoding='utf-8')
    assert 'WebGLRenderer' in page
    for ref in job['result']['artifacts'].values():service.get(ref)

def test_published_approval_uses_own_ir_and_allows_simulation_preflight(context):
    service,request,attempt,paths=context
    run(context);authority=approve(context)
    # There is no root geometry-ir.json. The approval is bound to its revision.
    approved=verify_approval(attempt,authority=authority)
    assert approved['approval']['audit_html'].startswith('evidence-revisions/')
    assert approved['approval']['audit_manifest_sha256']
    prepared=prepare_simulation(dict(request,request_id='preflight',operation='simulate',fidelity='screen'),paths,authority)
    assert prepared.execution['parameters']['l3']==13.9312
    original=attempt.read_bytes()
    run(context,request_id='audit-again')
    assert attempt.read_bytes()==original
    assert verify_approval(attempt,authority=authority)==approved
    assert latest_review(attempt,paths)!=approved['approval']['audit_html']

def test_drc_failure_is_reviewable_but_never_approvable(context):
    service,_,attempt,paths=context
    script=attempt.parents[2]/'model.py'
    script.write_text(script.read_text(encoding='utf-8').replace('min_width=.28','min_width=100'),encoding='utf-8')
    declare(attempt,paths)
    job=run(context)
    assert job['state']=='completed'
    summary=service.get(job['result']['artifacts']['audit.json'])['document']
    assert summary['drc_status']=='fail' and summary['readiness']=='needs_correction'
    with pytest.raises(ApprovalError,match='DRC must pass'):
        prepare_review(attempt,latest_review(attempt,paths),{})

@pytest.mark.parametrize('field,value',[('inputs',['cst_runs/x.s2p']),('param_delta',{'l3':14}),('setup_delta',{'mesh':{'kind':'tetrahedral'}})])
def test_audit_rejects_ignored_request_fields(context,field,value):
    job=run(context,**{field:value})
    assert job['state']=='failed' and 'declared attempt baseline' in job['result']['error']
    service,_,attempt,paths=context
    assert read_iterations(attempt.parent/'iterations.jsonl',paths)[0]['status']=='failed'

def test_changed_source_baseline_refused_before_publish(context):
    _,_,attempt,_=context
    script=attempt.parents[2]/'model.py'
    script.write_text(script.read_text(encoding='utf-8').replace('epsilon=3.55','epsilon=3.66'),encoding='utf-8')
    job=run(context)
    assert job['state']=='failed' and 'declared attempt baseline' in job['result']['error']
    assert not (attempt.parent/'evidence-revisions').exists()

@pytest.mark.parametrize('filename',['audit.html','geometry-ir.json','model-source/model.py','manifest.json'])
def test_tampered_review_revision_invalidates_get_and_approval(context,filename):
    service,_,attempt,paths=context
    job=run(context);authority=approve(context)
    directory=(attempt.parent/latest_review(attempt,paths)).parent
    with (directory/filename).open('ab') as stream:stream.write(b'\nchanged')
    with pytest.raises((ValueError,ApprovalError)):verify_approval(attempt,authority=authority)
    with pytest.raises(ValueError):service.get(job['result']['artifacts']['audit.json'])

def test_crash_after_audit_rename_recovers_without_overwriting_prior_review(context,monkeypatch):
    import cst_lab.function_evidence as evidence
    service,request,attempt,paths=context
    first=run(context);prior=latest_review(attempt,paths)
    original=(attempt.parent/prior).read_bytes()
    real=evidence.complete_publication
    def crash(*args,**kwargs):
        real(*args,**kwargs)
        raise SystemExit(74)
    monkeypatch.setattr(evidence,'complete_publication',crash)
    ref=service.store.submit(RunRequest.parse(dict(request,request_id='crash')))
    with pytest.raises(SystemExit):service.work(ref)
    assert service.get(ref)['state']=='finalizing'
    assert latest_review(attempt,paths)==prior  # A moved folder alone is not approval-ready.
    monkeypatch.setattr(evidence,'complete_publication',real)
    assert service.store.recover(ref)=='completed'
    assert service.store.recover(ref)=='completed'
    assert len(read_iterations(attempt.parent/'iterations.jsonl',paths))==2
    assert (attempt.parent/prior).read_bytes()==original
    assert latest_review(attempt,paths)!=prior
