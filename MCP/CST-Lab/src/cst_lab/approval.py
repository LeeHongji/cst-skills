"""Artifact-bound approval, separate from untrusted MCP request arguments.

Only a server-side confirmation/delegation adapter may call complete_review. A
reviewer string supplied by an agent is not an attestation. HMAC protects the
persisted binding against accidental edits/untrusted API requests, not against
the local OS account owner who can read the server's key and execute Python.
"""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import secrets
from pathlib import Path

from .atomic import atomic_json, process_lock
from .contracts.attempt import ApprovalError, load_attempt, check_topology
from .paths import LabPaths
from .validation import load_schema, validate_document


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ReviewAuthority:
    """Key lives in local runtime state, never in a topic or the tool schema."""
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        with process_lock(self.directory/'key.lock'):
            key = self.directory/'approval.key'
            if not key.exists():
                key.write_bytes(secrets.token_bytes(32))
            self._key = key.read_bytes()
        if len(self._key) != 32:
            raise ApprovalError('invalid local approval authority key')

    def sign(self, binding):
        return hmac.new(self._key, digest(binding).encode(), hashlib.sha256).hexdigest()

    def verify(self, binding, signature):
        if not hmac.compare_digest(self.sign(binding), str(signature)):
            raise ApprovalError('approval attestation is missing, forged, or changed')


def _artifact(attempt_path, relative):
    root = Path(attempt_path).resolve().parent
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ApprovalError('audit artifact missing or outside attempt')
    return target


def prepare_review(attempt_path, audit_html, ranges, *, request=None):
    """Read-only preparation; can be performed before asking a human."""
    from cst_cad import audit, drc, ir
    path = Path(attempt_path).resolve(); attempt = load_attempt(path)
    artifact = _artifact(path, str(audit_html))
    metadata = audit.read_metadata(artifact)
    try:
        audit.verify_embedded_source(artifact,metadata)
    except audit.AuditError as exc:
        raise ApprovalError(str(exc)) from exc
    from .function_audit import review_inputs
    try:
        geometry_path,audit_manifest_sha256=review_inputs(path,artifact,LabPaths.resolve())
    except ValueError as exc:
        raise ApprovalError(str(exc)) from exc
    doc = ir.read(geometry_path); ir.require_valid(doc)
    report = drc.run(doc)
    if report['status'] != 'pass' or metadata.get('drc_status') != 'pass':
        raise ApprovalError('DRC must pass before approval')
    if metadata.get('drc_sha256') != digest(report):
        raise ApprovalError('audit DRC differs from current actual checks')
    for field, value in [('topology_hash', ir.topology_hash(doc)), ('model_intent_id', doc['model_intent_id'])]:
        if attempt.get(field) != value or metadata.get(field) != value:
            raise ApprovalError(f'{field} differs between attempt, IR and audit')
    baseline = {p['name']: p['value'] for p in doc['parameters']}
    if baseline != attempt['baseline_parameters'] or baseline != metadata.get('baseline_parameters'):
        raise ApprovalError('baseline parameters differ from audited IR')
    registration = metadata.get('source_registration')
    if registration:
        if registration.get('calibrated') is not True or not registration.get('citation') or not registration.get('method'):
            raise ApprovalError('source image must be calibrated with provenance')
        for field in ('physical_width', 'x', 'y', 'rotation_deg', 'pixel_width', 'pixel_height'):
            value = registration.get(field)
            if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value):
                raise ApprovalError('invalid source registration')
        if min(registration['physical_width'],registration['pixel_width'],registration['pixel_height']) <= 0:
            raise ApprovalError('invalid source registration scale')
    normalized = {}
    parameters = {p['name']: p for p in doc['parameters']}
    if not isinstance(ranges, dict):
        raise ApprovalError('explicit ranges object is required')
    for name, values in ranges.items():
        parameter = parameters.get(name, {})
        if not parameter.get('tunable') or parameter.get('expression'):
            raise ApprovalError(f'{name} is not an independent tunable parameter')
        if not isinstance(values, (list,tuple)) or len(values)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
            raise ApprovalError('range must contain two finite numeric bounds')
        low, high = values
        if not low <= baseline[name] <= high:
            raise ApprovalError(f'range for {name} must contain the audited value')
        if low < parameter.get('min',-math.inf) or high > parameter.get('max',math.inf):
            raise ApprovalError(f'range for {name} exceeds model limits')
        normalized[name] = [float(low),float(high)]
    binding = dict(attempt_path=str(path), attempt_sha256=file_digest(path),
                   audit_html=artifact.relative_to(path.parent).as_posix(),audit_sha256=file_digest(artifact),
                   artifact_id=metadata['artifact_id'], metadata_sha256=digest(metadata),
                   topology_hash=attempt['topology_hash'], model_intent_id=doc['model_intent_id'],
                   baseline_sha256=digest(baseline), ranges=normalized, drc_status='pass')
    if audit_manifest_sha256 is not None:
        binding['audit_manifest_sha256']=audit_manifest_sha256
    if request is not None:
        expected=dict(schema_version=1,kind='cst-approval-request',artifact_id=binding['artifact_id'],
                      audit_sha256=binding['audit_sha256'],topology_hash=binding['topology_hash'],
                      model_intent_id=binding['model_intent_id'],ranges=normalized)
        if request != expected:
            raise ApprovalError('exported request does not match the reviewed artifact and ranges')
    return binding


