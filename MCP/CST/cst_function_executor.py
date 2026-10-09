"""Function-to-Guardian dispatch and reviewable execution diagnostics.

Simulation completion additionally requires CST evidence promotion, which is
kept separate from this worker's physical execution outcome.
"""
from dataclasses import asdict
import json
from pathlib import Path
import re
import shutil
import sys

from cst_lab.atomic import atomic_json, process_lock
from cst_lab.approval import ReviewAuthority
from cst_lab.function_contract import digest
from cst_lab.function_evidence import sha256, prepare_diagnostic
from cst_lab.function_model import prepare_simulation
from cst_lab.jobs import JobStore, JobSession
from cst_lab.paths import LabPaths

ROOT = Path(__file__).resolve().parents[2]


def execution_directory(root, ref):
    root=Path(root).resolve()
    if not re.fullmatch(r'job://[0-9a-f]{64}/[0-9a-f]{32}',ref):
        raise ValueError('invalid Function job reference')
    # Including both 64+32 reference components exceeded Win32 MAX_PATH once
    # CST companion names and atomic-write suffixes were appended. Hash the full
    # job identity (including attempt), and still refuse any existing directory.
    from cst_lab.paths import LabPaths
    directory=LabPaths.resolve(root).runs_root/'_function'/('native-'+digest(ref)[:32])
    for parent in (directory,*directory.parents):
        if parent==root: break
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('execution workspace must not contain linked ancestors')
    return directory


def executor_fingerprint():
    files = [Path(__file__), ROOT/'MCP/CST/tools/function_cst_worker.py']
    for source in ('MCP/CST/cst_guardian', 'MCP/CST-CAD/src/cst_cad', 'MCP/CST-Lab/src/cst_lab'):
        files.extend((ROOT/source).rglob('*.py'))
    return digest({p.relative_to(ROOT).as_posix(): sha256(p) for p in sorted(set(files))})


def cache_runtime_probe():
    """Identify executor/CST bytes without opening or connecting to CST.

    Not an installation/security check. No company/signature/DLL provenance
    inspection. A prior native receipt supplies the version for these bytes.
    """
    from cst_guardian.paths import discover_cst_root
    root=discover_cst_root()
    if root is None:return None
    binary=root/'AMD64/CST DESIGN ENVIRONMENT_AMD64.exe'
    if not binary.is_file():return None
    return dict(executor_sha256=executor_fingerprint(),cst_binary_sha256=sha256(binary))


def worker(root, ref, envelope_hash, phase='execute', reopen_hash=None):
    """Internal worker entry; re-authorize independently before starting CST."""
    root = Path(root).resolve()
    paths = LabPaths.resolve(root)
    store = JobStore(root, paths=paths)
    job = store.get(ref)  # validates the reference before using it in a path
    directory = execution_directory(root,ref)
    envelope = json.loads((directory/'dispatch.json').read_text(encoding='utf-8'))
    if digest(envelope) != envelope_hash or envelope['executor_sha256'] != executor_fingerprint():
        raise ValueError('dispatch or executor bytes changed before worker startup')
    if job['state'] != 'running' or job.get('owner_token') != envelope['owner_token']:
        raise ValueError('worker has no active owning Function job')
    session = JobSession(store, ref, envelope['owner_token'])
    authority = ReviewAuthority(paths.registry_root/'approval')

    def authorize():
        current = store.get(ref)
        if current['state'] != 'running' or current.get('owner_token') != envelope['owner_token']:
            raise ValueError('Function ownership ended before CST operation')
        prepared = prepare_simulation(current['request'], paths, authority)
        if asdict(prepared) != envelope['prepared']:
            raise ValueError('approved model, sources or effective settings changed after dispatch')
        return prepared

    with process_lock(directory/'worker.lock', timeout=0):
        if phase not in ('execute','reopen'):raise ValueError('unsupported internal worker phase')
        if (directory/('execution' if phase=='execute' else 'reopen')).exists():
            raise FileExistsError('this job already has a workspace for this phase')
        prepared = authorize()
        if phase=='reopen':
            reopen_request=json.loads((directory/'reopen-request.json').read_text(encoding='utf-8'))
            if not reopen_hash or digest(reopen_request)!=reopen_hash or reopen_request['job']!=ref:
                raise ValueError('reopen request identity changed')
        from cst_guardian.windows_job import require_current_job_containment
        atomic_json(directory/('containment.json' if phase=='execute' else 'reopen-containment.json'),require_current_job_containment())
        from cst_guardian.function_execution import NativeBackend, execute_prepared, verify_reopen
        from cst_guardian.session import GuardedSession
        with GuardedSession(force_new=True, restore_on_exit=False) as guarded:
            session_file=directory/('session.json' if phase=='execute' else 'reopen-session.json')
            atomic_json(session_file, guarded.info.to_json())
            backend=NativeBackend(guarded,envelope['executor_sha256'])
            if phase=='execute':
                receipt = execute_prepared(prepared, directory/'execution',backend, authorize, session.progress)
            else:
                receipt=verify_reopen(prepared,root,directory/'simulation/selected.cst',directory/'reopen',
                    reopen_request['model_snapshot_sha256'],backend,authorize,session.progress)
        atomic_json(session_file, guarded.info.to_json())
        return receipt


