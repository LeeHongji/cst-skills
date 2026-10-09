from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import time

import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'MCP/CST-CAD/src'))
from cst_cad import audit,ir,drc
from cst_lab.approval import ReviewAuthority,prepare_review,complete_review,digest
from cst_lab.contracts.attempt import write_attempt,ApprovalError
from cst_lab.contracts.design import write_design
from cst_lab.contracts.iterations import append_iteration,iteration_line
from cst_lab.function_contract import RunRequest
from cst_lab.function_model import load_model,prepare_simulation,verify_geometry_expressions
from cst_lab.function_setup import resolve_setup,apply_to_ir,cache_identity
from cst_lab.paths import LabPaths


@pytest.fixture
def model_context(tmp_path):
    shutil.copytree(ROOT/'brain/schemas',tmp_path/'brain/schemas')
    paths=LabPaths.resolve(tmp_path)
    request=dict(topic='verification',design='lowpass',attempt='a',request_id='one',why='Synthetic preflight test',
                 operation='simulate',fidelity='screen')
    attempt=RunRequest.parse(request).attempt_path(tmp_path)
    design=attempt.parents[2];design.mkdir(parents=True)
    source=(ROOT/'MCP/CST/tools/verification_lowpass.py').read_text(encoding='utf-8')
    source=source.replace('tunable=(k == "l3")','tunable=(k in ("l3", "l2", "wh"))')
    source=source.replace('    m.material("RO4003C"','    m.derived_param("total_length", length)\n    m.material("RO4003C"')
    script=design/'model.py';script.write_text(source,encoding='utf-8')
    doc=load_model(script,{})
    write_design(design/'design.md',dict(schema_version=1,topic_id='verification',design_id='lowpass',title='Lowpass test',
        model='model.py',ports=2,acceptance=[dict(id='transmission',metric='s2_1_db',band_ghz=[.1,1.5],comparator='>=',threshold=-1,mode='pointwise')]),'Isolated test; no real simulation.',paths)
    write_attempt(attempt,dict(schema_version=1,topic_id='verification',design_id='lowpass',attempt_id='a',
        topology_hash=ir.topology_hash(doc),model_intent_id=doc['model_intent_id'],
        baseline_parameters={p['name']:p['value'] for p in doc['parameters']},approved_ranges={},max_iterations=10),paths)
    ir.write(doc,attempt.parent/'geometry-ir.json');audit.write(doc,attempt.parent/'audit.html')
    authority=ReviewAuthority(paths.registry_root/'approval')
    binding=prepare_review(attempt,'audit.html',{'l3':[12,16],'l2':[7,9],'wh':[.1,.6]})
    # Synthetic approval ONLY in this pytest-owned directory; never live approval.
    complete_review(binding,authority=authority,reviewer='unit-test-only',channel='local-operator-console',confirmation=digest(binding))
    return paths,request,authority,script,attempt


def prepare(context,**changes):
    paths,request,authority,_,_=context
    return prepare_simulation(dict(request,**changes),paths,authority)


def parent(context,prepared):
    paths,_,_,_,attempt=context
    append_iteration(attempt.parent/'iterations.jsonl',iteration_line(iter_number=0,parent=None,status='completed',
        fidelity='screen',provenance='native',audited=True,execution_kind='solver',execution=prepared.execution,
        observation='Synthetic fixture fact; not a physical solve'),paths)


def test_full_parameters_and_setup_inherit_parent(model_context):
    first=prepare(model_context,param_delta={'l3':15.},setup_delta={'settings':{'accuracy_db':-42}})
    parent(model_context,first)
    second=prepare(model_context,parent=0,param_delta={'l2':[8.2153,8.7]},setup_delta={'settings':{'accuracy_db':[-42,-44]}})
    assert second.execution['parameters']['l3']==15
    assert second.execution['parameters']['l2']==8.7
    assert second.execution['parameters']['total_length']-first.execution['parameters']['total_length']==pytest.approx(8.7-8.2153)
    assert second.execution['setup']['settings']['accuracy_db']==-44
    assert set(second.param_delta)=={'l2','total_length'}
    assert second.param_delta['l2']==[8.2153,8.7]
    assert second.document['simulation']['settings']['accuracy_db']==-44
    assert second.drc_report['status']=='pass'


