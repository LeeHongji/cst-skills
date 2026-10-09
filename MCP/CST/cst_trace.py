"""Low-overhead, auditable trace recording for native CST MCP tool calls."""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


_LOCK = threading.Lock()
_SEQUENCE = 0
_SECRET = re.compile(r"(api[_-]?key|token|secret|password|authorization)", re.I)


def _trace_root() -> Path:
    configured = os.environ.get("CST_TRACE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "cst_runs" / "_mcp_traces"


def _trace_id() -> str:
    configured = os.environ.get("CST_TRACE_ID")
    if configured:
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", configured).strip("-")
    return f"mcp-{os.getpid()}-{datetime.now().strftime('%Y%m%d')}"


def _next_sequence() -> int:
    global _SEQUENCE
    with _LOCK:
        _SEQUENCE += 1
        return _SEQUENCE


def _stage(tool_name: str) -> str:
    lowered = tool_name.casefold()
    if any(token in lowered for token in ("detect", "list_design", "environment")):
        return "environment"
    if any(token in lowered for token in ("connect", "launch", "open_project", "new_project", "active_project", "save_project")):
        return "session"
    if any(token in lowered for token in ("solver", "simulation")):
        return "simulation"
    if any(token in lowered for token in ("result", "touchstone", "export")):
        return "results"
    if any(token in lowered for token in ("sweep", "optimization", "study", "probe")):
        return "optimization"
    if any(token in lowered for token in ("history", "vba", "schematic", "add_", "configure_")):
        return "modeling"
    return "inspection"


def _jsonable(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "<depth-limited>"
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 4000:
            return {"sha256": hashlib.sha256(value.encode("utf-8")).hexdigest().upper(), "length": len(value)}
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): ("<redacted>" if _SECRET.search(str(key)) else _jsonable(item, depth + 1))
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item, depth + 1) for item in list(value)[:100]]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"), depth + 1)
    return repr(value)[:1000]


def _capture_history(arguments: dict[str, Any], event_id: str) -> list[str]:
    code = arguments.get("vba_code")
    if not isinstance(code, str) or not code.strip():
        return []
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest().upper()
    directory = _trace_root() / _trace_id() / "history"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{event_id}-{digest[:12]}.vba"
    path.write_text(code, encoding="utf-8")
    arguments["vba_code"] = {
        "sha256": digest,
        "length": len(code),
        "artifact": str(path),
    }
    return [str(path)]


def _append_event(payload: dict[str, Any]) -> None:
    directory = _trace_root() / _trace_id()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "trace.jsonl"
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def trace_function(function: Callable[..., Any]) -> Callable[..., Any]:
    signature = inspect.signature(function)

    def begin(args: Any, kwargs: Any) -> Any:
        started = time.perf_counter()
        event_id = f"evt-{uuid.uuid4().hex[:16]}"
        sequence = _next_sequence()
        try:
            bound = signature.bind_partial(*args, **kwargs)
            arguments = dict(bound.arguments)
        except TypeError:
            arguments = {"args": args, "kwargs": kwargs}
        evidence = _capture_history(arguments, event_id)
        redacted = _jsonable(arguments)
        base = {
            "event_id": event_id,
            "trace_id": _trace_id(),
            "sequence": sequence,
            "timestamp": datetime.now().astimezone().isoformat(),
            "stage": _stage(function.__name__),
            "actor": os.environ.get("CST_AGENT_NAME", "agent"),
            "tool": function.__name__,
            "args_redacted": redacted,
            "parameter_delta": {},
            "decision": "",
            "rationale_summary": "",
            "evidence_paths": evidence,
        }
        return started, base

    def failure(started: float, base: dict, exc: Exception) -> None:
        _append_event(
                {
                    **base,
                    "observation": f"{type(exc).__name__}: {exc}",
                    "status": "error",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
        )

    def success(started: float, base: dict, result: Any) -> None:
        _append_event(
            {
                **base,
                "observation": "Tool call completed",
                "result_summary": _jsonable(result),
                "status": "success",
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "error": None,
            }
        )
    if inspect.iscoroutinefunction(function):
        @functools.wraps(function)
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            started, base = begin(args, kwargs)
            try:
                result = await function(*args, **kwargs)
            except Exception as exc:
                failure(started, base, exc)
                raise
            success(started, base, result)
            return result
    else:
        @functools.wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started, base = begin(args, kwargs)
            try:
                result = function(*args, **kwargs)
            except Exception as exc:
                failure(started, base, exc)
                raise
            success(started, base, result)
            return result

    return wrapped


def install_fastmcp_trace(mcp: Any) -> None:
    """Wrap FastMCP's decorator so all subsequently registered tools are traced."""

    original_tool = mcp.tool

    def traced_tool(*decorator_args: Any, **decorator_kwargs: Any) -> Callable[[Callable[..., Any]], Any]:
        register = original_tool(*decorator_args, **decorator_kwargs)

        def decorator(function: Callable[..., Any]) -> Any:
            return register(trace_function(function))

        return decorator

    mcp.tool = traced_tool
