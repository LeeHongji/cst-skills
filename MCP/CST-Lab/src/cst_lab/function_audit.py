"""Offline, immutable CAD review preparation; approval remains a separate action."""
import json
from pathlib import Path
import shutil

from .atomic import atomic_json
from .contracts.attempt import load_attempt
from .contracts.design import load_design
from .contracts.iterations import read_iterations
from .function_contract import RunRequest, digest
from .function_evidence import sha256
from .function_model import load_model, source_manifest


def prepare(request, attempt_path, stage, paths, progress):
    from cst_cad import audit, drc, ir
    request = RunRequest.parse(request).document
    if request['operation'] != 'audit':
        raise ValueError('CAD review requires operation=audit')
    if any(request[k] for k in ('inputs', 'param_delta', 'setup_delta')) or request['parent'] is not None:
        raise ValueError('audit reviews the declared attempt baseline; put a changed baseline/topology in a new attempt, not audit deltas or curve inputs')
    attempt_path, stage = Path(attempt_path), Path(stage)
    attempt = load_attempt(attempt_path, paths)
    design = attempt_path.parents[2]
    header, _, _ = load_design(design/'design.md', paths)
    if any(header[field+'_id'] != request[field] for field in ('topic', 'design')):
        raise ValueError('audit design identity differs from request')
    script = (design/header['model']).resolve()
    if not script.is_relative_to(design.resolve()) or not script.is_file():
        raise ValueError('audit model source missing or outside design')
    sources = source_manifest(design)
    attempt_bytes, contract_bytes = attempt_path.read_bytes(), (design/'design.md').read_bytes()
    stage.mkdir(parents=True, exist_ok=False)
    progress('snapshot-model-source', {'files':len(sources)})
    for record in sources:
        target = stage/'model-source'/record['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(design/record['path'], target)
        if sha256(target) != record['sha256']:
            raise ValueError('audit source changed while copying')
    (stage/'attempt-snapshot.json').write_bytes(attempt_bytes)
    (stage/'design.md').write_bytes(contract_bytes)
    atomic_json(stage/'request.json', request)
    frozen_script = stage/'model-source'/script.relative_to(design.resolve())
    progress('rebuilding-audit-ir', {})
    default = load_model(frozen_script, {})
    baseline = attempt['baseline_parameters']
    if {p['name'] for p in default['parameters']} != set(baseline):
        raise ValueError('attempt parameter inventory differs from model')
    overrides = {p['name']:baseline[p['name']] for p in default['parameters'] if p.get('tunable') and not p.get('expression')}
    document = load_model(frozen_script, overrides)
    if (document['model_intent_id'] != attempt.get('model_intent_id') or ir.topology_hash(document) != attempt['topology_hash']
            or {p['name']:p['value'] for p in document['parameters']} != baseline):
        raise ValueError('model cannot reproduce the declared attempt baseline/identity; prepare a new matching attempt')
    progress('checking-drc', {})
    report = drc.run(document)
    ir.write(document, stage/'geometry-ir.json')
    atomic_json(stage/'drc.json', report)
    options = {}
    config = stage/'model-source/audit-source.json'
    if config.exists():
        settings = json.loads(config.read_text(encoding='utf-8'))
        if set(settings) != {'image', 'registration'} or not isinstance(settings['image'], str):
            raise ValueError('audit-source.json requires image and registration')
        image = (config.parent/settings['image']).resolve()
        if not image.is_relative_to(config.parent.resolve()) or not image.is_file():
            raise ValueError('audit source image must be inside frozen model source')
        options = dict(source_image=image, registration=settings['registration'])
    progress('rendering-webgl-audit', {})
    audit.write(document, stage/'audit.html', **options)
    metadata = audit.read_metadata(stage/'audit.html')
    # A model source is trusted repository code, not an OS sandbox. The route
    # itself never imports or calls a CST backend; snapshot drift still fails.
    if (source_manifest(design) != sources or attempt_path.read_bytes() != attempt_bytes
            or (design/'design.md').read_bytes() != contract_bytes):
        raise ValueError('audit inputs changed before sealing')
    receipt = dict(schema_version=1, kind='model-audit', operation='audit',
        request_sha256=digest(request), model_intent_id=document['model_intent_id'], topology_hash=ir.topology_hash(document),
        baseline_parameters=baseline, model_sources=sources, drc_status=report['status'],
        audit_sha256=sha256(stage/'audit.html'), artifact_id=metadata['artifact_id'], metadata_sha256=digest(metadata),
        approval_granted=False, human_reviewed=False, solver_started=False,
        readiness='ready_for_approval' if report['status']=='pass' else 'needs_correction')
    atomic_json(stage/'audit.json', receipt)
    return receipt


def seal(stage, job):
    from .function_evidence import _regular_tree, validate_revision
    stage = Path(stage)
    _regular_tree(stage)
    if (stage/'manifest.json').exists():
        raise ValueError('audit stage is already sealed')
    atomic_json(stage/'manifest.json', dict(schema_version=1, kind='model-audit', job=job,
        files=[dict(path=p.relative_to(stage).as_posix(), bytes=p.stat().st_size, sha256=sha256(p)) for p in sorted(stage.rglob('*')) if p.is_file()],
        claim='Offline CAD/DRC review preparation only; no CST invocation, simulation acceptance or approval granted'))
    validate_revision(stage)
    return sha256(stage/'manifest.json')


def validate(directory):
    """Validate sealed audit bindings without executing archived model Python."""
    from cst_cad import audit, ir
    directory = Path(directory)
    receipt = json.loads((directory/'audit.json').read_text(encoding='utf-8'))
    document = ir.read(directory/'geometry-ir.json')
    ir.require_valid(document)
    report = json.loads((directory/'drc.json').read_text(encoding='utf-8'))
    attempt = json.loads((directory/'attempt-snapshot.json').read_text(encoding='utf-8'))
    request = RunRequest.parse(json.loads((directory/'request.json').read_text(encoding='utf-8'))).document
    if request['operation'] != 'audit' or receipt.get('operation') != 'audit' or receipt.get('kind') != 'model-audit' or receipt.get('schema_version') != 1:
        raise ValueError('invalid model audit receipt')
    if any(receipt.get(k) is not False for k in ('approval_granted','human_reviewed','solver_started')):
        raise ValueError('audit cannot claim approval, personal viewing or a solve')
    metadata = audit.read_metadata(directory/'audit.html')
    audit.verify_embedded_source(directory/'audit.html', metadata)
    baseline = {p['name']:p['value'] for p in document['parameters']}
    for key, expected in dict(request_sha256=digest(request), audit_sha256=sha256(directory/'audit.html'),
            metadata_sha256=digest(metadata), artifact_id=metadata['artifact_id'], baseline_parameters=baseline,
            model_intent_id=document['model_intent_id'], topology_hash=ir.topology_hash(document),
            drc_status=report['status'], readiness='ready_for_approval' if report['status']=='pass' else 'needs_correction').items():
        if receipt.get(key) != expected:
            raise ValueError('audit receipt differs from frozen evidence: '+key)
    for key in ('model_intent_id','topology_hash','baseline_parameters'):
        if metadata.get(key) != receipt[key] or attempt.get(key) != receipt[key]:
            raise ValueError('audit metadata/attempt binding differs: '+key)
    if metadata.get('drc_sha256') != digest(report) or metadata.get('drc_status') != report['status']:
        raise ValueError('audit DRC binding differs')
    actual = [dict(path=p.relative_to(directory/'model-source').as_posix(),sha256=sha256(p))
              for p in sorted((directory/'model-source').rglob('*')) if p.is_file()]
    if actual != receipt.get('model_sources'):
        raise ValueError('audit model source inventory differs')
    return receipt


def latest_review(attempt_path, paths):
    """Select the newest finalized audit; a failed DRC is never skipped."""
    from .function_evidence import validate_revision
    attempt_path = Path(attempt_path)
    rows = read_iterations(attempt_path.parent/'iterations.jsonl', paths)
    audits = [row for row in rows if (row.get('evidence') or {}).get('kind') == 'model-audit']
    if not audits:
        return 'audit.html'  # Existing artifact-bound approvals remain supported.
    row = audits[-1]
    directory = attempt_path.parent/'evidence-revisions'/row['evidence']['revision']
    manifest = validate_revision(directory, row['evidence']['manifest_sha256'])
    if row['status'] != 'completed' or manifest['job'] != row['job_id'] or manifest['kind'] != 'model-audit':
        raise ValueError('latest audit is not a completed publication')
    return (directory/'audit.html').relative_to(attempt_path.parent).as_posix()


def review_inputs(attempt_path, artifact, paths):
    """Use a finalized revision's own IR, keeping legacy root audits readable."""
    from .function_evidence import validate_revision
    attempt_path, artifact = Path(attempt_path), Path(artifact)
    relative = artifact.relative_to(attempt_path.resolve().parent)
    if relative.parts[0] != 'evidence-revisions':
        return attempt_path.parent/'geometry-ir.json', None
    if len(relative.parts) != 3 or relative.name != 'audit.html':
        raise ValueError('invalid published audit path')
    rows = read_iterations(attempt_path.parent/'iterations.jsonl', paths)
    matches = [r for r in rows if (r.get('evidence') or {}).get('revision') == relative.parts[1]]
    if len(matches) != 1 or matches[0]['status'] != 'completed' or matches[0]['evidence']['kind'] != 'model-audit':
        raise ValueError('audit revision has no completed iteration')
    row = matches[0]
    manifest = validate_revision(artifact.parent, row['evidence']['manifest_sha256'])
    if manifest['job'] != row['job_id'] or manifest['kind'] != 'model-audit':
        raise ValueError('audit publication differs from its iteration')
    return artifact.parent/'geometry-ir.json', row['evidence']['manifest_sha256']
