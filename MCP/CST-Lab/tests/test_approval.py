import copy
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'MCP/CST-CAD/src'))
from cst_cad import audit, ir
from cst_cad.dsl import ModelBuilder
from cst_lab.approval import (ReviewAuthority, prepare_review, complete_review, verify_approval,
                              check_effective_parameters, digest)
from cst_lab.contracts.attempt import ApprovalError, write_attempt


def model(overrides=None):
    m=ModelBuilder(model_id='approval-coupon',overrides=overrides)
    w=m.param('w',2.,tunable=True,minimum=1.,maximum=3.)
    h=m.param('h',1.)
    m.derived_param('twice_w',2*w)
    m.material('PEC',kind='pec');m.layer('metal',0,h,'PEC')
    m.net('SIGNAL','metal').rect(0,0,w,10)
    m.rule('width','min_width','net:SIGNAL',severity='error',min_width=.5)
    return m.build()


@pytest.fixture
def review(tmp_path):
    doc=model();path=tmp_path/'attempt/attempt.json';path.parent.mkdir()
    ir.write(doc,path.parent/'geometry-ir.json');audit.write(doc,path.parent/'audit.html')
    write_attempt(path,dict(schema_version=1,attempt_id='a01',design_id='coupon',topic_id='validation',
        topology_hash=ir.topology_hash(doc),model_intent_id=doc['model_intent_id'],
        baseline_parameters={p['name']:p['value'] for p in doc['parameters']},approved_ranges={},max_iterations=5))
    authority=ReviewAuthority(tmp_path/'authority')
    binding=prepare_review(path,'audit.html',{'w':[1.6,2.4]})
    return path,authority,binding


def confirm(review):
    path,authority,binding=review
    # Synthetic confirmation used only in this unit test; no live review claim.
    return complete_review(binding,authority=authority,reviewer='unit-test-operator',
                           channel='local-operator-console',confirmation=digest(binding))


def test_confirmed_artifact_survives_authority_restart_and_in_range_parameters(review):
    path,authority,_=review;confirm(review)
    actual=verify_approval(path,authority=ReviewAuthority(authority.directory))
    check_effective_parameters(actual,model({'w':2.3}))
    assert not (path.parent/'.approval.lock').exists()


@pytest.mark.parametrize('kind',['html','range','baseline','signature','ir','metadata'])
def test_any_approved_binding_tampering_is_rejected(review,kind):
    path,authority,_=review;confirm(review)
    a=json.loads(path.read_text())
    if kind=='html':
        p=path.parent/'audit.html';p.write_text(p.read_text(encoding='utf-8')+'<!-- changed -->',encoding='utf-8')
    elif kind=='range':a['approved_ranges']['w']=[1.,3.]
    elif kind=='baseline':a['baseline_parameters']['h']=2.
    elif kind=='signature':a['approval']['signature']='0'*64
    elif kind=='ir':ir.write(model({'w':2.1}),path.parent/'geometry-ir.json')
    else:
        p=path.parent/'audit.html';p.write_text(p.read_text(encoding='utf-8').replace('"drc_status": "pass"','"drc_status": "fail"'),encoding='utf-8')
    write_attempt(path,a)
    with pytest.raises(ApprovalError):verify_approval(path,authority=authority)


def test_reviewer_text_or_wrong_confirmation_cannot_grant_approval(review):
    _,authority,binding=review
    for channel,confirmation in [('agent-request',digest(binding)),('mcp-elicitation','yes')]:
        with pytest.raises(ApprovalError):
            complete_review(binding,authority=authority,reviewer='human',channel=channel,confirmation=confirmation)


def test_pending_review_rejects_changed_inputs(review):
    path,_,_=review
    a=json.loads(path.read_text());a['max_iterations']=8;write_attempt(path,a)
    with pytest.raises(ApprovalError,match='changed while'):confirm(review)


@pytest.mark.parametrize('ranges',[{'h':[.8,1.2]},{'w':[2.1,2.4]},{'w':[1.,float('nan')]},{'w':[0.,3.]},{'w':[True,3.]},{'twice_w':[3.,5.]}])
def test_unreviewable_ranges_fail_closed(review,ranges):
    path,_,_=review
    with pytest.raises(ApprovalError):prepare_review(path,'audit.html',ranges)


def test_fixed_derived_and_missing_parameters_checked_on_effective_ir(review):
    a=confirm(review)
    for name,value in [('h',1.1),('twice_w',5.),('w',2.6)]:
        doc=model()
        next(p for p in doc['parameters'] if p['name']==name)['value']=value
        with pytest.raises(ApprovalError):check_effective_parameters(a,ir.stamp(doc))


def test_unsigned_legacy_record_never_grants_production_execution(review):
    path,authority,_=review;a=json.loads(path.read_text())
    a['approval']=dict(approved_by='someone',approved_at='2026-09-14T00:00:00Z',topology_hash=a['topology_hash'],audit_html='audit.html')
    write_attempt(path,a)
    with pytest.raises(ApprovalError,match='authenticated'):verify_approval(path,authority=authority)


def test_exported_request_is_bound_to_exact_file_and_ranges(review):
    path,_,b=review
    request={k:b[k] for k in ['artifact_id','audit_sha256','topology_hash','model_intent_id','ranges']}
    request.update(schema_version=1,kind='cst-approval-request')
    assert prepare_review(path,'audit.html',b['ranges'],request=request)==b
    request['audit_sha256']='0'*64
    with pytest.raises(ApprovalError,match='exported request'):prepare_review(path,'audit.html',b['ranges'],request=request)
