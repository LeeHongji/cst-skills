"""Simulation publication tests with explicit in-memory CST doubles only."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'MCP/CST'),str(ROOT/'MCP/CST/tests')]
from test_function_execution import FakeBackend
from test_function_model import model_context
from cst_lab.function_model import prepare_simulation
from cst_lab.function_contract import RunRequest,digest
from cst_lab.atomic import atomic_json
from cst_lab.function_simulation import prepare_stage,seal_stage,read
from cst_lab.function_evidence import validate_revision
from cst_guardian.function_execution import execute_prepared,verify_reopen
from cst_agent_api import FunctionService
from cst_lab.function_incremental import plan as incremental_plan,copy_parent


class Backend(FakeBackend):
    def new_project(self,path):
        project=super().new_project(path)
        model=path.with_suffix('')/'Model/3D';model.mkdir(parents=True)
        (model/'ModelHistory.json').write_text('{"scope":"synthetic model, not native CST evidence"}')
        return project

    def open_project(self,path):
        self.events.append('open');self.path=path
        assert sorted(p.name for p in path.with_suffix('').iterdir())==['Model']
        return object()

    def export(self,project,stem,setup):
        target=super().export(project,stem,setup)
        frequency=setup['frequency'];low,high=frequency['min'],frequency['max']
        target.write_text('# GHz S RI R 50\n'+''.join(
            f'{low+(high-low)*i/100} .1 0 .9 0 .9 0 .1 0\n' for i in range(101)))
        return target


@pytest.fixture
def solved(model_context,monkeypatch):
    import cst_guardian.session
    def forbidden(*args,**kwargs):raise AssertionError('synthetic approval must never start native CST')
    monkeypatch.setattr(cst_guardian.session.GuardedSession,'__enter__',forbidden)
    paths,request,authority,_,attempt=model_context
    request=RunRequest.parse(dict(request,setup_delta=dict(settings=dict(accuracy_db=-50)))).document
    prepared=prepare_simulation(request,paths,authority)
    backend=Backend(prepared)
    backend.log=(ROOT/'MCP/CST/tests/fixtures/solver-evidence/td-wr90.log').read_text()
    execution=paths.workspace_root/'cst_runs/test-solve/execution'
    receipt=execute_prepared(prepared,execution,backend,lambda:None,lambda *args:None)
    assert receipt['status']=='executed',receipt
    return paths,request,prepared,execution,receipt


def staged(solved):
    paths,request,prepared,execution,_=solved
    stage=execution.parent/'simulation';job='job://'+'a'*64+'/'+'b'*32
    summary=prepare_stage(request,prepared,execution,stage,paths,job)
    return stage,job,summary


def reopen(solved,stage,summary,incomplete=False):
    paths,_,prepared,execution,_=solved
    backend=Backend(prepared);backend.incomplete=incomplete
    directory=execution.parent/'reopen'
    receipt=verify_reopen(prepared,paths.workspace_root,stage/'selected.cst',directory,
        summary['model_snapshot_sha256'],backend,lambda:None,lambda *args:None)
    for source,target in [('observation.json','reopen-observation.json'),('native-settings.json','reopen-settings.json')]:
        if (directory/source).exists():shutil.copy2(directory/source,stage/target)
    return receipt


def test_stage_requires_independent_clean_reopen_before_sealing(solved):
    stage,job,summary=staged(solved)
    assert not (stage/'manifest.json').exists() and summary['reopen']=='pending'
    with pytest.raises(ValueError,match='reopen receipt'):seal_stage(stage,job,{})
    receipt=reopen(solved,stage,summary)
    assert receipt['status']=='verified' and receipt['source_unchanged'] is True
    hashed=seal_stage(stage,job,receipt)
    assert validate_revision(stage,hashed)['kind']=='simulation'
    assert read(stage/'simulation.json')['acceptance']['status']=='pass'
    assert not list(stage.rglob('Result')) and not list(stage.rglob('Temp'))
    assert (stage/'model-source/model.py').is_file()
    assert (stage/'analysis/response-00.png').is_file()
    assert (stage/'vba/bundle.vba').is_file()
    with pytest.raises(ValueError,match='already sealed'):seal_stage(stage,job,receipt)


@pytest.mark.parametrize('damage',['not_converged','unapproved','export_changed','readback_forged','source_changed','locked','audit_changed'])
def test_preparation_refuses_unproven_or_changed_execution(solved,damage):
    paths,request,prepared,execution,receipt=solved
    if damage=='not_converged':receipt['convergence']['converged']=False
    if damage=='unapproved':receipt['approval_validated']=False
    if damage=='export_changed':(execution/receipt['export']['path']).write_text('# changed')
    if damage=='readback_forged':
        actual=read(execution/'native-settings.json');actual['settings.accuracy_db']['value']=-20
        atomic_json(execution/'native-settings.json',actual)
    if damage=='source_changed':
        source=RunRequest.parse(request).attempt_path(paths.workspace_root).parents[2]/'model.py'
        source.write_text(source.read_text()+'\n# changed during solve\n')
    if damage=='locked':(execution/'working/model/Model.lok').write_bytes(b'held')
    if damage=='audit_changed':
        attempt=RunRequest.parse(request).attempt_path(paths.workspace_root)
        with (attempt.parent/'audit.html').open('a',encoding='utf-8') as handle:handle.write('changed')
    atomic_json(execution/'execution-receipt.json',receipt)
    with pytest.raises((ValueError,RuntimeError)):staged(solved)
    if damage=='locked':assert (execution/'working/model/Model.lok').exists()


@pytest.mark.parametrize('damage',['missing_readback','changed_selected','changed_reopen_observation','wrong_runtime','no_close','missing_vba','source_tampered','source_added'])
def test_reopen_or_identity_failure_cannot_publish(solved,damage):
    stage,job,summary=staged(solved)
    receipt=reopen(solved,stage,summary,incomplete=damage=='missing_readback')
    if damage=='changed_selected':(stage/'selected.cst').write_bytes(b'changed after reopen')
    if damage=='changed_reopen_observation':
        observed=read(stage/'reopen-observation.json');observed['entities'][0]['bounding_box']['x0']+=1
        atomic_json(stage/'reopen-observation.json',observed)
    if damage=='wrong_runtime':receipt['runtime']['cst_version']='2025.1'
    if damage=='no_close':receipt['project_closed']=False
    if damage=='missing_vba':(stage/'vba/bundle.vba').unlink()
    if damage=='source_tampered':(stage/'model-source/model.py').write_text('# changed after execution')
    if damage=='source_added':(stage/'model-source/unexecuted.py').write_text('# not part of execution')
    with pytest.raises(ValueError):seal_stage(stage,job,receipt)


@pytest.mark.parametrize('publication_interrupt',[False,True])
def test_facade_finalizes_only_after_reopen_and_publishes_one_complete_fact(solved,monkeypatch,publication_interrupt):
    import cst_function_executor as executor
    import cst_guardian.supervisor
    paths,request,prepared,execution,receipt=solved
    service=FunctionService(paths.workspace_root)
    def guarded(argv,**kwargs):
        assert '--phase' in argv and argv[argv.index('--phase')+1]=='reopen'
        assert kwargs['scope_worker_descendants'] is True
        ref=argv[argv.index('--job')+1];directory=executor.execution_directory(paths.workspace_root,ref)
        summary=read(directory/'simulation/simulation.json')
        backend=Backend(prepared)
        verified=verify_reopen(prepared,paths.workspace_root,directory/'simulation/selected.cst',directory/'reopen',
            summary['model_snapshot_sha256'],backend,lambda:None,lambda *args:None)
        assert verified['status']=='verified'
        atomic_json(directory/'reopen-session.json',dict(quiet_mode=False,closed=True))
        return SimpleNamespace(to_json=lambda:dict(ok=True,outcome='completed',events=[]))
    monkeypatch.setattr(cst_guardian.supervisor,'run_guarded',guarded)
    def perform(session,candidate):
        assert asdict(candidate)==asdict(prepared)
        directory=executor.execution_directory(paths.workspace_root,session.ref);directory.mkdir(parents=True)
        shutil.copytree(execution,directory/'execution')
        atomic_json(directory/'session.json',dict(quiet_mode=False,closed=True))
        atomic_json(directory/'guardian-report.json',dict(ok=True,events=[dict(action='click',scope='synthetic')]))
        return executor.promote_execution(session,candidate,directory,dict(prepared=asdict(candidate)),receipt)
    monkeypatch.setattr(executor,'execute',perform)
    ref=service.store.submit(RunRequest.parse(request))
    if publication_interrupt:
        import cst_lab.function_evidence as evidence
        original=evidence.complete_publication
        def interrupted(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError('injected interruption after simulation archive publication')
        with monkeypatch.context() as patch:
            patch.setattr(evidence,'complete_publication',interrupted)
            with pytest.raises(RuntimeError,match='injected interruption'):
                with service.store.claim(ref) as session:service._execute(session)
        assert service.store.get(ref)['state']=='finalizing'
        attempt=RunRequest.parse(request).attempt_path(paths.workspace_root)
        history=attempt.parent/'iterations.jsonl'
        assert not history.exists() or not history.read_text().strip()
        # Resume the durable intent through a new store without re-executing CST.
        service=FunctionService(paths.workspace_root)
        assert service.store.recover(ref)=='completed'
        assert service.store.recover(ref)=='completed'
    else:
        with service.store.claim(ref) as session:service._execute(session)
    result=service.get(ref)
    assert result['state']=='completed' and result['result']['acceptance']['status']=='pass'
    assert service.store.submit(RunRequest.parse(request))==ref
    attempt=RunRequest.parse(request).attempt_path(paths.workspace_root)
    lines=(attempt.parent/'iterations.jsonl').read_text().splitlines()
    assert len(lines)==1
    fact=json.loads(lines[0]);assert fact['audited'] is True and fact['solver']['converged'] is True
    assert fact['solver']['quiet_mode'] is False and fact['solver']['dialogs'][0]['scope']=='synthetic'
    manifest=service.get(result['result']['artifacts']['manifest.json'])['document']
    assert manifest['kind']=='simulation'
    selected=service.get(result['result']['artifacts']['selected.cst'])
    assert Path(selected['path']).is_file()
    Path(selected['path']).write_bytes(b'tamper')
    with pytest.raises(ValueError):service.get(result['result']['artifacts']['simulation.json'])


@pytest.fixture
def incremental_case(solved,model_context):
    from cst_lab.contracts.iterations import append_iteration,iteration_line
    paths,request,prepared,execution,receipt=solved
    stage,job,summary=staged(solved)
    verified=reopen(solved,stage,summary);hashed=seal_stage(stage,job,verified)
    attempt=RunRequest.parse(request).attempt_path(paths.workspace_root)
    revision='r-'+job.rsplit('/',1)[-1]
    folder=attempt.parent/'evidence-revisions'/revision;shutil.copytree(stage,folder)
    fact=iteration_line(iter_number=0,job_id=job,request_sha256=RunRequest.parse(request).sha256,
        status='completed',fidelity='screen',provenance='native',audited=True,execution_kind='solver',
        execution=prepared.execution,metrics=summary['metrics'],acceptance=summary['acceptance'],
        solver=dict(converged=True),duration_s=0.,cache_hit=False,
        evidence=dict(kind='simulation',revision=revision,manifest_sha256=hashed))
    append_iteration(attempt.parent/'iterations.jsonl',fact,paths)
    request=dict(request,request_id='incremental-child',parent=0,param_delta={'l3':15.})
    child=prepare_simulation(request,paths,model_context[2])
    assert child.incremental is not None
    return solved,request,child,folder


def test_incremental_preflight_selects_verified_parent_and_does_not_copy_caches(incremental_case):
    from cst_lab.project_package import model_snapshot
    solved,request,child,folder=incremental_case
    assert child.incremental['updates']=={'l3':[13.9312,15.]}
    before=model_snapshot(folder/'selected.cst')
    copied=copy_parent(child.incremental,solved[0].workspace_root/'cst_runs/parent-copy/model.cst')
    assert model_snapshot(copied)==before==model_snapshot(folder/'selected.cst')
    assert sorted(p.name for p in copied.with_suffix('').iterdir())==['Model']


@pytest.mark.parametrize('damage',['model','manifest','iteration','changed-source','changed-setup'])
def test_incremental_refuses_corruption_and_rebuilds_incompatible_context(incremental_case,damage):
    solved,request,child,folder=incremental_case
    paths,_,_,_,_=solved
    attempt=RunRequest.parse(request).attempt_path(paths.workspace_root)
    fact=json.loads((attempt.parent/'iterations.jsonl').read_text())
    sources=deepcopy(child.source_manifest);doc=deepcopy(child.document)
    if damage=='model':(folder/'selected.cst').write_bytes(b'corrupted')
    if damage=='manifest':(folder/'manifest.json').write_text('{}')
    if damage=='iteration':fact['execution']['parameters']['l3']=14.
    if damage=='changed-source':sources[0]['sha256']='0'*64
    if damage=='changed-setup':doc['simulation']['settings']['accuracy_db']=-45
    if damage.startswith('changed'):
        assert incremental_plan(attempt,fact,doc,sources,child.approval_sha256) is None
    else:
        with pytest.raises(ValueError):incremental_plan(attempt,fact,doc,sources,child.approval_sha256)


@pytest.mark.parametrize('wrong_parent',[False,True])
def test_incremental_execution_checks_parent_before_update_and_preserves_evidence(incremental_case,wrong_parent):
    solved,request,child,folder=incremental_case
    paths,_,parent,_,_=solved
    class IncrementalBackend(Backend):
        def __init__(self):
            super().__init__(child);self.parent_backend=Backend(parent);self.updated=False
            self.log=(ROOT/'MCP/CST/tests/fixtures/solver-evidence/td-wr90.log').read_text()
        def new_project(self,path):raise AssertionError('incremental execution must not create a blank model')
        def observe(self,p,d):
            observed=deepcopy(super().observe(p,d) if self.updated else self.parent_backend.observation)
            if wrong_parent and not self.updated:observed['parameters']['l3']+=1
            return observed
        def read_setup(self,p,s,d):return self.actual if self.updated else self.parent_backend.actual
        def update_parameters(self,p,updates):
            self.events.append('parameter-update');self.updated=True
            return dict(parameters=[dict(parameter=k,before=v[0],after=v[1]) for k,v in updates.items()])
    backend=IncrementalBackend();execution=paths.workspace_root/'cst_runs/child/execution'
    receipt=execute_prepared(child,execution,backend,lambda:None,lambda *args:None)
    if wrong_parent:
        assert receipt['status']=='blocked' and 'parameter-update' not in backend.events and 'solve' not in backend.events
        return
    assert receipt['status']=='executed',receipt
    assert receipt['model_update']=='parent-parameter-update' and receipt['history']==[]
    assert backend.events.index('parameter-update')<backend.events.index('solve')
    child_solved=(paths,request,child,execution,receipt)
    stage,job,summary=staged(child_solved);verified=reopen(child_solved,stage,summary)
    hashed=seal_stage(stage,job,verified)
    assert validate_revision(stage,hashed)['kind']=='simulation'
    assert read(stage/'incremental/source.json')['parent_iteration']==0
