"""Strict task-level request/result contract, independent of CST or its model loader."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping


class RequestError(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def _number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise RequestError(f'{name} must be a finite number, not a boolean or numeric string')
    return float(value)


@dataclass(frozen=True)
class RunRequest:
    """Canonical fields. Aliases are reported, not silently ignored.

    Deltas specify new values; [old,new] also retains an explicit precondition.
    Setup nesting is preserved here and validated against effective setup in 4B.
    No caller can supply runtime versions, approval flags or reviewer identities.
    """
    document: dict[str, Any]
    converted_aliases: tuple[str, ...] = ()

    @classmethod
    def parse(cls, request: Mapping[str, Any]) -> 'RunRequest':
        if not isinstance(request, Mapping):
            raise RequestError('request must be an object')
        allowed = {'topic', 'design', 'attempt', 'request_id', 'operation', 'fidelity', 'why',
                   'param_delta', 'setup_delta', 'parent', 'inputs', 'parameters', 'setup'}
        if unknown := set(request) - allowed:
            raise RequestError(f'unknown request fields: {sorted(unknown)}')
        data = dict(request)
        aliases = []
        for old, new in [('parameters', 'param_delta'), ('setup', 'setup_delta')]:
            if old in data:
                if new in data:
                    raise RequestError(f'{old} and {new} cannot both be supplied')
                data[new] = data.pop(old)
                aliases.append(f'{old}->{new}')
        for key in ('topic', 'design', 'attempt'):
            if not isinstance(data.get(key), str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', data[key]):
                raise RequestError(f'{key} must be a contract ID, not a filesystem path')
        if not isinstance(data.get('request_id'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', data['request_id']):
            raise RequestError('request_id is required for idempotent retry (1–128 safe characters)')
        if not isinstance(data.get('why'), str) or not data['why'].strip():
            raise RequestError('why must state the purpose of this request')
        data.setdefault('fidelity', 'offline')
        if data['fidelity'] not in ('offline', 'screen', 'confirm'):
            raise RequestError('fidelity must be offline, screen or confirm')
        data.setdefault('operation', 'analyze' if data['fidelity'] == 'offline' else 'simulate')
        if data['operation'] not in ('audit', 'analyze', 'compare', 'simulate'):
            raise RequestError('operation must be audit, analyze, compare or simulate')
        if (data['operation'] == 'simulate') != (data['fidelity'] != 'offline'):
            raise RequestError('simulate requires screen/confirm; other operations require offline')
        data.setdefault('parent', None)
        if data['parent'] is not None and (type(data['parent']) is not int or data['parent'] < 0):
            raise RequestError('parent must be a nonnegative iteration number or null')
        data.setdefault('param_delta', {})
        data.setdefault('setup_delta', {})
        for key in ('param_delta', 'setup_delta'):
            if not isinstance(data[key], dict) or any(not isinstance(k, str) or not k for k in data[key]):
                raise RequestError(f'{key} must be an object with nonempty string keys')
        values = {}
        for name, value in data['param_delta'].items():
            if isinstance(value, list):
                if len(value) != 2:
                    raise RequestError(f'param_delta.{name} must be a number or [old,new]')
                values[name] = [_number(v, name) for v in value]
            else:
                values[name] = _number(value, name)
        data['param_delta'] = values
        data.setdefault('inputs', [])
        if not isinstance(data['inputs'], list) or any(not isinstance(x, str) or not x.strip() for x in data['inputs']):
            raise RequestError('inputs must be a list of evidence references')
        if data['operation'] in ('analyze', 'compare'):
            if data['param_delta'] or data['setup_delta']:
                raise RequestError('source-data analysis cannot apply model or solver deltas')
            if len(data['inputs']) < (2 if data['operation'] == 'compare' else 1):
                raise RequestError('analysis needs source evidence; compare needs at least two inputs')
        try:
            # Copy nested structures and reject NaN, arbitrary objects and non-JSON values.
            data = json.loads(canonical(data))
        except (TypeError, ValueError) as exc:
            raise RequestError(f'request must contain finite JSON data: {exc}') from exc
        return cls(data, tuple(aliases))

    @property
    def sha256(self):
        return digest(self.document)

    def attempt_path(self, root: Path) -> Path:
        d = self.document
        projects = (Path(root).resolve() / 'projects').resolve()
        if not projects.is_relative_to(Path(root).resolve()):
            raise RequestError('projects resolves outside the workspace')
        path = (projects / d['topic'] / 'designs' / d['design'] / 'attempts' / d['attempt'] / 'attempt.json').resolve()
        if not path.is_relative_to(projects):
            raise RequestError('attempt resolves outside projects')
        return path


def result(*, status, job, job_status, fidelity, acceptance=None, metrics=None,
           artifacts=None, duration_s=0., cache_hit=False, next_action=None, error=None):
    """API completion is separate from acceptance and simulation fidelity."""
    if status not in ('queued', 'running', 'completed', 'blocked', 'failed'):
        raise RequestError('invalid API status')
    if job_status not in ('queued', 'running', 'finalizing', 'completed', 'failed', 'blocked'):
        raise RequestError('invalid job status')
    if status != ('running' if job_status == 'finalizing' else job_status):
        raise RequestError('API status conflicts with job lifecycle')
    if fidelity not in ('offline', 'screen', 'confirm'):
        raise RequestError('invalid fidelity')
    if type(cache_hit) is not bool:
        raise RequestError('cache_hit must be boolean')
    if cache_hit and status != 'completed':
        raise RequestError('only a completed request can be a cache hit')
    acceptance = acceptance or {'status': 'not_evaluated', 'gates': []}
    if acceptance.get('status') not in ('pass', 'fail', 'error', 'not_evaluated') or not isinstance(acceptance.get('gates'), list):
        raise RequestError('invalid acceptance')
    duration = _number(duration_s, 'duration_s')
    if duration < 0:
        raise RequestError('duration_s cannot be negative')
    return json.loads(canonical(dict(status=status, job=job, job_status=job_status, fidelity=fidelity,
        acceptance=acceptance, metrics=metrics or {}, artifacts=artifacts or {}, duration_s=duration,
        cache_hit=cache_hit, next_action=next_action, error=error)))
