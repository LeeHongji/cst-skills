"""Exact, source-backed reuse of native simulation evidence without CST.

The append-only attempt history is the index. Only native simulation revisions
are candidates; cache results cannot recursively masquerade as new solves.
Each hit copies the complete verified source simulation into its own immutable
revision, reevaluates current gates, and records no new solver/reopen action.
"""
import json
from pathlib import Path
import shutil

from .atomic import atomic_json
from .function_contract import RunRequest,digest
from .function_evidence import sha256,validate_revision
from .function_offline import analyze
from .function_setup import cache_identity
from .contracts.iterations import read_iterations


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def comparable(execution):
    # Request syntax can differ while the complete effective setup is equal.
    return {k:v for k,v in execution.items() if k!='setup_overrides'}


def find(attempt,prepared,paths,runtime_probe):
    if prepared.execution['setup']['fidelity']=='confirm' or runtime_probe is None:return None
    if set(runtime_probe)!={'executor_sha256','cst_binary_sha256'}:
        raise ValueError('cache lookup requires trusted executor and CST binary identity')
    attempt=Path(attempt);base=attempt.parent/'evidence-revisions'
    for row in reversed(read_iterations(attempt.parent/'iterations.jsonl',paths)):
        if (row.get('status')!='completed' or row.get('provenance')!='native' or row.get('audited') is not True
            or row.get('cache_hit') is not False or row.get('evidence',{}).get('kind')!='simulation'
            or comparable(row.get('execution',{}))!=comparable(prepared.execution)):
            continue
        binding=row['evidence'];folder=(base/binding['revision']).resolve()
        if folder.parent!=base.resolve():raise ValueError('cache source escapes attempt')
        manifest=validate_revision(folder,binding['manifest_sha256'])
        summary=read(folder/'simulation.json')
        if manifest['job']!=row['job_id'] or summary['execution']!=row['execution']:
            raise ValueError('cache iteration differs from immutable simulation')
        runtime=summary['cache_identity']['runtime']
        if any(runtime.get(k)!=v for k,v in runtime_probe.items()):continue
        identity,key=cache_identity(prepared.document,prepared.execution['setup'],runtime)
        if summary['cache_key']!=key or summary['cache_identity']!=identity:continue
        if summary['model_sources']!=prepared.source_manifest:continue
        return dict(folder=folder,source=dict(iteration=row['iter'],job=row['job_id'],
            revision=binding['revision'],manifest_sha256=binding['manifest_sha256']),runtime=runtime)
    return None


def prepare(request,prepared,match,stage,paths,job,authorize,progress):
    """Freeze the prior simulation and current approval; evaluate today's gates."""
    authorize();stage=Path(stage);stage.mkdir(parents=True,exist_ok=False)
    source=match['folder'];bound=match['source']
    validate_revision(source,bound['manifest_sha256'])
    progress('reusing-verified-simulation',{'source_job':bound['job'],'cst_launches':0})
    shutil.copytree(source,stage/'source-simulation')
    validate_revision(stage/'source-simulation',bound['manifest_sha256'])
    # Verify source again to reject a change during copying.
    validate_revision(source,bound['manifest_sha256'])
    attempt=RunRequest.parse(request).attempt_path(paths.workspace_root)
    review=stage/'review';review.mkdir()
    shutil.copy2(attempt,review/'attempt.json')
    approved=read(review/'attempt.json')
    if digest(approved.get('approval'))!=prepared.approval_sha256:raise ValueError('cache approval changed')
    shutil.copy2(attempt.parent/approved['approval']['audit_html'],review/'audit.html')
    atomic_json(stage/'model-ir.json',prepared.document)
    atomic_json(stage/'effective-setup.json',prepared.execution['setup'])
    from cst_cad import drc
    effective_drc=drc.run(prepared.document)
    if effective_drc['status']!='pass':raise ValueError('effective cache model DRC failed')
    atomic_json(stage/'drc.json',effective_drc)
    curve=stage/'source-simulation/analysis'/f'source-00.s{len(prepared.document["ports"])}p'
    analysis_request=dict(request,operation='analyze',fidelity='offline',param_delta={},setup_delta={},
                          inputs=[curve.relative_to(paths.workspace_root).as_posix()])
    analysis,metrics,acceptance=analyze(analysis_request,attempt,stage/'analysis',paths,progress)
    identity,key=cache_identity(prepared.document,prepared.execution['setup'],match['runtime'])
    summary=dict(schema_version=1,job=job,source=bound,execution=prepared.execution,
        fidelity=prepared.execution['setup']['fidelity'],cache_identity=identity,cache_key=key,
        approval_sha256=prepared.approval_sha256,curve_sha256=sha256(curve),
        metrics=metrics,acceptance=acceptance,solver_started=False,cst_launches=0,
        claim='Reuse of a previously converged, independently reopened native simulation; no new solve or reopen')
    atomic_json(stage/'cache.json',summary)
    authorize()
    files=[dict(path=p.relative_to(stage).as_posix(),bytes=p.stat().st_size,sha256=sha256(p))
           for p in sorted(stage.rglob('*')) if p.is_file()]
    atomic_json(stage/'manifest.json',dict(schema_version=1,kind='cache-reuse',job=job,files=files,claim=summary['claim']))
    validate_revision(stage)
    return dict(status='completed',audited=True,stage=stage,manifest_sha256=sha256(stage/'manifest.json'),
        metrics=metrics,acceptance=acceptance,receipt=dict(solver_started=False),cache_hit=True)


