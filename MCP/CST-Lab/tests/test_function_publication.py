"""Real process exits across the evidence/JSONL commit boundary; never CST."""
import pytest

from cst_lab.contracts.iterations import read_iterations
from cst_lab.function_evidence import prepare_analysis,validate_revision
from cst_lab.jobs import JobError
from test_function_jobs import store,request,child,completed,fact,PATHS


def location(store,ref):
    attempt=request().attempt_path(store.root)
    return attempt.parent/'evidence-revisions'/('r-'+ref.rsplit('/',1)[1])


@pytest.mark.parametrize('window',['intent','renamed','partial','appended'])
def test_abrupt_exit_publication_recovers_exactly_once(store,window):
    first=store.submit(request('prefix'))
    with store.claim(first) as session: session.finish(fact(store.get(first)))
    history=request().attempt_path(store.root).parent/'iterations.jsonl'
    prefix=history.read_bytes()
    ref=store.submit(request(parent=0))
    completed(child(store,'publication-'+window,ref),expected=74)
    assert store.get(ref)['state']=='finalizing'
    folder=location(store,ref)
    assert folder.exists()==(window!='intent')
    before=history.read_bytes()
    assert store.recover(ref)=='completed'
    intent=store.get(ref)['final_intent']
    assert validate_revision(folder,intent['fact']['evidence']['manifest_sha256'])['job']==ref
    after=history.read_bytes()
    assert after.startswith(before) and after.startswith(prefix)
    rows=read_iterations(history,PATHS)
    assert len(rows)==2 and rows[-1]['job_id']==ref
    assert rows[-1]['audited'] is False
    assert store.recover(ref)=='completed'
    assert history.read_bytes()==after
    assert store.submit(request(parent=0))==ref
    assert len(list(folder.parent.iterdir()))==1
    assert not (store.root/'cst_runs/analysis').exists()


@pytest.mark.parametrize('window',['intent','renamed'])
@pytest.mark.parametrize('damage',['file','manifest','extra','missing'])
def test_recovery_never_claims_completed_when_evidence_changed(store,window,damage):
    ref=store.submit(request())
    completed(child(store,'publication-'+window,ref),expected=74)
    folder=store.root/'cst_runs/analysis' if window=='intent' else location(store,ref)
    if damage=='file': (folder/'metrics.json').write_text('{}')
    elif damage=='manifest': (folder/'manifest.json').write_text('{}')
    elif damage=='extra': (folder/'unlisted.json').write_text('{}')
    else: (folder/'metrics.json').unlink()
    with pytest.raises(ValueError): store.recover(ref)
    assert store.get(ref)['state']=='finalizing'
    assert not (request().attempt_path(store.root).parent/'iterations.jsonl').exists()


def test_live_finish_seals_before_publishing_and_checks_job_identity(store):
    ref=store.submit(request())
    stage=store.root/'cst_runs/analysis';stage.mkdir(parents=True)
    (stage/'metrics.json').write_text('{}')
    expected=prepare_analysis(stage,ref)
    assert not location(store,ref).exists()
    final=fact(store.get(ref),evidence=dict(kind='offline-analysis',revision=location(store,ref).name,
                                         manifest_sha256=expected))
    with store.claim(ref) as session: session.finish(final,stage=stage)
    assert store.get(ref)['state']=='completed'
    validate_revision(location(store,ref),expected)


@pytest.mark.parametrize('damage',['job','revision','hash','kind'])
def test_invalid_publication_never_moves_evidence(store,damage):
    ref=store.submit(request())
    stage=store.root/'cst_runs/analysis';stage.mkdir(parents=True)
    (stage/'metrics.json').write_text('{}')
    expected=prepare_analysis(stage,ref if damage!='job' else 'job://'+'b'*64+'/'+'c'*32)
    evidence=dict(kind='offline-analysis',revision=location(store,ref).name,manifest_sha256=expected)
    if damage=='revision': evidence['revision']='r-'+'d'*32
    if damage=='hash': evidence['manifest_sha256']='e'*64
    if damage=='kind': evidence['kind']='cst-project'
    with pytest.raises((JobError,ValueError)):
        with store.claim(ref) as session: session.finish(fact(store.get(ref),evidence=evidence),stage=stage)
    assert stage.exists() and not location(store,ref).exists()
    assert store.get(ref)['state']=='failed'


def test_sealed_stage_is_not_resealed_over_existing_manifest(store):
    ref=store.submit(request())
    stage=store.root/'cst_runs/analysis';stage.mkdir(parents=True)
    (stage/'metrics.json').write_text('{}')
    expected=prepare_analysis(stage,ref)
    with pytest.raises(ValueError,match='already sealed'):prepare_analysis(stage,ref)
    validate_revision(stage,expected)


@pytest.mark.parametrize('target',['outside-runs','runs-root'])
def test_publication_rejects_staging_outside_a_run_subdirectory(store,target):
    ref=store.submit(request())
    stage=store.root/('staging' if target=='outside-runs' else 'cst_runs')
    stage.mkdir(parents=True,exist_ok=True)
    # Use outside-runs for a sealed stage; cst_runs itself contains registry
    # state, and must be rejected before any recursive publication.
    if target=='outside-runs':
        (stage/'metrics.json').write_text('{}')
        expected=prepare_analysis(stage,ref)
    else: expected='e'*64
    evidence=dict(kind='offline-analysis',revision=location(store,ref).name,manifest_sha256=expected)
    with pytest.raises(ValueError,match='below this workspace cst_runs'):
        with store.claim(ref) as session:session.finish(fact(store.get(ref),evidence=evidence),stage=stage)
    assert stage.exists() and not location(store,ref).exists()


def test_recovery_refuses_conflicting_existing_revision(store):
    ref=store.submit(request())
    completed(child(store,'publication-intent',ref),expected=74)
    folder=location(store,ref);folder.mkdir(parents=True)
    (folder/'manifest.json').write_text('{}')
    with pytest.raises(ValueError,match='manifest hash changed'):store.recover(ref)
    assert (folder/'manifest.json').read_text()=='{}'
    assert (store.root/'cst_runs/analysis/metrics.json').exists()
    assert store.get(ref)['state']=='finalizing'
