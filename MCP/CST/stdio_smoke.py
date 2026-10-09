#!/usr/bin/env python3
"""Exercise the CST MCP over its real stdio transport without changing CST state."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent
EXPECTED_TOOLS = 53


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


async def smoke() -> dict[str, Any]:
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "mcp_server.py")],
        cwd=str(ROOT),
        env={"PYTHONUTF8": "1", **os.environ},
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            result: dict[str, Any] = {
                "ok": len(listed.tools) == EXPECTED_TOOLS,
                "server": _jsonable(initialized.serverInfo),
                "tool_count": len(listed.tools),
                "tools": [tool.name for tool in listed.tools],
            }
            return result


def main() -> None:
    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    result = asyncio.run(smoke())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(
            f"Expected {EXPECTED_TOOLS} CST MCP tools, found {result['tool_count']}"
        )


if __name__ == "__main__":
    main()
