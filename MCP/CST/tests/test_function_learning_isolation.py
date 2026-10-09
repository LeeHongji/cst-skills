"""Regression coverage for cross-job learning receipt attribution."""
import json
from types import SimpleNamespace

from test_function_facade import workspace, FunctionService, RunRequest
from cst_lab.atomic import atomic_json


def complete(service, request):
    ref=service.store.submit(RunRequest.parse(request))
    service.work(ref)
    assert service.get(ref)['state']=='completed'
    return ref


def test_automatic_publication_keeps_two_jobs_and_final_facts_separate(workspace,monkeypatch):
    root,request=workspace
    service=FunctionService(root)
    publications=[]
    def publish(command,**kwargs):
        fact_path=command[command.index('--fact-file')+1]
        with open(fact_path,encoding='utf-8') as handle:fact=json.load(handle)
        ref=command[command.index('--job-ref')+1]
        assert fact['job_id']==ref
        publications.append((fact_path,fact))
        return SimpleNamespace(returncode=0,stdout=json.dumps({'status':'published','case_id':f'iteration-{fact["iter"]}'}))
    monkeypatch.setattr('cst_agent_api.subprocess.run',publish)
    a=complete(service,request)
    before=service.get(a)['learning']
    b=complete(service,dict(request,request_id='second-learning-job'))
    assert len(publications)==2
    assert publications[0][0]!=publications[1][0]
    assert service.get(a)['learning']==before
    assert service.get(a)['learning']['job']==a
    assert service.get(b)['learning']['job']==b
    assert service.get(a)['learning']['case_id']!=service.get(b)['learning']['case_id']


def test_disabled_job_cannot_overwrite_previous_publication(workspace,monkeypatch):
    root,request=workspace;service=FunctionService(root)
    monkeypatch.setenv('CST_FUNCTION_LEARNING','0')
    a=complete(service,request)
    atomic_json(service._learning_directory(a)/'report.json',{'status':'published','job':a,'case_id':'prior'})
    b=complete(service,dict(request,request_id='disabled-second'))
    assert service.get(a)['learning']['case_id']=='prior'
    assert service.get(b)['learning']=={'status':'skipped','reason':'disabled','job':b}


def test_legacy_receipt_never_claims_publication_for_failed_or_queued_job(workspace):
    root,request=workspace;service=FunctionService(root)
    ref=service.store.submit(RunRequest.parse(dict(request,inputs=['cst_runs/nonexistent.s2p'])))
    directory,_=service.store._directory(ref)
    atomic_json(directory/'learning-publication.json',{'status':'published','case_id':'different-job'})
    assert service.get(ref)['learning']['status']=='unverified'
    service.work(ref)
    assert service.get(ref)['state']=='failed'
    assert service.get(ref)['learning']['status']=='unverified'


def test_wrong_bound_receipt_is_not_reported_as_success(workspace,monkeypatch):
    root,request=workspace;service=FunctionService(root)
    monkeypatch.setenv('CST_FUNCTION_LEARNING','0')
    ref=complete(service,request)
    atomic_json(service._learning_directory(ref)/'report.json',{'status':'published','job':'job://other'})
    assert service.get(ref)['learning']['status']=='unverified'
