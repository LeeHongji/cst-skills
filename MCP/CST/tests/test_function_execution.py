"""Isolated orchestration tests. No test approval or backend can launch CST."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[3]
for source in ('MCP/CST', 'MCP/CST-Lab/src', 'MCP/CST-CAD/src'):
    sys.path.insert(0,str(ROOT/source))
from cst_cad import emit_vba, drc
from cst_lab.function_model import load_model
from cst_lab.function_setup import resolve_setup, apply_to_ir
from cst_lab.function_contract import digest
from cst_guardian.function_execution import execute_prepared, verify_readback, leaves, NativeBackend
from cst_lab.function_readback import port_requirements


@pytest.fixture
def prepared():
    document=load_model(ROOT/'MCP/CST/tools/verification_lowpass.py',{})
    setup=resolve_setup(document,{},'screen')
    document=apply_to_ir(document,setup)
    blocks=emit_vba.build_blocks(document)
    return SimpleNamespace(document=document,execution=dict(setup=setup,
        emitted_sha256=digest([dict(title=b.title,code=b.code) for b in blocks])),
        approval_sha256='a'*64,drc_report=drc.run(document))


class FakeBackend:
    def __init__(self,prepared):
        self.prepared=prepared;self.events=[];self.incomplete=False;self.error=None
        self.log='';self.logs={};self.wrong_ports=False
        self.actual={k:dict(value=v,method='isolated test double') for k,v in leaves(prepared.execution['setup'])}
        self.actual.update({k:dict(value=v,method='isolated test double')
                            for k,v in port_requirements(prepared.execution['setup']['ports'])})
        self.observation=dict(entities=[dict(component=e['full_name'].split(':')[0],
            name=e['full_name'].split(':')[1],bounding_box=e['bounding_box'])
            for e in emit_vba.expected_entities(prepared.document)],
            parameters={p['name']:p['value'] for p in prepared.document['parameters']})

    def new_project(self,path):
        self.events.append('new');self.path=path;path.parent.mkdir(parents=True);return object()
    def runtime(self,p): return dict(cst_version='2026.2',executor_sha256='b'*64,cst_binary_sha256='c'*64)
    def history(self,p,b):
        self.events.append('history:'+b.title)
        return [dict(type='error',text='synthetic geometry failure')] if self.error=='history' else []
    def save(self,p):
        self.events.append('save');self.path.write_bytes(b'Synthetic CST stand-in, not native evidence')
    def observe(self,p,d): self.events.append('observe');return self.observation
    def read_setup(self,p,s,d):
        self.events.append('read_setup');return {} if self.incomplete else self.actual
    def log_paths(self,p):
        self.logs=dict(model=p.parent/'Model.log',output=p.parent/'output.txt')
        if self.error=='stale': self.logs['model'].write_text(self.log)
        return self.logs
    def messages(self,p): return []
    def solve(self,p):
        self.events.append('solve')
        if self.error=='solve': raise RuntimeError('synthetic solver failure')
        if self.error!='stale': self.logs['model'].write_text(self.log)
    def export(self,p,stem,setup):
        self.events.append('export');stem.parent.mkdir()
        target=stem.with_suffix('.s4p' if self.wrong_ports else '.s2p')
        frequency=setup['frequency']
        target.write_text('# GHz S RI R 50\n'+''.join(
            f'{f} .1 0 .9 0 .9 0 .1 0\n' for f in (frequency['min'],frequency['max'])))
        return target
    def close(self,p): self.events.append('close')


def execute(tmp_path,prepared,backend,authorize=lambda:None):
    return execute_prepared(prepared,tmp_path/'execution',backend,authorize,lambda *args:None)


def test_block_incomplete_readback_before_solver_and_retain_evidence(tmp_path,prepared):
    backend=FakeBackend(prepared);backend.incomplete=True
    result=execute(tmp_path,prepared,backend)
    assert result['status']=='blocked' and result['solver_started'] is False
    assert 'solve' not in backend.events and backend.events[-1]=='close'
    assert (tmp_path/'execution/readback-verification.json').is_file()
    assert 'solver' in result['error'] and 'ports.count' in result['error']


@pytest.mark.parametrize('mutation',['extra_parameter','nan','missing_box','duplicate','shift','wrong_setting','missing_core_setting'])
def test_readback_rejects_invalid_identity_and_settings(tmp_path,prepared,mutation):
    backend=FakeBackend(prepared)
    if mutation=='extra_parameter': backend.observation['parameters']['typo']=1
    if mutation=='nan': backend.observation['entities'][0]['bounding_box']['x0']=float('nan')
    if mutation=='missing_box': backend.observation['entities'][0].pop('bounding_box')
    if mutation=='duplicate': backend.observation['entities'].append(deepcopy(backend.observation['entities'][0]))
    if mutation=='shift': backend.observation['entities'][0]['bounding_box']['x0']+=1
    if mutation=='wrong_setting': backend.actual['settings.accuracy_db']['value']=-20
    if mutation=='missing_core_setting': backend.actual.pop('frequency.max')
    result=execute(tmp_path,prepared,backend)
    assert result['status'] in ('failed','blocked') and 'solve' not in backend.events


def td_success(setup):
    # Use native historical bytes for parser coverage, never call it this test's
    # native solve. Match that fixture's actual -50 dB steady state limit.
    return (ROOT/'MCP/CST/tests/fixtures/solver-evidence/td-wr90.log').read_text()


def set_accuracy(prepared,value):
    prepared.execution['setup']['settings']['accuracy_db']=value
    prepared.document=apply_to_ir(prepared.document,prepared.execution['setup'])
    prepared.execution['emitted_sha256']=digest([dict(title=b.title,code=b.code)
        for b in emit_vba.build_blocks(prepared.document)])


def test_save_readback_reauthorize_solve_export_order(tmp_path,prepared):
    set_accuracy(prepared,-50)
    backend=FakeBackend(prepared);backend.log=td_success(prepared.execution['setup'])
    def authorize(): backend.events.append('authorize')
    result=execute(tmp_path,prepared,backend,authorize)
    assert result['status']=='executed',result
    assert result['convergence']['converged'] is True
    assert result['export']['ports']==2 and result['export']['samples']==2
    events=backend.events;start=events.index('solve')
    assert events[start-2:start]==['authorize','save']
    assert events[start+1:start+3]==['save','export']
    assert events[-2:]==['authorize','close']
    assert events.index('read_setup')<start


def test_authorized_engineering_regression_cannot_claim_human_approval(tmp_path,prepared):
    set_accuracy(prepared,-50)
    prepared.approval_sha256=None
    backend=FakeBackend(prepared);backend.log=td_success(prepared.execution['setup'])
    result=execute(tmp_path,prepared,backend)
    assert result['status']=='executed' and result['execution_authorized'] is True
    assert result['approval_validated'] is False and result['approval_sha256'] is None


@pytest.mark.parametrize('fault',['history','solve','stale','wrong_ports','revoked','emit_changed'])
def test_execution_failure_retains_receipt_and_never_claims_executed(tmp_path,prepared,fault):
    set_accuracy(prepared,-50)
    backend=FakeBackend(prepared);backend.log=td_success(prepared.execution['setup'])
    backend.error=fault;backend.wrong_ports=fault=='wrong_ports';calls=[]
    if fault=='emit_changed': prepared.execution['emitted_sha256']='0'*64
    def authorize():
        calls.append(1)
        if fault=='revoked' and len(calls)==2: raise ValueError('synthetic approval revoked')
    result=execute(tmp_path,prepared,backend,authorize)
    assert result['status']=='failed',result
    assert (tmp_path/'execution/execution-receipt.json').is_file()
    if fault in ('revoked','history','emit_changed'): assert 'solve' not in backend.events
    if fault=='solve':
        assert result['solver_started'] is True and result['solver_returned'] is False
        assert (tmp_path/'execution/fresh-solver-logs.json').exists()
    if fault=='stale': assert result['convergence']['converged'] is not True


def test_native_log_paths_match_real_cst_companion_layout(tmp_path):
    backend=NativeBackend(None,'0'*64)
    assert backend.log_paths(tmp_path/'model.cst')['model']==tmp_path/'model/Result/Model.log'


def test_native_version_banner_is_preserved_in_cache_identity(prepared,tmp_path):
    from cst_lab.function_setup import cache_identity
    model=SimpleNamespace(GetApplicationVersion=lambda:'Version 2026.2 - Nov 28 2025')
    binary=tmp_path/'AMD64/CST DESIGN ENVIRONMENT_AMD64.exe'
    binary.parent.mkdir();binary.write_bytes(b'synthetic executable identity only; never launched')
    session=SimpleNamespace(info=SimpleNamespace(install_root=str(tmp_path)))
    runtime=NativeBackend(session,'b'*64).runtime(SimpleNamespace(model3d=model))
    identity,key=cache_identity(prepared.document,prepared.execution['setup'],runtime)
    assert identity['runtime']['cst_version']=='Version 2026.2 - Nov 28 2025'
    changed=dict(runtime,cst_version='Version 2026.2 - Nov 29 2025')
    assert cache_identity(prepared.document,prepared.execution['setup'],changed)[1]!=key


@pytest.mark.parametrize('monitor_count',[0,2,-1])
def test_native_setting_queries_preserve_actual_values_and_monitor_presence(tmp_path,prepared,monitor_count):
    # The requested mm/open boundaries must never be echoed as native results.
    model=SimpleNamespace(GetSolverType=lambda:'HF Time Domain',
        Solver=SimpleNamespace(GetFmin=lambda:0.,GetFmax=lambda:7.2),
        Units=SimpleNamespace(GetUnit=lambda dimension:'cm' if dimension=='Length' else 'GHz'),
        Boundary=SimpleNamespace(GetXmin=lambda:'electric'),
        Monitor=SimpleNamespace(GetNumberOfMonitors=lambda:monitor_count))
    actual=NativeBackend(None,'0'*64).read_setup(SimpleNamespace(model3d=model),prepared.execution['setup'],tmp_path)
    assert actual['units.length']['value']=='cm'
    assert actual['boundaries.xmin']['value']=='electric'
    assert 'value' not in actual['boundaries.xmax']
    if monitor_count==0:assert actual['monitors']['value']==[]
    else:assert 'error' in actual['monitors'] and 'value' not in actual['monitors']
