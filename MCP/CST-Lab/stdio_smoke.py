#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent
EXPECTED_TOOLS = 23


def jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


async def smoke() -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    environment.setdefault("CST_AUTOMATION_ROOT", str(ROOT.parents[1]))
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "mcp_server.py")],
        cwd=str(ROOT),
        env=environment,
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            return {
                "ok": len(listed.tools) == EXPECTED_TOOLS,
                "server": jsonable(initialized.serverInfo),
                "tool_count": len(listed.tools),
                "tools": [tool.name for tool in listed.tools],
            }


if __name__ == "__main__":
    result = asyncio.run(smoke())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(f"Expected {EXPECTED_TOOLS} CST Lab tools, found {result['tool_count']}")
