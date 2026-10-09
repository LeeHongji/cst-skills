"""Failure evidence follows the same durable publication protocol as analysis."""
import json
import pytest

from cst_lab.atomic import atomic_json
from cst_lab.function_evidence import prepare_diagnostic,validate_revision
from cst_lab.jobs import JobError
from test_function_jobs import store,request,fact


def stage_for(store,ref,status='blocked'):
    stage=store.root/'cst_runs/diagnostic';stage.mkdir(parents=True)
    atomic_json(stage/'diagnostic.json',dict(job=ref,status=status,solver_started=False))
    (stage/'worker-stderr.txt').write_text('Native readback unavailable; no solver start\n')
    return stage


@pytest.mark.parametrize('status',['blocked','failed'])
def test_failed_job_publishes_queryable_hashed_diagnostics_and_is_idempotent(store,status):
    ref=store.submit(request())
    stage=stage_for(store,ref,status)
    hashed=prepare_diagnostic(stage,ref)
    revision='r-'+ref.rsplit('/',1)[1]
    evidence=dict(kind='execution-diagnostic',revision=revision,manifest_sha256=hashed)
    base='artifact://'+ref[6:]+'/'
    artifacts={p.name:base+p.name for p in stage.iterdir()}
    with store.claim(ref) as session:
        session.finish(fact(store.get(ref),status=status,evidence=evidence,artifacts=artifacts),stage=stage)
    assert store.get(ref)['state']==status and store.submit(request())==ref
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'MCP/CST'))
    from cst_agent_api import FunctionService
    service=FunctionService(store.root)
    got=service.get(artifacts['worker-stderr.txt'])
    assert 'no solver start' in got['text']
    manifest=service.get(artifacts['manifest.json'])['document']
    assert manifest['kind']=='execution-diagnostic'
    assert not stage.exists()
    with open(got['path'],'a') as handle: handle.write('tampered')
    with pytest.raises(ValueError,match='changed'):service.get(artifacts['worker-stderr.txt'])


@pytest.mark.parametrize('change',['completed','cache_hit','wrong_status','cst_file','result_directory'])
def test_diagnostics_cannot_claim_simulation_completion_or_carry_caches(store,change):
    ref=store.submit(request())
    stage=stage_for(store,ref)
    if change=='cst_file':(stage/'model.cst').write_bytes(b'not a diagnostic')
    if change=='result_directory':(stage/'Result').mkdir()
    if change in ('cst_file','result_directory'):
        with pytest.raises(ValueError):prepare_diagnostic(stage,ref)
        return
    hashed=prepare_diagnostic(stage,ref)
    final=fact(store.get(ref),status='completed' if change=='completed' else 'failed' if change=='wrong_status' else 'blocked',
        cache_hit=change=='cache_hit',evidence=dict(kind='execution-diagnostic',
        revision='r-'+ref.rsplit('/',1)[1],manifest_sha256=hashed))
    with pytest.raises((ValueError,JobError)):
        with store.claim(ref) as session:session.finish(final,stage=stage)
    assert stage.exists()


def test_diagnostic_finalization_recovers_after_move_before_fact_append(store,monkeypatch):
    import cst_lab.function_evidence as evidence
    ref=store.submit(request());stage=stage_for(store,ref,'failed')
    hashed=prepare_diagnostic(stage,ref)
    real=evidence.complete_publication
    def interrupted(*args,**kwargs):
        real(*args,**kwargs)
        raise RuntimeError('synthetic interruption after rename')
    monkeypatch.setattr(evidence,'complete_publication',interrupted)
    with pytest.raises(RuntimeError):
        with store.claim(ref) as session:
            session.finish(fact(store.get(ref),status='failed',evidence=dict(kind='execution-diagnostic',
                revision='r-'+ref.rsplit('/',1)[1],manifest_sha256=hashed)),stage=stage)
    assert store.get(ref)['state']=='finalizing' and not stage.exists()
    monkeypatch.setattr(evidence,'complete_publication',real)
    assert store.recover(ref)=='failed'
    history=request().attempt_path(store.root).parent/'iterations.jsonl'
    before=history.read_bytes()
    assert store.recover(ref)=='failed' and history.read_bytes()==before
    assert len(history.read_text().splitlines())==1
