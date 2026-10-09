"""Process-coordinated jobs; final numerical facts remain append-only JSONL.

Runtime coordination is deliberately not a rebuildable scientific index. OS
leases protect a live worker, including while it has not emitted a heartbeat.
A durable finalization intent bridges the job-state/JSONL crash window.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from .atomic import atomic_json, process_lock, read_json
from .contracts.attempt import load_attempt
from .contracts.iterations import iteration_line, read_iterations, _check_order, iteration_lock_path
from .function_contract import RunRequest, canonical, digest, result
from .paths import LabPaths
from .validation import load_schema, validate_document


class JobError(RuntimeError):
    pass


class JobBusy(JobError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class JobStore:
    def __init__(self, root: Path, *, paths: LabPaths | None = None):
        self.root = Path(root).resolve()
        self.paths = paths or LabPaths.resolve(self.root)
        self.runtime = LabPaths.resolve(self.root).registry_root / 'function-jobs'

    def _directory(self, ref):
        match = re.fullmatch(r'job://([0-9a-f]{64})/([0-9a-f]{32})', ref)
        if not match:
            raise JobError('invalid job reference')
        return self.runtime / match[1], match[2]

    def _load(self, directory):
        return read_json(directory / 'state.json')

    def get(self, ref):
        directory, key = self._directory(ref)
        state = self._load(directory)
        if key not in state['jobs']:
            raise JobError('unknown job')
        return state['jobs'][key]

    def pending(self, ref):
        directory, _ = self._directory(ref)
        state = self._load(directory)
        return sorted((j for j in state['jobs'].values() if j['state'] in ('queued','running','finalizing')), key=lambda j:j['iteration'])

    def response(self, ref):
        job = self.get(ref)
        if job.get('result'):
            return job['result']
        return result(status='queued' if job['state'] == 'queued' else 'running', job=ref,
                      job_status=job['state'], fidelity=job['request']['fidelity'],
                      next_action='cst_get this job reference')

    def submit(self, request: RunRequest):
        # Parse again: do not trust a caller mutating the dataclass's nested dict.
        aliases = request.converted_aliases
        request = RunRequest.parse(request.document)
        attempt_path = request.attempt_path(self.root)
        relative = attempt_path.relative_to(self.root).as_posix()
        directory = self.runtime / digest(relative)
        key = digest(request.document['request_id'])[:32]
        ref = f'job://{directory.name}/{key}'
        with process_lock(directory / 'coordination.lock'):
            state = self._load(directory) if (directory / 'state.json').exists() else {'attempt': relative, 'jobs': {}}
            if key in state['jobs']:
                if state['jobs'][key]['request_sha256'] != request.sha256:
                    raise JobError('request_id already names different content')
                return ref
            attempt = load_attempt(attempt_path, self.paths)
            for field, contract in [('topic', 'topic_id'), ('design', 'design_id'), ('attempt', 'attempt_id')]:
                if request.document[field] != attempt[contract]:
                    raise JobError(f'{field} differs from attempt contract')
            history = attempt_path.parent / 'iterations.jsonl'
            with process_lock(iteration_lock_path(history, self.paths)):
                rows = read_iterations(history, self.paths)
                used = {row['iter'] for row in rows} | {job['iteration'] for job in state['jobs'].values()}
                if len(used) >= attempt['max_iterations']:
                    raise JobError('max_iterations exhausted, including queued reservations')
                parent = request.document['parent']
                if parent is not None and parent not in {r['iter'] for r in rows}:
                    raise JobError('parent must name a finalized iteration in this attempt')
                number = max(used, default=-1) + 1
                state['jobs'][key] = dict(ref=ref, request=request.document, request_sha256=request.sha256,
                    iteration=number, state='queued', submitted_at=now(), final_intent=None, result=None,
                    converted_aliases=list(aliases))
                atomic_json(directory / 'state.json', state)
        return ref

    @contextmanager
    def claim(self, ref):
        directory, key = self._directory(ref)
        # One live execution per attempt. Queue submission uses a separate lock.
        with ExitStack() as lease:
            try:
                lease.enter_context(process_lock(directory / 'execution.lock', timeout=0))
            except TimeoutError as exc:
                raise JobBusy('attempt has an active execution lease') from exc
            with process_lock(directory / 'coordination.lock'):
                state = self._load(directory)
                job = state['jobs'][key]
                pending = sorted((j for j in state['jobs'].values() if j['state'] in ('queued', 'running', 'finalizing')), key=lambda j: j['iteration'])
                if job['state'] != 'queued' or not pending or pending[0]['ref'] != ref:
                    raise JobBusy('job is not the first queued job; recover earlier abandoned work first')
                token = uuid.uuid4().hex
                job.update(state='running', started_at=now(), owner_pid=os.getpid(), owner_token=token)
                atomic_json(directory / 'state.json', state)
            session = JobSession(self, ref, token)
            try:
                yield session
            except BaseException as exc:
                session.fail(f'{type(exc).__name__}: {exc}')
                raise
            finally:
                session.fail('worker exited without finalizing a result')

    def _finalize(self, ref, token, fact, *, stage=None):
        directory, key = self._directory(ref)
        with process_lock(directory / 'coordination.lock'):
            state = self._load(directory)
            job = state['jobs'][key]
            if job['state'] != 'running' or job.get('owner_token') != token:
                raise JobError('job is not owned by this running session')
            fact = json.loads(canonical(fact))
            for name, value in {'iter': job['iteration'], 'parent': job['request']['parent'],
                                'job_id': ref, 'fidelity': job['request']['fidelity'],
                                'request_sha256': job['request_sha256']}.items():
                if name in fact and fact[name] != value:
                    raise JobError(f'final fact conflicts with job {name}')
                fact[name] = value
            if fact.get('status') not in ('completed', 'failed', 'blocked') or type(fact.get('audited')) is not bool:
                raise JobError('final fact requires terminal status and explicit audited boolean')
            validate_document(fact, load_schema(self.paths.schemas_root, 'iteration.schema.json'), self.paths.schemas_root)
            publication=None
            if stage is not None:
                from .function_evidence import publication_paths,validate_revision
                attempt=self.root/state['attempt']
                source,destination=publication_paths(self.root,attempt,ref,stage)
                evidence=fact.get('evidence') or {}
                expected=evidence.get('manifest_sha256')
                if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):
                    raise JobError('publication requires a manifest hash in the final fact')
                manifest=validate_revision(source,expected)
                valid_status=(fact['status'] in ('failed','blocked') if manifest['kind']=='execution-diagnostic'
                              else fact['status']=='completed')
                if (not valid_status or evidence.get('revision')!=destination.name
                    or evidence.get('kind')!=manifest['kind'] or manifest['job']!=ref):
                    raise JobError('publication differs from the final fact or job')
                if manifest['kind']=='execution-diagnostic':
                    diagnostic=read_json(source/'diagnostic.json')
                    if diagnostic['status']!=fact['status']:
                        raise JobError('diagnostic status differs from final fact')
                if manifest['kind'] in ('simulation','cache-reuse'):
                    summary=read_json(source/('simulation.json' if manifest['kind']=='simulation' else 'cache.json'))
                    if any(fact.get(k)!=summary.get(k) for k in ('execution','metrics','acceptance','fidelity')):
                        raise JobError('simulation final fact differs from sealed evidence')
                if manifest['kind']=='model-audit':
                    summary=read_json(source/'audit.json')
                    if (fact.get('drc')!=summary['drc_status'] or summary['request_sha256']!=job['request_sha256']
                            or any(fact.get(k)!=summary[k] for k in ('model_intent_id','topology_hash'))):
                        raise JobError('audit final fact differs from sealed evidence')
                publication=dict(stage=source.relative_to(self.root).as_posix(),manifest_sha256=expected)
            history = self.root / state['attempt']
            history = history.parent / 'iterations.jsonl'
            with process_lock(iteration_lock_path(history, self.paths)):
                rows = read_iterations(history, self.paths)
                _check_order(fact, rows)
                prefix = history.read_bytes() if history.exists() else b''
                separator = b'' if not prefix or prefix.endswith(b'\n') else b'\n'
                payload = separator + (canonical(fact) + '\n').encode('utf-8')
                final_intent=dict(fact=fact, payload=payload.decode('utf-8'),
                    prefix_bytes=len(prefix), prefix_sha256=hashlib.sha256(prefix).hexdigest())
                if publication is not None: final_intent['publication']=publication
                job.update(state='finalizing', final_intent=final_intent)
                atomic_json(directory / 'state.json', state)
            self._publish(directory, state, key)
            return job['result']

    def _publish(self, directory, state, key):
        """Resume only our exact append; never truncate or rewrite a prior byte."""
        job = state['jobs'][key]
        intent = job['final_intent']
        fact = intent['fact']
        if 'publication' in intent:
            from .function_evidence import complete_publication
            publication=intent['publication']
            evidence=fact.get('evidence') or {}
            if (publication['manifest_sha256']!=evidence.get('manifest_sha256')
                or evidence.get('revision')!='r-'+job['ref'].rsplit('/',1)[1]):
                raise JobError('publication intent differs from final evidence')
            complete_publication(self.root,self.root/state['attempt'],job['ref'],publication,self.paths)
        history = (self.root / state['attempt']).parent / 'iterations.jsonl'
        payload = intent['payload'].encode('utf-8')
        with process_lock(iteration_lock_path(history, self.paths)):
            data = history.read_bytes() if history.exists() else b''
            prefix = data[:intent['prefix_bytes']]
            if len(prefix) != intent['prefix_bytes'] or hashlib.sha256(prefix).hexdigest() != intent['prefix_sha256']:
                raise JobError('history prefix changed; refusing recovery')
            tail = data[len(prefix):]
            if payload.startswith(tail):
                # Includes an interrupted partial JSON write or a missing final newline.
                remaining = payload[len(tail):]
                if remaining:
                    history.parent.mkdir(parents=True, exist_ok=True)
                    with history.open('ab') as handle:
                        handle.write(remaining)
                        handle.flush()
                        os.fsync(handle.fileno())
            elif not tail.startswith(payload):
                raise JobError('history tail differs from finalization intent; refusing recovery')
            rows = read_iterations(history, self.paths)
            if next((r for r in rows if r['iter'] == fact['iter']), None) != fact:
                raise JobError('published fact differs from intent')
        job['result'] = result(status=fact['status'], job=job['ref'], job_status=fact['status'],
            fidelity=job['request']['fidelity'], acceptance=fact.get('acceptance'), metrics=fact.get('metrics'),
            artifacts=fact.get('artifacts'), duration_s=fact.get('duration_s', 0), cache_hit=fact.get('cache_hit', False),
            error=fact.get('error'), next_action=None if fact['status'] == 'completed' else 'inspect job evidence before submitting a new request')
        job.update(state=fact['status'], finished_at=now())
        atomic_json(directory / 'state.json', state)

    def recover(self, ref):
        directory, key = self._directory(ref)
        # File timestamps and PID existence are insufficient proof of abandonment.
        with ExitStack() as lease:
            try:
                lease.enter_context(process_lock(directory / 'execution.lock', timeout=0))
            except TimeoutError:
                return 'live'
            with process_lock(directory / 'coordination.lock'):
                state = self._load(directory)
                job = state['jobs'][key]
                if job['state'] == 'finalizing':
                    self._publish(directory, state, key)
                    return job['state']
                if job['state'] != 'running':
                    return job['state']
                token = job['owner_token']
            JobSession(self, ref, token).fail('worker execution lease was released before finalization; recovered as failed')
            return 'failed'


class JobSession:
    def __init__(self, store, ref, token):
        self.store, self.ref, self.token = store, ref, token
        self.started = time.monotonic()
        job = store.get(ref)
        self.elapsed_before = max(0., time.time() - datetime.fromisoformat(job['started_at']).timestamp())

    def finish(self, fact, *, stage=None):
        return self.store._finalize(self.ref, self.token, fact, stage=stage)

    def progress(self, phase, details=None):
        if not isinstance(phase, str) or not phase.strip():
            raise JobError('progress phase is required')
        directory, key = self.store._directory(self.ref)
        with process_lock(directory / 'coordination.lock'):
            state = self.store._load(directory)
            job = state['jobs'][key]
            if job['state'] != 'running' or job.get('owner_token') != self.token:
                raise JobError('progress can only be written by the running owner')
            job['progress'] = json.loads(canonical(dict(at=now(), phase=phase, details=details or {})))
            atomic_json(directory / 'state.json', state)

    def fail(self, reason):
        job = self.store.get(self.ref)
        if job['state'] != 'running':
            return
        request = job['request']
        deltas = lambda values: {k: v if isinstance(v, list) and len(v) == 2 else [None, v] for k, v in values.items()}
        self.finish(iteration_line(iter_number=job['iteration'], parent=request['parent'],
            param_delta=deltas(request['param_delta']), setup_delta=deltas(request['setup_delta']),
            status='failed', audited=False, provenance='native', error=reason,
            observation=request['why'], duration_s=self.elapsed_before + time.monotonic() - self.started,
            execution_kind='interrupted', cache_hit=False))
