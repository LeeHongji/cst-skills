import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import time

import pytest
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'MCP/CST'),str(ROOT/'MCP/CST-Lab/src')]
from cst_agent_api import FunctionService
from cst_lab.contracts.attempt import write_attempt
from cst_lab.contracts.design import write_design
from cst_lab.contracts.iterations import read_iterations
from cst_lab.function_contract import RunRequest
from cst_lab.function_evidence import validate_revision
from cst_lab.paths import LabPaths


@pytest.fixture
def workspace(tmp_path):
    shutil.copytree(ROOT/'brain/schemas',tmp_path/'brain/schemas')
    paths=LabPaths.resolve(tmp_path)
    request=dict(topic='t',design='d',attempt='a',request_id='analyze-1',why='Synthetic exported curve acceptance',
                 operation='analyze',fidelity='offline',inputs=['cst_runs/source.s2p'])
    attempt=RunRequest.parse(request).attempt_path(tmp_path)
    write_attempt(attempt,dict(schema_version=1,topic_id='t',design_id='d',attempt_id='a',
        topology_hash='0'*64,baseline_parameters={},approved_ranges={},max_iterations=20),paths)
    header=dict(schema_version=1,topic_id='t',design_id='d',title='Offline test',model='model.py',ports=2,
        acceptance=[dict(id='return_loss',metric='s1_1_db',band_ghz=[1,1.4],comparator='<',threshold=-15,mode='pointwise')])
    write_design(attempt.parents[2]/'design.md',header,'Synthetic source data, not a validated physical model.',paths)
    # A source-only attempt intentionally has no model.py, IR, audit or approval.
    source=tmp_path/'cst_runs/source.s2p';source.parent.mkdir(parents=True,exist_ok=True)
    source.write_text('# GHz S RI R 50\n'+'\n'.join(f'{1+i*.1} .1 0 .9 0 .9 0 .1 0' for i in range(5))+'\n')
    return tmp_path,request


def wait(service,ref):
    end=time.monotonic()+30
    while True:
        job=service.get(ref)
        if job['state'] in ('completed','failed','blocked'): return job
        assert time.monotonic()<end,job
        time.sleep(.05)


def test_actual_background_analysis_without_any_model_or_approval(workspace):
    root,request=workspace;service=FunctionService(root)
    started=time.monotonic();response=service.run(request)
    assert time.monotonic()-started<5
    job=wait(service,response['job'])
    assert job['state']=='completed',job
    assert job['result']['acceptance']['status']=='pass'
    assert job['result']['metrics']['return_loss']==pytest.approx(-20)
    assert job['result']['cache_hit'] is False
    again=service.run(request)
    assert again==job['result']
    attempt=RunRequest.parse(request).attempt_path(root)
    rows=read_iterations(attempt.parent/'iterations.jsonl',LabPaths.resolve(root))
    assert len(rows)==1 and rows[0]['audited'] is False and rows[0]['drc']=='skipped'
    assert not (attempt.parents[2]/'model.py').exists()
    manifest=service.get(job['result']['artifacts']['manifest.json'])
    assert manifest['document']['kind']=='offline-analysis'
    for ref in job['result']['artifacts'].values():
        artifact=service.get(ref)
        assert Path(artifact['path']).is_file()
    assert 'owner_token' not in job and 'final_intent' not in job


def test_comparison_re_evaluates_changed_gates_and_binds_snapshots(workspace):
    root,request=workspace;service=FunctionService(root)
    other=root/'cst_runs/other.s2p';other.write_text((root/'cst_runs/source.s2p').read_text().replace('.1 0','.2 0'))
    request.update(operation='compare',inputs=[request['inputs'][0],'cst_runs/other.s2p'])
    job=wait(service,service.run(request)['job'])
    assert job['state']=='completed',job
    assert job['result']['acceptance']['status']=='fail'
    analysis=service.get(job['result']['artifacts']['analysis.json'])['document']
    assert analysis['comparison'][0]['metric_delta']['return_loss']==pytest.approx(6.020599913)
    design=RunRequest.parse(request).attempt_path(root).parents[2]/'design.md'
    design.write_text(design.read_text().replace('-15','-10'))
    request['request_id']='compare-new-gates'
    second=wait(service,service.run(request)['job'])
    assert second['result']['acceptance']['status']=='pass'
    second_analysis=service.get(second['result']['artifacts']['analysis.json'])['document']
    assert second_analysis['gates_sha256']!=analysis['gates_sha256']
    assert service.get(job['result']['artifacts']['analysis.json'])['document']==analysis