def execute(session, prepared):
    """Run one owned worker. Preserve diagnostics even on a hard timeout."""
    from cst_guardian.supervisor import run_guarded
    root = session.store.root
    directory = execution_directory(root,session.ref)
    directory.mkdir(parents=True, exist_ok=False)
    fingerprint = executor_fingerprint()
    envelope = dict(schema_version=1, owner_token=session.token, prepared=asdict(prepared),
                    executor_sha256=fingerprint)
    atomic_json(directory/'dispatch.json', envelope)
    session.progress('guardian-starting', {'workspace': str(directory)})
    try:
        report = run_guarded([sys.executable, str(ROOT/'MCP/CST/tools/function_cst_worker.py'),
            '--workspace-root', str(root), '--job', session.ref, '--dispatch-sha256', digest(envelope)],
            log_dir=directory/'guardian', timeout_s=1800, scope_worker_descendants=True, cwd=ROOT).to_json()
    except Exception as exc:
        report=dict(ok=False,outcome='launch-or-supervision-error',error=f'{type(exc).__name__}: {exc}')
    atomic_json(directory/'guardian-report.json', report)
    receipt_path = directory/'execution/execution-receipt.json'
    try:
        receipt = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {}
    except (ValueError,OSError) as exc:
        receipt={}
        atomic_json(directory/'worker-error.json',dict(error=f'cannot read worker receipt: {exc}'))
    status = receipt.get('status') if report['ok'] else 'failed'
    if status=='executed':
        try:
            return promote_execution(session,prepared,directory,envelope,receipt)
        except Exception as exc:
            atomic_json(directory/'promotion-error.json',dict(error=f'{type(exc).__name__}: {exc}'))
            status='failed'
            receipt['promotion_error']=f'{type(exc).__name__}: {exc}'
    if status not in ('failed', 'blocked'):
        status = 'failed'
        reason = 'Guardian worker did not produce a terminal execution receipt'
    else:
        reason = (receipt.get('promotion_error') or receipt.get('error') or 'worker execution failed') if report['ok'] else f'Guardian stopped the worker: {report["outcome"]}'
    stage = directory/'diagnostic'
    stage.mkdir()
    atomic_json(stage/'prepared-input.json',asdict(prepared))
    # Explicit allowlist: never copy dispatch credentials, Result/Temp, .lok or
    # a partial .cst into an archive that could be mistaken for simulation proof.
    for name in ('session.json', 'guardian-report.json', 'worker-error.json', 'containment.json',
                 'promotion-error.json','reopen-session.json','reopen-guardian-report.json'):
        if (directory/name).is_file():
            shutil.copy2(directory/name, stage/name)
    execution = directory/'execution'
    if (execution/'incremental').is_dir():
        shutil.copytree(execution/'incremental',stage/'incremental')
    for name in ('execution-receipt.json', 'model-ir.json', 'effective-setup.json', 'drc.json',
                 'observation.json', 'native-settings.json', 'readback-verification.json',
                 'log-checkpoints.json', 'fresh-solver-logs.json', 'solver-messages.json'):
        if (execution/name).is_file():
            shutil.copy2(execution/name, stage/name)
    for name in ('worker-stdout.txt', 'worker-stderr.txt'):
        if (directory/'guardian'/name).is_file():
            shutil.copy2(directory/'guardian'/name, stage/name)
    for name in ('reopen-receipt.json','observation.json','native-settings.json'):
        source=directory/'reopen'/name
        if source.is_file():shutil.copy2(source,stage/('reopen-'+name))
    atomic_json(stage/'diagnostic.json', dict(schema_version=1, job=session.ref, status=status,
        reason=reason, working_copy=str(execution/'working/model.cst'),
        solver_started=receipt.get('solver_started'),
        solver_start_observation='worker receipt' if 'solver_started' in receipt else 'unknown',
        claim='Execution diagnostics only; no completed simulation archive or reusable cache',
        executor_sha256=fingerprint))
    manifest_hash = prepare_diagnostic(stage, session.ref)
    return dict(status=status, error=reason, receipt=receipt, stage=stage, manifest_sha256=manifest_hash)


