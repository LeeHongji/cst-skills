"""Real stdio MCP initialization/list/query checks; does not run a solver."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]


async def check(workspace):
    output=[]
    for name,entry in [('function','MCP/CST/agent_mcp_server.py'),('brain','MCP/CST-Brain/mcp_server.py')]:
        server=StdioServerParameters(command=sys.executable,args=[str(ROOT/entry)],cwd=str(ROOT),
            env={**os.environ,'CST_AUTOMATION_ROOT':str(workspace),'CST_BRAIN_ROOT':str(workspace/'brain'),
                 'CST_TRACE_ROOT':str(workspace/'runtime/_mcp_traces'),'PYTHONUTF8':'1'})
        async with stdio_client(server) as (reader,writer):
            async with ClientSession(reader,writer) as session:
                initialization=await session.initialize();listed=await session.list_tools()
                names=sorted(t.name for t in listed.tools)
                if name=='function' and names!=['cst_approve','cst_get','cst_run']:raise ValueError('Unexpected execution tool surface')
                if name=='brain':
                    result=await session.call_tool('brain_search_tool',{'query':'CST evidence approval 证据 审批'})
                    if result.isError:raise ValueError('Brain search failed')
                output.append(dict(service=name,tools=names,protocol=initialization.protocolVersion,status='pass'))
    return dict(status='pass',checks=output,scope='stdio protocol, not a real Agent-client acceptance')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True)
    args=p.parse_args();print(json.dumps(asyncio.run(check(args.workspace.resolve())),ensure_ascii=False,indent=2))