def test_artifact_tampering_and_unknown_references_are_refused(workspace):
    root,request=workspace;service=FunctionService(root)
    job=wait(service,service.run(request)['job'])
    ref=job['result']['artifacts']['analysis.json']
    path=Path(service.get(ref)['path']);path.write_text('{}')
    with pytest.raises(ValueError,match='missing or changed'): service.get(ref)
    with pytest.raises(ValueError): service.get(ref+'/../attempt.json')


def test_unsupported_solver_route_and_bad_source_never_claim_completion(workspace):
    root,request=workspace;service=FunctionService(root)
    request.update(operation='simulate',fidelity='screen',inputs=[])
    job=wait(service,service.run(request)['job'])
    assert job['state']=='blocked'
    assert 'no CST launch' in job['result']['error']
    request.update(request_id='missing',operation='analyze',fidelity='offline',inputs=['cst_runs/missing.s2p'])
    failed=wait(service,service.run(request)['job'])
    assert failed['state']=='failed' and failed['result']['acceptance']['status']=='not_evaluated'


def test_dispatcher_continues_queue_after_failed_earlier_job(workspace):
    root,request=workspace;service=FunctionService(root)
    first=service.store.submit(RunRequest.parse(dict(request,request_id='bad-first',inputs=['cst_runs/absent.s2p'])))
    last=service.run(request)['job']
    assert wait(service,last)['state']=='completed'
    assert service.get(first)['state']=='failed'
    attempt=RunRequest.parse(request).attempt_path(root)
    rows=read_iterations(attempt.parent/'iterations.jsonl',LabPaths.resolve(root))
    assert [r['status'] for r in rows]==['failed','completed']


def test_invalid_phase_anchor_is_acceptance_error_with_reviewable_evidence(workspace):
    root,request=workspace;service=FunctionService(root)
    design=RunRequest.parse(request).attempt_path(root).parents[2]/'design.md'
    header=dict(schema_version=1,topic_id='t',design_id='d',title='Missing anchor coverage',model='model.py',ports=2,
        acceptance=[dict(id='phase',metric='phase_deviation_deg',main=[2,1],reference=[1,2],target=90,
        anchor_ghz=3,band_ghz=[1,1.4],comparator='<=',threshold=2,mode='pointwise')])
    write_design(design,header,'Synthetic error case',LabPaths.resolve(root))
    job=wait(service,service.run(request)['job'])
    assert job['state']=='completed',job
    assert job['result']['acceptance']['status']=='error'
    assert 'response-00.png' in job['result']['artifacts']
    analysis=service.get(job['result']['artifacts']['analysis.json'])['document']
    assert analysis['inputs'][0]['acceptance']['gates'][0]['reason']


def test_real_stdio_discovers_exactly_three_and_runs_offline(workspace):
    root,request=workspace
    async def run():
        parameters=StdioServerParameters(command=sys.executable,args=[str(ROOT/'MCP/CST/agent_mcp_server.py')],
            cwd=str(ROOT/'MCP/CST'),env={**os.environ,'CST_AUTOMATION_ROOT':str(root),'CST_TRACE_ROOT':str(root/'cst_runs/_mcp_traces'),'PYTHONUTF8':'1'})
        async with stdio_client(parameters) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                listed=await session.list_tools()
                assert {t.name for t in listed.tools}=={'cst_run','cst_get','cst_approve'}
                approval=next(t for t in listed.tools if t.name=='cst_approve')
                assert set(approval.inputSchema['properties'])=={'attempt','ranges'}
                submitted=await session.call_tool('cst_run',{'request':request})
                assert submitted.isError is not True,submitted
                response=submitted.structuredContent
                assert response and response['job'].startswith('job://')
                end=time.monotonic()+30
                while True:
                    got=await session.call_tool('cst_get',{'ref':response['job']})
                    assert got.isError is not True,got
                    job=got.structuredContent
                    if job['state'] in ('completed','failed','blocked'): break
                    assert time.monotonic()<end
                    await asyncio.sleep(.05)
                assert job['state']=='completed',job
                rejected=await session.call_tool('cst_run',{'request':dict(request,reviewer='agent')})
                assert rejected.isError is True
        assert list((root/'cst_runs/_mcp_traces').rglob('*.jsonl'))
    asyncio.run(run())