@pytest.mark.parametrize('changes,match',[
    ({'param_delta':{'l3':17}},'outside approved range'),
    ({'param_delta':{'sub_h':1}},'independent tunable'),
    ({'param_delta':{'total_length':60}},'independent tunable'),
    ({'param_delta':{'typo':2}},'independent tunable'),
    ({'param_delta':{'l3':[14,15]}},'old-value'),
    ({'setup_delta':{'mesh':{'min_cell_fraction':.01}}},'unsupported mesh'),
    ({'setup_delta':{'settings':{'pretend_applied':2}}},'unsupported settings'),
    ({'setup_delta':{'boundaries':{'zmax':'electric'}}},'unsupported setup'),
    ({'setup_delta':{'frequency':{'min':8}}},'inconsistent'),
    ({'setup_delta':{'settings':{'accuracy_db':[-50,-45]}}},'old-value'),
])
def test_refusals_before_any_cst_call(model_context,changes,match):
    with pytest.raises((ValueError,ApprovalError),match=match): prepare(model_context,**changes)


def test_numeric_old_value_accepts_integer_for_float(model_context):
    result=prepare(model_context,setup_delta={'mesh':{'steps_per_wavelength_near':[20,22]}})
    assert result.execution['setup']['mesh']['steps_per_wavelength_near']==22


def test_changed_fixed_physics_cannot_hide_behind_same_topology(model_context):
    _,_,_,script,_=model_context
    before=load_model(script,{})
    script.write_text(script.read_text().replace('epsilon=3.55','epsilon=3.66'))
    after=load_model(script,{})
    assert ir.topology_hash(before)==ir.topology_hash(after)
    with pytest.raises(ApprovalError,match='exact audited baseline'): prepare(model_context)


def test_ignored_overrides_and_geometry_expressions_are_detected(model_context):
    _,_,_,script,_=model_context
    original=script.read_text()
    script.write_text(original.replace('overrides=overrides)','overrides=None)'))
    with pytest.raises(ValueError,match='ignored requested'): prepare(model_context,param_delta={'l3':15})
    script.write_text(original.replace('return m.build()',
        "doc=m.build()\n    doc['nets'][0]['solids'][0]['box']['x1']+=1\n    from cst_cad import ir\n    return ir.stamp(doc)"))
    with pytest.raises(ValueError,match='geometry/expression mismatch'): prepare(model_context)


def test_approval_rechecked_and_drc_must_be_pass(model_context,monkeypatch):
    original=drc.run;calls=0
    def failed_candidate(doc,*args,**kwargs):
        nonlocal calls
        calls+=1
        report=original(doc,*args,**kwargs)
        if calls==2: report['status']='error'
        return report
    monkeypatch.setattr(drc,'run',failed_candidate)
    with pytest.raises(ApprovalError,match='DRC must pass'): prepare(model_context)


def test_actual_narrow_trace_geometry_fails_drc_even_inside_approved_ranges(model_context):
    with pytest.raises(ApprovalError,match='candidate DRC must pass, got fail'):
        prepare(model_context,param_delta={'wh':.2})


def test_cyclic_parameters_are_refused_offline(model_context):
    doc=load_model(model_context[3],{})
    next(p for p in doc['parameters'] if p['name']=='l2')['expression']='l3'
    next(p for p in doc['parameters'] if p['name']=='l3')['expression']='l2'
    with pytest.raises(ValueError,match='cyclic parameter'): verify_geometry_expressions(doc)


def test_unsigned_approval_is_blocked_before_model_import(model_context):
    _,_,_,script,attempt=model_context
    doc=json.loads(attempt.read_text());doc.pop('approval');attempt.write_text(json.dumps(doc))
    script.write_text('raise AssertionError("must not import without approval")')
    with pytest.raises(ApprovalError,match='authenticated approval'): prepare(model_context)


def test_parent_missing_or_corrupt_effective_context_is_refused(model_context):
    first=prepare(model_context);parent(model_context,first)
    _,_,_,_,attempt=model_context
    history=attempt.parent/'iterations.jsonl';row=json.loads(history.read_text())
    row['execution']['setup']['mesh']['steps_per_wavelength_near']=999
    history.write_text(json.dumps(row)+'\n')
    with pytest.raises(ValueError,match='parent effective setup hash changed'): prepare(model_context,parent=0)


