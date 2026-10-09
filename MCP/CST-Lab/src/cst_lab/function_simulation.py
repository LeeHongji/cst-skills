"""Stage complete simulation evidence before the final job publication intent.

This module never opens CST. A separate owned Guardian worker must reopen a
clean copy and return native readback before a stage can be sealed/published.
"""
import json
from pathlib import Path
import shutil

from .atomic import atomic_json
from .function_contract import RunRequest, digest
from .function_evidence import sha256
from .function_setup import cache_identity
from .project_package import copy_clean_model, model_snapshot, _clean_relative, BANNED_DIRECTORY_NAMES


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _verified(report, document, setup, observation, settings):
    from .function_readback import verify_readback
    recalculated=verify_readback(document,observation,setup,settings)
    if recalculated['status']!='verified' or recalculated!=report:
        raise ValueError('declared core native readback and explicit coverage are required for simulation promotion')


def prepare_stage(request, prepared, execution, stage, paths, job):
    """Freeze model, source, native logs and independently evaluated curves."""
    execution=Path(execution);stage=Path(stage)
    receipt=read(execution/'execution-receipt.json')
    if (receipt.get('status')!='executed' or any(receipt.get(k) is not True for k in
        ('solver_started','solver_returned','project_closed','approval_validated')) or
        receipt.get('approval_sha256')!=prepared.approval_sha256 or
        receipt.get('execution')!=prepared.execution or receipt.get('convergence',{}).get('converged') is not True):
        raise ValueError('physical execution receipt does not prove the approved completed solve')
    if read(execution/'model-ir.json')!=prepared.document or read(execution/'effective-setup.json')!=prepared.execution['setup']:
        raise ValueError('execution IR/settings differ from the prepared candidate')
    _verified(read(execution/'readback-verification.json'),prepared.document,prepared.execution['setup'],
              read(execution/'observation.json'),read(execution/'native-settings.json'))
    identity,key=cache_identity(prepared.document,prepared.execution['setup'],receipt['runtime'])
    if receipt.get('cache_identity')!=identity or receipt.get('cache_key')!=key:
        raise ValueError('execution runtime/cache identity is inconsistent')
    expected_export=f'exports/s-parameters.s{len(prepared.document["ports"])}p'
    if receipt.get('export',{}).get('path')!=expected_export:
        raise ValueError('execution export must name the expected port-count curve')
    if sha256(execution/expected_export)!=receipt['export'].get('sha256'):
        raise ValueError('solver export changed after the execution receipt')
    stage.mkdir(parents=True,exist_ok=False)
    snapshot=copy_clean_model(paths.workspace_root,execution/'working/model.cst',stage/'selected.cst')
    for name in ('execution-receipt.json','model-ir.json','effective-setup.json','drc.json',
                 'observation.json','native-settings.json','readback-verification.json',
                 'log-checkpoints.json','fresh-solver-logs.json','solver-messages.json'):
        shutil.copy2(execution/name,stage/name)
    shutil.copytree(execution/'vba',stage/'vba')
    if receipt.get('model_update')=='parent-parameter-update':
        shutil.copytree(execution/'incremental',stage/'incremental')
    attempt=RunRequest.parse(request).attempt_path(paths.workspace_root)
    design=attempt.parents[2]
    approved=read(attempt)
    if digest(approved.get('approval'))!=prepared.approval_sha256:
        raise ValueError('approval changed before evidence snapshot')
    review=stage/'review';review.mkdir()
    shutil.copy2(attempt,review/'attempt.json')
    if read(review/'attempt.json')!=approved:raise ValueError('attempt changed during evidence snapshot')
    audit=(attempt.parent/approved['approval']['audit_html']).resolve()
    if not audit.is_relative_to(attempt.parent.resolve()):raise ValueError('approved audit escapes its attempt')
    shutil.copy2(audit,review/'audit.html')
    if sha256(audit)!=approved['approval']['audit_sha256'] or sha256(review/'audit.html')!=approved['approval']['audit_sha256']:
        raise ValueError('approved audit bytes changed before promotion')
    for row in prepared.source_manifest:
        relative=Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('invalid source snapshot path')
        source=design/relative;target=stage/'model-source'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        if sha256(source)!=row['sha256']:raise ValueError('model source changed before promotion')
        shutil.copy2(source,target)
        if sha256(target)!=row['sha256'] or sha256(source)!=row['sha256']:
            raise ValueError('model source changed during promotion')
    from .function_offline import analyze
    offline=dict(request,operation='analyze',fidelity='offline',param_delta={},setup_delta={},
                 inputs=[(execution/expected_export).relative_to(paths.workspace_root).as_posix()])
    analysis,metrics,acceptance=analyze(offline,attempt,stage/'analysis',paths,lambda *args:None)
    if analysis['inputs'][0]['source_sha256']!=receipt['export']['sha256']:
        raise ValueError('solver export changed while evaluating curves')
    summary=dict(schema_version=1,job=job,fidelity=request['fidelity'],execution=prepared.execution,
        model_sources=prepared.source_manifest,design_contract=f'analysis/contract/{request["design"]}/design.md',
        approval_sha256=prepared.approval_sha256,model_snapshot_sha256=digest(snapshot),
        model_snapshot=snapshot,cache_identity=identity,cache_key=key,metrics=metrics,acceptance=acceptance,
        curve_sha256=analysis['inputs'][0]['source_sha256'],reopen='pending',
        claim='Simulation evidence; completion requires native cache-free reopen and final publication')
    atomic_json(stage/'simulation.json',summary)
    return summary