def complete_review(binding, *, authority, reviewer, channel, confirmation, authorization=None):
    """Internal adapter hook: confirmation binds the exact prepared artifact.

    Do not expose reviewer/channel/confirmation as cst_approve request fields.
    They are supplied by the server's confirmation adapter or a scoped active
    user delegation. The latter never claims personal viewing of an artifact.
    """
    if channel not in {'mcp-elicitation','local-operator-console','standing-user-authorization'} or not str(reviewer).strip():
        raise ApprovalError('authenticated human confirmation channel required')
    if channel == 'standing-user-authorization':
        from .standing_authorization import require_active
        grant = require_active(authority, binding['attempt_path'], authorization)
        if reviewer != grant['approved_by']:
            raise ApprovalError('reviewer differs from standing authorization')
    elif authorization is not None:
        raise ApprovalError('delegation requires the standing authorization channel')
    if confirmation != digest(binding):
        raise ApprovalError('human confirmation does not bind the review request')
    path=Path(binding['attempt_path'])
    with process_lock(authority.directory/(hashlib.sha256(str(path).encode()).hexdigest()+'.lock')):
        if authorization is not None:
            require_active(authority, path, authorization)
        current=prepare_review(path,binding['audit_html'],binding['ranges'])
        if current != binding:
            raise ApprovalError('review inputs changed while confirmation was pending')
        attempt=load_attempt(path)
        record={k:v for k,v in binding.items() if k not in {'attempt_path','attempt_sha256','ranges'}}
        record.update(approved_by=reviewer,approved_at=datetime.now(timezone.utc).isoformat(),
                      approved_ranges=binding['ranges'],channel=channel,confirmation_sha256=confirmation)
        if authorization is not None:
            record.update(authorization=authorization, human_reviewed=False)
        record['signature']=authority.sign(record)
        attempt['approval']=record; attempt['approved_ranges']=binding['ranges']; attempt['status']='running'
        paths=LabPaths.resolve();validate_document(attempt,load_schema(paths.schemas_root,'attempt.schema.json'),paths.schemas_root)
        atomic_json(path,attempt)
    return attempt


def verify_approval(attempt_path, *, authority):
    """Production gate; legacy unsigned reviewer records cannot grant execution."""
    path=Path(attempt_path);attempt=load_attempt(path);approval=attempt.get('approval')
    if not approval or not approval.get('signature'):
        raise ApprovalError('no authenticated approval record')
    signed=dict(approval);signature=signed.pop('signature');authority.verify(signed,signature)
    if approval.get('channel') == 'standing-user-authorization':
        from .standing_authorization import require_active
        grant = require_active(authority, path, approval.get('authorization'))
        if approval.get('human_reviewed') is not False or approval['approved_by'] != grant['approved_by']:
            raise ApprovalError('invalid delegated approval attribution')
    if approval['approved_ranges'] != attempt['approved_ranges'] or approval['baseline_sha256'] != digest(attempt['baseline_parameters']):
        raise ApprovalError('approved ranges or fixed baseline changed')
    fresh=prepare_review(path,approval['audit_html'],attempt['approved_ranges'])
    if fresh.get('audit_manifest_sha256')!=approval.get('audit_manifest_sha256'):
        raise ApprovalError('approval invalidated: audit manifest changed')
    for key in ('audit_sha256','metadata_sha256','topology_hash','model_intent_id','baseline_sha256','artifact_id','drc_status'):
        if fresh[key]!=approval[key]:
            raise ApprovalError(f'approval invalidated: {key} changed')
    return attempt


def check_effective_parameters(attempt, candidate):
    """Check ALL rebuilt parameters, including fixed and derived expressions."""
    from cst_cad.expressions import evaluate
    from cst_cad import ir
    ir.require_valid(candidate);check_topology(attempt,ir.topology_hash(candidate))
    parameters={p['name']:p for p in candidate['parameters']}
    baseline=attempt['baseline_parameters'];ranges=attempt['approved_ranges']
    if set(parameters)!=set(baseline):
        raise ApprovalError('full parameter set differs from approved model')
    values={k:p['value'] for k,p in parameters.items()}
    for name,p in parameters.items():
        value=p['value']
        if isinstance(value,bool) or not math.isfinite(value):
            raise ApprovalError('effective parameters must be finite')
        if p.get('expression'):
            if not math.isclose(value,evaluate(p['expression'],values),rel_tol=1e-10,abs_tol=1e-10):
                raise ApprovalError(f'derived parameter {name} does not match its expression')
        elif name in ranges:
            if not ranges[name][0] <= value <= ranges[name][1]:
                raise ApprovalError(f'effective parameter {name} outside approved range')
        elif value != baseline[name]:
            raise ApprovalError(f'fixed parameter {name} changed')
