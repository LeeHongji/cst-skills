"""Task-level facade. Dispatch is separate from CST execution and from acceptance.

Offline analysis/comparison and guarded simulation dispatch are connected.
Simulation requires core native readback and CST evidence promotion;
incomplete execution produces queryable diagnostics, never a completed result.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from dataclasses import asdict

PLATFORM_ROOT=Path(__file__).resolve().parents[2]
for source in ('CST-Lab','CST-CAD'):
    sys.path.insert(0,str(PLATFORM_ROOT/'MCP'/source/'src'))

from cst_lab.contracts.iterations import iteration_line,read_iterations
from cst_lab.function_contract import RunRequest, digest
from cst_lab.function_evidence import prepare_analysis,validate_revision,sha256
from cst_lab.function_offline import analyze
from cst_lab.jobs import JobStore,JobBusy
from cst_lab.paths import LabPaths
from cst_lab.atomic import atomic_json


class FunctionService:
    def __init__(self, root=None):
        self.root=Path(root or os.environ.get('CST_AUTOMATION_ROOT') or PLATFORM_ROOT).resolve()
        self.paths=LabPaths.resolve(self.root)
        self.store=JobStore(self.root,paths=self.paths)

    def _learning_directory(self, job_ref):
        self.store._directory(job_ref)  # Validate the reference before deriving a path.
        # Hash the full ref to bind attempt + job without deeply nested Windows paths.
        return self.store.runtime.parent/'function-learning'/digest(job_ref)

    def _publish_learning(self, request, fact, job_ref):
        """Publish the finalized append-only fact into Brain as a best effort.

        Brain is a searchable projection; it must never be able to turn a
        successful CST result into a failed job.  The sidecar in the job
        directory keeps the publication outcome queryable through ``cst_get``
        even when the optional Brain environment is unavailable.
        """
        # _directory returns the shared attempt directory, not a job folder.
        # Never let successive jobs overwrite one another's learning evidence.
        directory=self._learning_directory(job_ref)
        report={"status":"skipped","reason":"disabled","job":job_ref}
        if os.environ.get("CST_FUNCTION_LEARNING", "1").casefold() in {"0", "false", "no"}:
            atomic_json(directory/'report.json',report)
            return report
        try:
            history=RunRequest.parse(request).attempt_path(self.root).parent/'iterations.jsonl'
            # JobStore._finalize enriches the submitted fact with the
            # immutable job identity, request hash and fidelity before it
            # appends the JSONL row.  Publish that exact row so Brain's
            # append-only consistency check sees the same bytes/fields as the
            # durable experiment history.
            job=self.store.get(job_ref)
            if job['state'] not in ('completed','failed','blocked') or job['request']!=RunRequest.parse(request).document:
                raise ValueError('learning requires this job\'s finalized request')
            iteration=job['iteration']
            rows=read_iterations(history,self.paths)
            published=next((row for row in rows if row.get('iter')==iteration and row.get('job_id')==job_ref),None)
            if published is None:
                raise RuntimeError(f'final iteration {iteration} is not present in {history}')
            fact=published
            fact_file=directory/'fact.json'
            request_file=directory/'request.json'
            atomic_json(fact_file,fact)
            atomic_json(request_file,request)
            brain_python=Path(sys.executable)
            if not brain_python.is_file():
                raise FileNotFoundError(f'Brain Python not found: {brain_python}')
            brain_root=Path(os.environ.get('CST_BRAIN_ROOT') or self.root/'brain').resolve()
            command=[str(brain_python),'-m','cst_brain','--brain-root',str(brain_root),
                     'publish-function-iteration','--history',str(history),'--fact-file',str(fact_file),
                     '--request-file',str(request_file),'--job-ref',job_ref,'--workspace-root',str(self.root)]
            completed=subprocess.run(command,cwd=PLATFORM_ROOT/'MCP'/'CST-Brain',
                                     env={**os.environ,'PYTHONUTF8':'1'},capture_output=True,text=True,
                                     timeout=60,check=False)
            if completed.returncode:
                raise RuntimeError(f'Brain publication exited {completed.returncode}: {completed.stderr[-1000:]}')
            payload=json.loads(completed.stdout) if completed.stdout.strip() else {}
            report={"status":"published" if payload.get("status") in ('published','unchanged') else payload.get("status","success"),
                    "reused":payload.get('status')=='unchanged',
                    "case_id":payload.get("case_id"),"manifest":payload.get("manifest"),"page":payload.get("page"),
                    "evidence_count":payload.get("evidence_count",0)}
        except Exception as exc:
            report={"status":"error","error":f'{type(exc).__name__}: {exc}'}
        report['job']=job_ref
        atomic_json(directory/'report.json',report)
        return report

    def run(self, request):
        normalized=RunRequest.parse(request)
        ref=self.store.submit(normalized)
        job=self.store.get(ref)
        if job['state'] not in ('completed','failed','blocked'):
            directory,_=self.store._directory(ref)
            # Duplicate dispatchers cannot execute a job twice: the OS execution
            # lease and final job state are rechecked before any route executes.
            with (directory/'dispatcher-stdout.log').open('ab') as out, (directory/'dispatcher-stderr.log').open('ab') as err:
                options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
                subprocess.Popen([sys.executable,str(Path(__file__).with_name('tools')/'function_worker.py'),
                    '--workspace-root',str(self.root),'--job',ref],stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                    cwd=PLATFORM_ROOT,**options)
        return self.store.response(ref)

    def get(self, ref):
        if ref.startswith('artifact://'):
            match=re.fullmatch(r'artifact://([0-9a-f]{64})/([0-9a-f]{32})/(.+)',ref)
            if not match: raise ValueError('invalid artifact reference')
            jobref=f'job://{match[1]}/{match[2]}'
            job=self.store.get(jobref)
            if ref not in (job.get('result') or {}).get('artifacts',{}).values():
                raise ValueError('artifact is not registered in this finalized job')
            fact=job['final_intent']['fact']
            attempt=RunRequest.parse(job['request']).attempt_path(self.root)
            folder=attempt.parent/'evidence-revisions'/fact['evidence']['revision']
            validate_revision(folder,fact['evidence']['manifest_sha256'])
            path=(folder/match[3]).resolve()
            if not path.is_relative_to(folder.resolve()): raise ValueError('artifact escapes revision')
            response=dict(kind='artifact',ref=ref,path=str(path),bytes=path.stat().st_size,sha256=sha256(path))
            if path.suffix=='.json': response['document']=json.loads(path.read_text(encoding='utf-8'))
            elif path.suffix in ('.md','.csv','.txt','.log') and path.stat().st_size<200_000:
                response['text']=path.read_text(encoding='utf-8')
            return response
        job=self.store.get(ref)
        public={k:v for k,v in job.items() if k not in ('owner_token','final_intent')}
        if job.get('state') in ('completed','failed','blocked'):
            try:
                history=RunRequest.parse(job['request']).attempt_path(self.root).parent/'iterations.jsonl'
                rows=read_iterations(history,self.paths)
                current=next((row for row in rows if row.get('iter')==job.get('iteration')),None)
                if current is not None:
                    view={key:current.get(key) for key in ('iter','parent','status','fidelity','provenance','audited','param_delta','setup_delta','execution_kind','cache_hit','metrics','acceptance')}
                    parent=next((row for row in rows if row.get('iter')==current.get('parent')),None) if current.get('parent') is not None else None
                    if parent is not None:
                        cur_metrics=current.get('metrics') or {}; old_metrics=parent.get('metrics') or {}
                        view['compare']={
                            'parent_iter':parent.get('iter'),
                            'parameter_delta':current.get('param_delta') or {},
                            'setup_delta':current.get('setup_delta') or {},
                            'metric_delta':{name:cur_metrics[name]-old_metrics[name] for name in set(cur_metrics)&set(old_metrics)
                                            if isinstance(cur_metrics[name],(int,float)) and isinstance(old_metrics[name],(int,float))},
                            'acceptance_change':{'from':(parent.get('acceptance') or {}).get('status'),
                                                 'to':(current.get('acceptance') or {}).get('status')},
                            'same_setup':self._same_setup(parent,current),
                            'sensitivity_eligible':self._same_setup(parent,current) and bool(current.get('param_delta')) and not bool(current.get('setup_delta')),
                            'causality_note':'Sensitivity is eligible only when parent/current setup hashes match and setup_delta is empty.'
                        }
                    public['iteration_fact']=view
            except Exception:
                # A query must remain available even if an old legacy line cannot
                # be parsed by the current contract reader.
                pass
        directory,_=self.store._directory(ref)
        learning=self._learning_directory(ref)/'report.json'
        if learning.is_file():
            try:
                report=json.loads(learning.read_text(encoding='utf-8'))
                if isinstance(report,dict) and report.get('job')==ref:
                    public['learning']=report
                else:
                    public['learning']={'status':'unverified','reason':'learning receipt job identity mismatch'}
            except (OSError,json.JSONDecodeError): pass
        elif (directory/'learning-publication.json').is_file():
            public['learning']={'status':'unverified','reason':'legacy attempt-wide learning receipt is not bound to this job'}
        return dict(kind='job',**public)

    @staticmethod
    def _same_setup(parent, current):
        previous=(parent.get('execution') or {}).get('setup_sha256')
        actual=(current.get('execution') or {}).get('setup_sha256')
        return bool(previous and actual and previous == actual)

    def work(self, ref):
        # A dispatcher can continue earlier queued jobs from the same attempt.
        # It never starts an additional physical execution of a running job.
        while self.store.get(ref)['state'] in ('queued','running','finalizing'):
            pending=self.store.pending(ref)
            if not pending: return
            first=pending[0]
            if first['state'] in ('running','finalizing'):
                self.store.recover(first['ref'])
                time.sleep(.2)
                continue
            try:
                with self.store.claim(first['ref']) as session:
                    self._execute(session)
            except JobBusy:
                time.sleep(.2)
            except Exception:
                if self.store.get(first['ref'])['state'] not in ('failed','blocked','completed'):
                    raise

    def _execute(self, session):
        start=time.monotonic()
        job=self.store.get(session.ref);request=job['request']
        if request['operation']=='simulate':
            from cst_lab.approval import ReviewAuthority
            from cst_lab.contracts.attempt import ApprovalError,TopologyMismatch,RangeViolation
            from cst_lab.function_model import prepare_simulation
            session.progress('preflight',{'checks':['approval','full-parameters','parent','drc','effective-setup']})
            prepared=None;drc_status='skipped';cached=None;runtime_probe=None
            try:
                prepared=prepare_simulation(request,self.paths,ReviewAuthority(self.paths.registry_root/'approval'))
                drc_status=prepared.drc_report['status']
                from cst_lab.function_cache import find
                from cst_function_executor import cache_runtime_probe
                runtime_probe=cache_runtime_probe()
                cached=find(RunRequest.parse(request).attempt_path(self.root),prepared,self.paths,runtime_probe)
                session.progress('ready-for-executor',{'execution':prepared.execution,'drc_status':prepared.drc_report['status']})
            except (ApprovalError,TopologyMismatch,RangeViolation,ValueError,FileNotFoundError) as exc:
                reason=f'Preflight refused: {exc}'
                report=getattr(exc,'report',None)
                if report: drc_status=report['status'] if report['status'] in ('pass','warn','fail','error') else 'error'
                session.progress('preflight-refused',{'reason':reason,'drc_report':report})
                prepared=None
            if prepared is not None:
                from cst_function_executor import execute
                if cached is not None:
                    from cst_lab.function_cache import prepare
                    from cst_lab.function_contract import digest
                    def authorize_cache():
                        current=prepare_simulation(request,self.paths,ReviewAuthority(self.paths.registry_root/'approval'))
                        if asdict(current)!=asdict(prepared) or cache_runtime_probe()!=runtime_probe:
                            raise ValueError('cache request/runtime changed before publication')
                    stage=self.paths.runs_root/'_function'/('cache-'+digest(session.ref)[:32])
                    outcome=prepare(request,prepared,cached,stage,self.paths,session.ref,authorize_cache,session.progress)
                else:
                    outcome=execute(session,prepared)
                stage=outcome['stage'];manifest_hash=outcome['manifest_sha256']
                manifest=validate_revision(stage,manifest_hash)
                base='artifact://'+session.ref[6:]+'/'
                artifacts={r['path']:base+r['path'] for r in manifest['files']}
                artifacts['manifest.json']=base+'manifest.json'
                receipt=outcome['receipt']
                result_fields={k:outcome[k] for k in ('metrics','acceptance','solver') if k in outcome}
                if outcome.get('error') is not None:result_fields['error']=outcome['error']
                fact=iteration_line(iter_number=job['iteration'],parent=request['parent'],
                    status=outcome['status'],audited=outcome.get('audited',False),provenance='native',
                    duration_s=time.monotonic()-start,drc=drc_status,
                    param_delta=prepared.param_delta,setup_delta=prepared.setup_delta,
                    execution=prepared.execution,
                    execution_kind='cache' if outcome.get('cache_hit') else 'solver' if receipt.get('solver_started') is True else 'interrupted',
                    cache_hit=outcome.get('cache_hit',False),observation=request['why'],artifacts=artifacts,
                    evidence=dict(kind=manifest['kind'],revision='r-'+session.ref.rsplit('/',1)[1],
                                  manifest_sha256=manifest_hash),**result_fields)
                session.finish(fact,stage=stage)
                self._publish_learning(request,fact,session.ref)
                return
            extra={}
            fact=iteration_line(iter_number=job['iteration'],parent=request['parent'],
                status='blocked',audited=False,provenance='native',duration_s=time.monotonic()-start,
                drc=drc_status,
                param_delta=prepared.param_delta if prepared else {},setup_delta=prepared.setup_delta if prepared else {},
                execution_kind='offline',cache_hit=False,observation=request['why'],
                error=reason+'; no CST launch attempted',**extra)
            session.finish(fact)
            self._publish_learning(request,fact,session.ref)
            return
        if request['operation']=='audit':
            from cst_lab.function_audit import prepare,seal
            from cst_lab.function_contract import digest
            attempt=RunRequest.parse(request).attempt_path(self.root)
            stage=self.paths.runs_root/'_function'/('audit-'+digest(session.ref)[:32])
            receipt=prepare(request,attempt,stage,self.paths,session.progress)
            manifest_hash=seal(stage,session.ref)
            manifest=validate_revision(stage,manifest_hash)
            base='artifact://'+session.ref[6:]+'/'
            artifacts={row['path']:base+row['path'] for row in manifest['files']}
            artifacts['manifest.json']=base+'manifest.json'
            session.progress('promoting-audit',{'readiness':receipt['readiness']})
            fact=iteration_line(iter_number=job['iteration'],parent=None,status='completed',
                audited=False,provenance='native',duration_s=time.monotonic()-start,
                execution_kind='offline',cache_hit=False,observation=request['why'],
                drc=receipt['drc_status'],topology_hash=receipt['topology_hash'],model_intent_id=receipt['model_intent_id'],
                acceptance=dict(status='not_evaluated',gates=[]),artifacts=artifacts,
                evidence=dict(kind='model-audit',revision='r-'+session.ref.rsplit('/',1)[1],manifest_sha256=manifest_hash))
            session.finish(fact,stage=stage)
            self._publish_learning(request,fact,session.ref)
            return
        attempt=RunRequest.parse(request).attempt_path(self.root)
        session.progress('snapshot',{'operation':request['operation']})
        stage=self.paths.runs_root/'_function'/session.ref[6:]/'analysis'
        analysis,metrics,acceptance=analyze(request,attempt,stage,self.paths,session.progress)
        session.progress('promoting',{'kind':'offline-analysis'})
        manifest_hash=prepare_analysis(stage,session.ref)
        manifest=validate_revision(stage,manifest_hash)
        revision='r-'+session.ref.rsplit('/',1)[1]
        base='artifact://'+session.ref[6:]+'/'
        artifacts={r['path']:base+r['path'] for r in manifest['files']}
        artifacts['manifest.json']=base+'manifest.json'
        fact=iteration_line(iter_number=job['iteration'],parent=request['parent'],
            status='completed',audited=False,provenance='native',duration_s=time.monotonic()-start,
            execution_kind='offline',cache_hit=False,observation=request['why'],metrics=metrics,
            acceptance=acceptance,artifacts=artifacts,evidence=dict(kind='offline-analysis',
                revision=revision,manifest_sha256=manifest_hash))
        session.finish(fact,stage=stage)
        self._publish_learning(request,fact,session.ref)


def cst_run(request):
    return FunctionService().run(request)


def cst_get(ref):
    return FunctionService().get(ref)