def validate(directory,job):
    """No recursive cache chaining: the embedded source must be a simulation."""
    directory=Path(directory);summary=read(directory/'cache.json')
    source=summary['source'];folder=directory/'source-simulation'
    # Check kind before recursion, including malicious nested cache manifests.
    if read(folder/'manifest.json').get('kind')!='simulation':raise ValueError('cache source must be a native simulation')
    manifest=validate_revision(folder,source['manifest_sha256'])
    original=read(folder/'simulation.json')
    if (summary['job']!=job or manifest['job']!=source['job'] or
        source['revision']!='r-'+source['job'].rsplit('/',1)[-1] or
        comparable(original['execution'])!=comparable(summary['execution'])):
        raise ValueError('cache source execution identity differs')
    document=read(directory/'model-ir.json');setup=read(directory/'effective-setup.json')
    identity,key=cache_identity(document,setup,original['cache_identity']['runtime'])
    if (identity!=original['cache_identity'] or identity!=summary['cache_identity'] or key!=summary['cache_key'] or
        setup!=summary['execution']['setup'] or summary['fidelity']!=setup['fidelity'] or
        document!=read(folder/'model-ir.json') or summary['solver_started'] is not False or summary['cst_launches']!=0):
        raise ValueError('cache identity or no-solve claim is inconsistent')
    from cst_cad import drc
    report=drc.run(document)
    if report['status']!='pass' or read(directory/'drc.json')!=report:raise ValueError('cache DRC is inconsistent')
    approved=read(directory/'review/attempt.json')
    if (digest(approved.get('approval'))!=summary['approval_sha256'] or
        sha256(directory/'review/audit.html')!=approved['approval']['audit_sha256']):
        raise ValueError('cache current approval snapshot changed')
    curve=directory/'analysis'/f'source-00.s{len(document["ports"])}p'
    analysis=read(directory/'analysis/analysis.json')
    if (len(analysis['inputs'])!=1 or sha256(curve)!=original['curve_sha256'] or
        sha256(curve)!=summary['curve_sha256'] or analysis['inputs'][0]['source_sha256']!=summary['curve_sha256'] or
        analysis['inputs'][0]['metrics']!=summary['metrics'] or analysis['inputs'][0]['acceptance']!=summary['acceptance']):
        raise ValueError('cache curves or reevaluated metrics differ')
    contracts=list((directory/'analysis/contract').glob('*/design.md'))
    if len(contracts)!=1 or sha256(contracts[0])!=analysis['design_sha256']:raise ValueError('cache gate snapshot differs')
    return summary