def test_source_helpers_reload_actual_bytes_without_stale_pyc(model_context):
    _,_,_,script,_=model_context
    helper=script.with_name('dimensions.py');helper.write_text('VALUE=3.55\n')
    script.write_text('from dimensions import VALUE\n'+script.read_text().replace('epsilon=3.55','epsilon=VALUE'))
    first=load_model(script,{})
    helper.write_text('VALUE=3.66\n')
    second=load_model(script,{})
    assert first['model_intent_id']!=second['model_intent_id']


def test_cache_identity_covers_setup_fidelity_runtime_and_parameters(model_context):
    base=prepare(model_context)
    runtime=dict(cst_version='2026.2',executor_sha256='a'*64)
    key=lambda item,version=runtime:cache_identity(item.document,item.execution['setup'],version)[1]
    original=key(base)
    assert original!=key(prepare(model_context,param_delta={'l3':15}))
    assert original!=key(prepare(model_context,setup_delta={'mesh':{'steps_per_wavelength_near':22}}))
    assert original!=key(prepare(model_context,fidelity='confirm'))
    assert original!=key(base,dict(runtime,cst_version='2026.3'))
    assert original!=key(base,dict(runtime,executor_sha256='b'*64))
    assert original==key(prepare(model_context,setup_delta={'settings':{'accuracy_db':-40}}))
    with pytest.raises(ValueError,match='version is missing'): key(base,dict(runtime,cst_version='unknown'))
    inconsistent=deepcopy(base.execution['setup']);inconsistent['settings']['accuracy_db']=-99
    with pytest.raises(ValueError,match='cache setup differs'): cache_identity(base.document,inconsistent,runtime)


@pytest.mark.parametrize('delta,drc_status,phase',[({'l3':15},'pass','ready-for-executor'),({'wh':.2},'fail','preflight-refused')])
def test_facade_preflight_dispatches_only_passing_models(model_context,delta,drc_status,phase,monkeypatch):
    sys.path.insert(0,str(ROOT/'MCP/CST'))
    from cst_agent_api import FunctionService
    from cst_lab.function_evidence import prepare_diagnostic
    from cst_lab.atomic import atomic_json
    import cst_function_executor
    paths,request,_,_,attempt=model_context
    service=FunctionService(paths.workspace_root)
    calls=[]
    def isolated_executor(session,prepared):
        calls.append(prepared)
        stage=paths.workspace_root/'cst_runs/test-diagnostic';stage.mkdir(parents=True)
        atomic_json(stage/'diagnostic.json',dict(job=session.ref,status='blocked'))
        return dict(status='blocked',error='isolated test backend; no CST',receipt={},stage=stage,
                    manifest_sha256=prepare_diagnostic(stage,session.ref))
    # Synthetic approval must NEVER flow into the native subprocess dispatcher.
    monkeypatch.setattr(cst_function_executor,'execute',isolated_executor)
    ref=service.store.submit(RunRequest.parse(dict(request,param_delta=delta)))
    with service.store.claim(ref) as session:
        service._execute(session)
    job=service.get(ref)
    assert job['state']=='blocked',job
    assert job['progress']['phase']==phase
    fact=json.loads((attempt.parent/'iterations.jsonl').read_text())
    assert fact['drc']==drc_status
    if drc_status=='pass':
        assert fact['execution']['parameters']['l3']==15 and len(calls)==1
        assert fact['evidence']['kind']=='execution-diagnostic'
    else:
        assert job['progress']['details']['drc_report']['status']=='fail' and not calls
    assert fact['audited'] is False and fact['execution_kind']==('interrupted' if calls else 'offline')
    assert 'solver' not in fact
    if output:=os.environ.get('CST_TEST_EVIDENCE_ROOT'):
        from cst_lab.atomic import atomic_json
        atomic_json(Path(output)/f'background-preflight-{drc_status}.json',dict(
            scope='Synthetic approval in pytest-owned workspace; no human approval or CST solve',
            job=job,final_iteration=fact))