def seal_stage(stage, job, reopen_receipt):
    from .function_evidence import validate_revision
    stage=Path(stage)
    if (stage/'manifest.json').exists():raise ValueError('simulation stage is already sealed')
    summary=read(stage/'simulation.json')
    if summary['job']!=job:raise ValueError('simulation stage belongs to another job')
    if (reopen_receipt.get('status')!='verified' or
        any(reopen_receipt.get(k) is not True for k in ('project_closed','cache_free_before_open','source_unchanged','approval_validated')) or
        reopen_receipt.get('model_snapshot_sha256')!=summary['model_snapshot_sha256'] or
        reopen_receipt.get('runtime')!=summary['cache_identity']['runtime']):
        raise ValueError('native cache-free reopen receipt is incomplete or mismatched')
    _verified(reopen_receipt.get('verification',{}),read(stage/'model-ir.json'),read(stage/'effective-setup.json'),
              read(stage/'reopen-observation.json'),read(stage/'reopen-settings.json'))
    atomic_json(stage/'reopen-receipt.json',reopen_receipt)
    summary['reopen']='verified'
    atomic_json(stage/'simulation.json',summary)
    files=[]
    for path in sorted(stage.rglob('*')):
        if path.is_symlink() or path.is_junction():raise ValueError('simulation evidence must not contain links')
        relative=path.relative_to(stage)
        if any(p.casefold() in BANNED_DIRECTORY_NAMES for p in relative.parts):raise ValueError('simulation evidence contains a cache directory')
        _clean_relative(relative)
        if path.is_file():files.append(dict(path=relative.as_posix(),bytes=path.stat().st_size,sha256=sha256(path)))
    atomic_json(stage/'manifest.json',dict(schema_version=1,kind='simulation',job=job,files=files,
        claim='Approved simulation with exported curves and a verified cache-free CST reopen'))
    validate_revision(stage)
    return sha256(stage/'manifest.json')


