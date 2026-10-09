"""Bounded three-tool lowpass verification, with genuine interactive approval.

Prepare is offline. Approve forwards an actual terminal user's response via
MCP elicitation. Verify requires an existing valid approval; it cannot enroll
standing authorization or create a signature. Agent callers must never type
the review response on behalf of a human.
"""
import argparse
import asyncio
import json
import os
import re
from pathlib import Path
import sys
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import ElicitResult

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'MCP/CST-Lab/src'),str(ROOT/'MCP/CST-CAD/src')]
from cst_lab.atomic import atomic_json
from cst_lab.approval import ReviewAuthority, verify_approval
from cst_lab.paths import LabPaths
from cst_lab.workspace import settings


async def run(args):
    root=args.workspace.resolve()
    if not settings(root) or settings(root)['software']!=ROOT:raise ValueError('Use the workspace-bound runtime')
    os.environ['CST_AUTOMATION_ROOT']=str(root)
    attempt=root/f'projects/{args.topic}/designs/lowpass/attempts/a01/attempt.json'
    output=root/'runtime/verification'/args.session
    output.mkdir(parents=True,exist_ok=True)
    async def elicit(context,params):
        if args.mode!='approve':return ElicitResult(action='decline')
        print(params.message,flush=True)
        response=await asyncio.to_thread(input,'Human reviewer: type REVIEWED after opening this audit and approving these ranges, or press Enter to decline: ')
        accepted=response=='REVIEWED'
        atomic_json(output/'human-elicitation.json',dict(message=params.message,response=response,accepted=accepted,
                    channel='interactive-terminal',claim='Actual interactive operator response; not Agent-supplied review data'))
        return ElicitResult(action='accept',content={'reviewed':True}) if accepted else ElicitResult(action='decline')
    server=StdioServerParameters(command=sys.executable,args=[str(ROOT/'MCP/CST/agent_mcp_server.py')],cwd=str(ROOT),
        env={**os.environ,'CST_AUTOMATION_ROOT':str(root),'CST_BRAIN_ROOT':str(root/'brain'),
             'CST_TRACE_ROOT':str(root/'runtime/_mcp_traces'),'PYTHONUTF8':'1'})
    transcript=[]
    async with stdio_client(server) as (reader,writer):
      async with ClientSession(reader,writer,elicitation_callback=elicit) as session:
        await session.initialize()
        async def call(name,payload):
            result=await session.call_tool(name,payload)
            transcript.append(dict(tool=name,args=payload,result=result.model_dump(mode='json')))
            atomic_json(output/(args.mode+'-transcript.json'),transcript)
            if result.isError:raise RuntimeError(str(result.content))
            return result.structuredContent
        async def task(request):
            submitted=await call('cst_run',{'request':request});ref=submitted['job']
            repeated=await call('cst_run',{'request':request})
            if repeated['job']!=ref:raise ValueError('Idempotency failed')
            deadline=time.monotonic()+1800
            while True:
                job=await call('cst_get',{'ref':ref})
                if job['state'] in ['completed','failed','blocked']:break
                if time.monotonic()>deadline:raise TimeoutError('Observation timeout; query this existing job before recovery: '+ref)
                await asyncio.sleep(3)
            print(json.dumps(dict(job=ref,state=job['state'],acceptance=(job.get('result') or {}).get('acceptance')),ensure_ascii=False),flush=True)
            return job
        def request(label,operation='simulate',fidelity='screen',delta=None,inputs=None):
            return dict(topic=args.topic,design='lowpass',attempt='a01',request_id=args.session+'-'+label,
                        operation=operation,fidelity=fidelity,why='Independent distribution acceptance: '+label,
                        param_delta=delta or {},inputs=inputs or [])
        if args.mode=='prepare':
            audit=await task(request('audit','audit','offline'))
            if audit['state']!='completed':raise ValueError('Audit failed')
            blocked=await task(request('unapproved'))
            if blocked['state']!='blocked':raise ValueError('Unapproved solve did not block')
            atomic_json(output/'prepare.json',dict(audit=audit,unapproved=blocked,proposed_ranges={'l3':[13.,15.]}))
            return
        if args.mode=='approve':
            result=await call('cst_approve',{'attempt':attempt.relative_to(root).as_posix(),'ranges':{'l3':[13.,15.]}})
            atomic_json(output/'approval.json',result)
            if not result.get('approved'):raise ValueError('Human approval was not granted')
            return
        verify_approval(attempt,authority=ReviewAuthority(LabPaths.resolve(root).registry_root/'approval'))
        jobs=[]
        for label,fidelity,delta in [('baseline','screen',{}),('variation','screen',{'l3':14.5}),('confirmation','confirm',{'l3':14.5}),('cache','screen',{'l3':14.5})]:
            job=await task(request(label,fidelity=fidelity,delta=delta));jobs.append(job)
            atomic_json(output/(label+'.json'),job)
            if job['state']!='completed' or job['result']['acceptance']['status']!='pass':raise ValueError('Numerical/run acceptance failed: '+label)
            if label=='cache' and not job['result'].get('cache_hit'):raise ValueError('Exact screen cache did not hit')
            if label!='cache' and job['result'].get('cache_hit'):raise ValueError('Fresh native execution unexpectedly reused a cache')
            for name,reference in job['result'].get('artifacts',{}).items():
                if name in ['simulation.json','reopen-receipt.json','manifest.json']:
                    await call('cst_get',{'ref':reference})
            if job.get('learning',{}).get('status')!='published':raise ValueError('Learning publication incomplete')
        refused=await task(request('out-of-range',delta={'l3':15.25}))
        if refused['state']!='blocked':raise ValueError('Out-of-range candidate did not block')
        sources=[]
        for job in jobs[:2]:
            candidates=[ref for name,ref in job['result']['artifacts'].items() if name.lower().endswith('.s2p')]
            if not candidates:raise ValueError('Touchstone evidence missing')
            evidence=await call('cst_get',{'ref':candidates[0]})
            sources.append(Path(evidence['path']).resolve().relative_to(root).as_posix())
        compared=await task(request('comparison','compare','offline',inputs=sources))
        if compared['state']!='completed':raise ValueError('Offline comparison failed')
        atomic_json(output/'verification.json',dict(status='pass',jobs=[j['ref'] for j in jobs],
            comparisons=[compared['ref']],range_refusal=refused['ref'],claim='New workspace three-tool case acceptance; no general solver coverage claim'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--topic',default='distribution-validation');p.add_argument('--session',default='distribution-v1')
    p.add_argument('--mode',choices=['prepare','approve','verify'],required=True)
    args=p.parse_args()
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',args.topic):p.error('Topic must be a lowercase kebab-case ID')
    if not args.session or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.session):p.error('Session must be a safe ID')
    asyncio.run(run(args))
