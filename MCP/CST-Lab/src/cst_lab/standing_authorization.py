"""Explicit operator delegation stored outside the three-tool request surface.

Enrollment is a local operator action backed by an actual user instruction.
Like ReviewAuthority, this is not an OS-account security boundary. A tool
argument cannot enroll a grant or supply its signer/confirmation evidence.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .atomic import atomic_json, process_lock
from .approval import digest
from .contracts.attempt import ApprovalError, load_attempt


def enroll(authority, *, workspace_root, topic_id, approved_by, statement, source):
    """Internal operator hook; never expose through cst_run/get/approve."""
    if not re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', topic_id):
        raise ApprovalError('invalid authorization topic')
    if not all(isinstance(v, str) and v.strip() for v in (approved_by, statement, source)):
        raise ApprovalError('explicit user statement and provenance required')
    root = Path(workspace_root).resolve()
    if not (root/'projects'/topic_id).is_dir():
        raise ApprovalError('authorization topic must already exist')
    grant = dict(schema_version=1, kind='standing-user-authorization',
                 workspace_root=str(root), topic_id=topic_id, approved_by=approved_by,
                 statement=statement, source=source,
                 recorded_at=datetime.now(timezone.utc).isoformat())
    grant['signature'] = authority.sign(grant)
    path = authority.directory/'standing'/f'{topic_id}.json'
    with process_lock(authority.directory/'standing'/f'{topic_id}.lock'):
        if path.exists():
            raise ApprovalError('standing authorization already enrolled; explicit revocation required before replacement')
        atomic_json(path, grant)
    return grant


def applicable(authority, attempt_path):
    """Return the signed active grant for this exact workspace/topic, if any."""
    path = Path(attempt_path).resolve()
    attempt = load_attempt(path)
    topic = attempt['topic_id']
    if not re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', topic):
        raise ApprovalError('invalid authorization topic')
    grant_path = authority.directory/'standing'/f'{topic}.json'
    if not grant_path.exists():
        return None
    grant = json.loads(grant_path.read_text(encoding='utf-8'))
    unsigned = dict(grant); signature = unsigned.pop('signature', None)
    authority.verify(unsigned, signature)
    if grant.get('kind') != 'standing-user-authorization' or grant.get('schema_version') != 1:
        raise ApprovalError('invalid standing authorization')
    root = Path(grant['workspace_root']).resolve()
    expected = root/'projects'/topic/'designs'/attempt['design_id']/'attempts'/attempt['attempt_id']/'attempt.json'
    # Lexical AND resolved paths must agree; junctions cannot expand the scope.
    if grant['topic_id'] != topic or path != expected or expected.resolve() != expected:
        raise ApprovalError('attempt is outside the authorized workspace/topic')
    return grant


def require_active(authority, attempt_path, grant):
    current = applicable(authority, attempt_path)
    if current is None or digest(current) != digest(grant):
        raise ApprovalError('standing authorization was revoked or changed')
    return current