def validate_simulation(directory, job):
    """Validate semantic bindings after the outer manifest verifies all bytes."""
    from cst_cad import ir
    directory=Path(directory)
    for path in directory.rglob('*'):
        relative=path.relative_to(directory)
        if any(p.casefold() in BANNED_DIRECTORY_NAMES for p in relative.parts):raise ValueError('simulation revision contains caches')
        _clean_relative(relative)
    summary=read(directory/'simulation.json');receipt=read(directory/'execution-receipt.json')
    required=('vba/bundle.vba','drc.json','log-checkpoints.json','fresh-solver-logs.json','solver-messages.json',
              'analysis/curves-00.csv','analysis/acceptance-samples-00.csv','analysis/response-00.png')
    if any(not (directory/name).is_file() for name in required):
        raise ValueError('simulation revision lacks required reproducibility evidence')
    contract=Path(summary['design_contract'])
    if contract.is_absolute() or '..' in contract.parts or not (directory/contract).is_file():
        raise ValueError('simulation design snapshot is missing or invalid')
    sources=summary['model_sources']
    if digest(sources)!=summary['execution']['model_source_sha256']:
        raise ValueError('model source inventory differs from executed source identity')
    names=[Path(row['path']).as_posix().casefold() for row in sources]
    actual={p.relative_to(directory/'model-source').as_posix().casefold()
            for p in (directory/'model-source').rglob('*') if p.is_file()}
    if len(set(names))!=len(names) or set(names)!=actual:
        raise ValueError('archived model source inventory has missing, duplicate or additional files')
    for row in sources:
        relative=Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts or sha256(directory/'model-source'/relative)!=row['sha256']:
            raise ValueError('archived model source differs from executed source bytes')
    if read(directory/'drc.json').get('status')!='pass':raise ValueError('simulation evidence has no passing DRC')
    document=read(directory/'model-ir.json');setup=read(directory/'effective-setup.json')
    ir.require_valid(document)
    identity,key=cache_identity(document,setup,receipt['runtime'])
    if (summary.get('job')!=job or summary.get('reopen')!='verified' or
        summary.get('execution')!=receipt.get('execution') or summary.get('cache_identity')!=identity or
        summary.get('cache_key')!=key or receipt.get('cache_key')!=key or receipt.get('cache_identity')!=identity or
        summary['execution']['setup']!=setup or summary['execution']['model_intent_id']!=document['model_intent_id']):
        raise ValueError('simulation execution identity differs from its evidence')
    if receipt.get('status')!='executed' or receipt.get('convergence',{}).get('converged') is not True:
        raise ValueError('simulation receipt lacks solver convergence')
    if any(receipt.get(k) is not True for k in ('solver_started','solver_returned','project_closed','approval_validated')):
        raise ValueError('simulation receipt lacks completed authorized execution')
    approved=read(directory/'review/attempt.json')
    if (digest(approved.get('approval'))!=summary['approval_sha256'] or receipt.get('approval_sha256')!=summary['approval_sha256'] or
        sha256(directory/'review/audit.html')!=approved['approval']['audit_sha256']):
        raise ValueError('simulation review snapshot is inconsistent')
    _verified(read(directory/'readback-verification.json'),document,setup,
              read(directory/'observation.json'),read(directory/'native-settings.json'))
    if receipt.get('model_update')=='parent-parameter-update':
        incremental=read(directory/'incremental/source.json')
        if receipt.get('incremental_parent_unchanged') is not True:
            raise ValueError('incremental source preservation is unproven')
        if digest(incremental)!=receipt.get('incremental_source_sha256'):
            raise ValueError('incremental parent binding changed')
        _verified(read(directory/'incremental/verification.json'),incremental['document'],incremental['setup'],
                  read(directory/'incremental/observation.json'),read(directory/'incremental/settings.json'))
        updates=read(directory/'incremental/parameter-update.json')
        expected=incremental['updates']
        actual={r['parameter']:[r['before'],r['after']] for r in updates['parameters']}
        if len(actual)!=len(updates['parameters']) or actual!=expected:
            raise ValueError('incremental parameter update evidence differs')
    snapshot=model_snapshot(directory/'selected.cst')
    if snapshot!=summary.get('model_snapshot') or digest(snapshot)!=summary['model_snapshot_sha256']:
        raise ValueError('selected CST model differs from the reopened content')
    reopened=read(directory/'reopen-receipt.json')
    if (reopened.get('status')!='verified' or reopened.get('model_snapshot_sha256')!=digest(snapshot) or
        any(reopened.get(k) is not True for k in ('project_closed','cache_free_before_open','source_unchanged','approval_validated')) or
        reopened.get('runtime')!=receipt['runtime']):
        raise ValueError('simulation revision has no matching cache-free reopen')
    _verified(reopened.get('verification',{}),document,setup,
              read(directory/'reopen-observation.json'),read(directory/'reopen-settings.json'))
    analysis=read(directory/'analysis/analysis.json')
    if sha256(directory/contract)!=analysis['design_sha256']:
        raise ValueError('simulation design snapshot differs from evaluated gates')
    if len(analysis['inputs'])!=1:raise ValueError('simulation must bind one exported dataset')
    curve=directory/f'analysis/source-00.s{len(document["ports"])}p'
    if sha256(curve)!=summary['curve_sha256'] or analysis['inputs'][0]['source_sha256']!=summary['curve_sha256']:
        raise ValueError('simulation curve differs from evaluated data')
    if receipt.get('export',{}).get('sha256')!=summary['curve_sha256']:
        raise ValueError('simulation curve differs from the actual solver export receipt')
    if summary['metrics']!=analysis['inputs'][0]['metrics'] or summary['acceptance']!=analysis['inputs'][0]['acceptance']:
        raise ValueError('simulation metrics differ from curve evaluation')
    return summary