def promote_execution(session, prepared, directory, envelope, receipt):
    """Evaluate, independently reopen and seal; JobSession publishes last."""
    from cst_lab.function_simulation import prepare_stage,seal_stage
    from cst_guardian.supervisor import run_guarded
    paths=session.store.paths;request=session.store.get(session.ref)['request']
    authority=ReviewAuthority(paths.registry_root/'approval')
    def authorize():
        if asdict(prepare_simulation(request,paths,authority))!=asdict(prepared):
            raise ValueError('approved candidate changed before evidence publication')
    authorize()
    session.progress('staging-simulation-evidence')
    stage=directory/'simulation'
    summary=prepare_stage(request,prepared,directory/'execution',stage,paths,session.ref)
    reopen_request=dict(job=session.ref,model_snapshot_sha256=summary['model_snapshot_sha256'])
    atomic_json(directory/'reopen-request.json',reopen_request)
    session.progress('guardian-reopen-starting')
    report=run_guarded([sys.executable,str(ROOT/'MCP/CST/tools/function_cst_worker.py'),
        '--workspace-root',str(paths.workspace_root),'--job',session.ref,'--dispatch-sha256',digest(envelope),
        '--phase','reopen','--reopen-sha256',digest(reopen_request)],
        log_dir=directory/'reopen-guardian',timeout_s=300,scope_worker_descendants=True,cwd=ROOT).to_json()
    atomic_json(directory/'reopen-guardian-report.json',report)
    if not report['ok']:raise RuntimeError(f'cache-free reopen Guardian failed: {report["outcome"]}')
    reopened=json.loads((directory/'reopen/reopen-receipt.json').read_text(encoding='utf-8'))
    authorize()
    for source,target in [('guardian-report.json','guardian-report.json'),('session.json','session.json'),
        ('reopen-guardian-report.json','reopen-guardian-report.json'),('reopen-session.json','reopen-session.json'),
        ('reopen/observation.json','reopen-observation.json'),('reopen/native-settings.json','reopen-settings.json')]:
        shutil.copy2(directory/source,stage/target)
    for folder in ('guardian','reopen-guardian'):
        for source in (directory/folder).glob('*'):
            if source.is_file() and source.suffix in ('.txt','.png','.json'):
                target=stage/folder/source.name;target.parent.mkdir(exist_ok=True)
                shutil.copy2(source,target)
    manifest_hash=seal_stage(stage,session.ref,reopened)
    session.progress('promoting-simulation-evidence')
    original_session=json.loads((directory/'session.json').read_text(encoding='utf-8'))
    original_guardian=json.loads((directory/'guardian-report.json').read_text(encoding='utf-8'))
    return dict(status='completed',error=None,receipt=receipt,stage=stage,manifest_sha256=manifest_hash,
        audited=True,metrics=summary['metrics'],acceptance=summary['acceptance'],
        solver=dict(type=prepared.execution['setup']['solver'],seconds=receipt['timings']['solve_s'],
                    converged=receipt['convergence']['converged'],quiet_mode=original_session['quiet_mode'],
                    dialogs=[e for e in original_guardian['events'] if e.get('action')=='click'],
                    mesh=prepared.execution['setup']['mesh']))
