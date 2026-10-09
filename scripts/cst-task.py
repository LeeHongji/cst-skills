"""CLI client of the same three-tool MCP used by Agents (no native CST calls)."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'MCP/CST'))
sys.path.insert(0, str(ROOT/'MCP/CST-Lab/src'))
from cst_lab.workspace import default_workspace
from cst_lab.paths import LabPaths
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(args):
    workspace = Path(args.workspace).resolve() if args.workspace else default_workspace(ROOT)
    paths = LabPaths.resolve(workspace)
    server = StdioServerParameters(command=sys.executable,
        args=[str(ROOT/'MCP/CST/agent_mcp_server.py')], cwd=str(ROOT/'MCP/CST'),
        env={**os.environ, 'CST_AUTOMATION_ROOT':str(workspace), 'CST_BRAIN_ROOT':str(workspace/'brain'), 'CST_TRACE_ROOT':str(paths.runs_root/'_mcp_traces'), 'PYTHONUTF8':'1'})
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            async def call(name, payload):
                result = await session.call_tool(name, payload)
                if result.isError: raise RuntimeError(str(result.content))
                return result.structuredContent
            if args.request:
                request = json.loads(args.request.read_text(encoding='utf-8-sig'))
                result = await call('cst_run', {'request':request})
            else:
                result = await call('cst_get', {'ref':args.get})
            if args.wait and args.request:
                ref = result['job']; deadline = time.monotonic()+args.timeout
                while True:
                    result = await call('cst_get', {'ref':ref})
                    if result['state'] in ('completed','failed','blocked'): break
                    if time.monotonic() > deadline:
                        raise TimeoutError(f'Observation timed out; query {ref}. This does not cancel the task.')
                    await asyncio.sleep(2)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result.get('state') in ('failed','blocked'): return 2
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--request', type=Path)
    group.add_argument('--get')
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--wait', action='store_true')
    parser.add_argument('--timeout', type=float, default=2200)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
