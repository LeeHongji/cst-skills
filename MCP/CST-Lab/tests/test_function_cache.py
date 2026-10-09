"""Cache reuse with isolated synthetic native evidence; no CST launch allowed."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

import pytest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'MCP/CST'),str(ROOT/'MCP/CST/tests')]
from test_function_simulation import solved,incremental_case
from test_function_model import model_context
from cst_lab.function_cache import find,prepare
from cst_lab.function_model import prepare_simulation
from cst_lab.function_contract import RunRequest
from cst_lab.function_evidence import validate_revision
from cst_lab.contracts.iterations import read_iterations
from cst_lab.contracts.design import load_design,write_design
from cst_agent_api import FunctionService

PROBE=dict(executor_sha256='b'*64,cst_binary_sha256='c'*64)


@pytest.fixture
def cache_case(incremental_case,model_context,monkeypatch):
    solved,_,_,folder=incremental_case
    paths,original,prepared,_,_=solved
    request=dict(original,request_id='cache-request')
    import cst_function_executor as executor
    def forbidden(*a,**k):raise AssertionError('cache verification must not invoke CST executor')
    monkeypatch.setattr(executor,'execute',forbidden)
    monkeypatch.setattr(executor,'cache_runtime_probe',lambda:dict(PROBE))
    return paths,request,prepared,folder,model_context[2]


def run(case,request=None):
    paths,default,_,_,_=case;request=request or default
    service=FunctionService(paths.workspace_root)
    ref=service.store.submit(RunRequest.parse(request))
    with service.store.claim(ref) as session:service._execute(session)
    return service,service.get(ref)


def test_exact_cache_reevaluates_gates_and_survives_source_removal(cache_case):
    paths,request,prepared,folder,_=cache_case
    design=RunRequest.parse(request).attempt_path(paths.workspace_root).parents[2]/'design.md'
    header,_,body=load_design(design,paths)
    header['acceptance'][0]['threshold']=-.5
    write_design(design,header,body,paths)
    service,job=run(cache_case)
    assert job['state']=='completed' and job['result']['cache_hit'] is True,job
    assert job['result']['acceptance']['status']=='fail'
    artifact=service.get(job['result']['artifacts']['cache.json'])
    assert artifact['document']['cst_launches']==0 and artifact['document']['solver_started'] is False
    assert artifact['document']['source']['job'].endswith('/'+'b'*32)
    assert service.run(request)==job['result']
    attempt=RunRequest.parse(request).attempt_path(paths.workspace_root)
    rows=read_iterations(attempt.parent/'iterations.jsonl',paths)
    assert len(rows)==2 and rows[1]['execution_kind']=='cache' and 'solver' not in rows[1]
    assert rows[0]['acceptance']['status']=='pass' and rows[1]['acceptance']['status']=='fail'
    # Temporary test fixture only: the durable cache must retain full evidence.
    shutil.rmtree(folder)
    assert service.get(job['result']['artifacts']['cache.json'])['document']==artifact['document']


@pytest.mark.parametrize('damage',['curve','model','manifest','runtime','executor','setup','source','confirm','legacy-runtime'])
def test_cache_refuses_corruption_and_misses_changed_identity(cache_case,damage):
    paths,request,prepared,folder,_=cache_case
    attempt=RunRequest.parse(request).attempt_path(paths.workspace_root)
    probe=dict(PROBE);candidate=deepcopy(prepared)
    if damage=='curve':(folder/'analysis/source-00.s2p').write_text('corrupt')
    elif damage=='model':(folder/'selected.cst').write_bytes(b'corrupt')
    elif damage=='manifest':(folder/'manifest.json').write_text('{}')
    elif damage=='runtime':probe['cst_binary_sha256']='d'*64
    elif damage=='executor':probe['executor_sha256']='d'*64
    elif damage=='setup':candidate.execution['setup_sha256']='d'*64
    elif damage=='source':candidate.execution['model_source_sha256']='d'*64
    elif damage=='confirm':candidate.execution['setup']['fidelity']='confirm'
    elif damage=='legacy-runtime':probe=None
    if damage in ('curve','model','manifest'):
        with pytest.raises(ValueError):find(attempt,candidate,paths,probe)
        _,job=run(cache_case)
        assert job['state']=='blocked' and job['result']['cache_hit'] is False
    else:assert find(attempt,candidate,paths,probe) is None


def test_current_approval_is_required_even_for_cache(cache_case):
    paths,request,_,_,_=cache_case
    attempt=RunRequest.parse(request).attempt_path(paths.workspace_root)
    a=json.loads(attempt.read_text());a.pop('approval');attempt.write_text(json.dumps(a))
    _,job=run(cache_case)
    assert job['state']=='blocked' and job['result']['cache_hit'] is False


def test_cache_finalization_recovers_once_without_reexecution(cache_case,monkeypatch):
    paths,request,_,_,_=cache_case;service=FunctionService(paths.workspace_root)
    ref=service.store.submit(RunRequest.parse(request))
    import cst_lab.function_evidence as evidence
    original=evidence.complete_publication
    def interrupt(*args,**kwargs):
        original(*args,**kwargs);raise RuntimeError('injected cache publication interrupt')
    with monkeypatch.context() as patch:
        patch.setattr(evidence,'complete_publication',interrupt)
        with pytest.raises(RuntimeError,match='injected cache'):
            with service.store.claim(ref) as session:service._execute(session)
    assert service.store.get(ref)['state']=='finalizing'
    assert service.store.recover(ref)=='completed'
    job=service.get(ref)
    assert job['result']['cache_hit'] is True
    rows=read_iterations(RunRequest.parse(request).attempt_path(paths.workspace_root).parent/'iterations.jsonl',paths)
    assert len(rows)==2
