from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from cst_automation import DEFAULT_CST_ROOT, _cst_root


PROJECT_ROOT = Path(__file__).resolve().parent
VENDORED_RUNTIME_SCRIPT_ROOT = (
    PROJECT_ROOT
    / "vendor"
    / "cst-runtime-cli"
    / "skills"
    / "cst-runtime-cli"
    / "scripts"
)


def _resolve_runtime_script_root() -> Path:
    """Resolve runtime CLI scripts from an override, vendor tree, or installed package."""
    override = os.environ.get("CST_RUNTIME_SCRIPT_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if VENDORED_RUNTIME_SCRIPT_ROOT.exists():
        return VENDORED_RUNTIME_SCRIPT_ROOT

    spec = importlib.util.find_spec("cst_runtime")
    if spec and spec.submodule_search_locations:
        package_dir = Path(next(iter(spec.submodule_search_locations))).resolve()
        return package_dir.parent
    if spec and spec.origin:
        return Path(spec.origin).resolve().parent.parent
    return VENDORED_RUNTIME_SCRIPT_ROOT


RUNTIME_SCRIPT_ROOT = _resolve_runtime_script_root()
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("CST_RUNTIME_CLI_TIMEOUT", "120"))


class CSTRuntimeCLIError(RuntimeError):
    """Raised when cst-runtime-cli cannot be executed."""


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return repr(value)


def _parse_json_stdout(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        value, _ = decoder.raw_decode(text)
        return value


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    runtime_path = str(RUNTIME_SCRIPT_ROOT)
    cst_root = _cst_root()
    cst_python_lib = cst_root / "AMD64" / "python_cst_libraries"
    cst_amd64 = cst_root / "AMD64"

    python_path_parts = [runtime_path]
    if cst_python_lib.exists():
        python_path_parts.append(str(cst_python_lib))
    if env.get("PYTHONPATH"):
        python_path_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    if cst_amd64.exists():
        env["PATH"] = str(cst_amd64) + os.pathsep + env.get("PATH", "")
    env.setdefault("CST_INSTALL_ROOT", str(cst_root if cst_root.exists() else DEFAULT_CST_ROOT))
    return env


def detect_runtime() -> dict[str, Any]:
    source = "override" if os.environ.get("CST_RUNTIME_SCRIPT_ROOT") else (
        "vendored" if RUNTIME_SCRIPT_ROOT == VENDORED_RUNTIME_SCRIPT_ROOT else "installed-package"
    )
    return {
        "ok": RUNTIME_SCRIPT_ROOT.exists(),
        "source": source,
        "runtime_script_root": str(RUNTIME_SCRIPT_ROOT),
        "runtime_script_root_exists": RUNTIME_SCRIPT_ROOT.exists(),
        "python_executable": sys.executable,
        "cst_install_root": str(_cst_root()),
    }


def run_runtime_cli(
    arguments: list[str],
    *,
    workspace: str | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    if not RUNTIME_SCRIPT_ROOT.exists():
        raise CSTRuntimeCLIError(f"cst-runtime-cli scripts not found: {RUNTIME_SCRIPT_ROOT}")

    command = [sys.executable, "-m", "cst_runtime", *arguments]
    cwd = str(Path(workspace).expanduser().resolve()) if workspace else str(PROJECT_ROOT)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=runtime_env(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout_seconds or DEFAULT_TIMEOUT_SECONDS,
    )

    parsed: Any = None
    parse_error: str | None = None
    if completed.stdout.strip():
        try:
            parsed = _parse_json_stdout(completed.stdout)
        except Exception as exc:
            parse_error = str(exc)

    result: dict[str, Any] = {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "command": command,
        "cwd": cwd,
        "json": parsed,
    }
    if parse_error:
        result["json_parse_error"] = parse_error
    if completed.stderr.strip():
        result["stderr"] = completed.stderr
    if parsed is None and completed.stdout.strip():
        result["stdout"] = completed.stdout
    return result


def list_runtime_tools(timeout_seconds: float | None = None) -> dict[str, Any]:
    return run_runtime_cli(["list-tools"], timeout_seconds=timeout_seconds)


def list_runtime_pipelines(timeout_seconds: float | None = None) -> dict[str, Any]:
    return run_runtime_cli(["list-pipelines"], timeout_seconds=timeout_seconds)


def runtime_usage_guide(timeout_seconds: float | None = None) -> dict[str, Any]:
    return run_runtime_cli(["usage-guide"], timeout_seconds=timeout_seconds)


def describe_runtime_tool(tool_name: str, timeout_seconds: float | None = None) -> dict[str, Any]:
    if not tool_name.strip():
        raise ValueError("tool_name must not be empty")
    return run_runtime_cli(["describe-tool", "--tool", tool_name.strip()], timeout_seconds=timeout_seconds)


def runtime_args_template(tool_name: str, timeout_seconds: float | None = None) -> dict[str, Any]:
    if not tool_name.strip():
        raise ValueError("tool_name must not be empty")
    return run_runtime_cli(["args-template", "--tool", tool_name.strip()], timeout_seconds=timeout_seconds)


def invoke_runtime_tool(
    tool_name: str,
    args: dict[str, Any] | None = None,
    *,
    workspace: str | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    if not tool_name.strip():
        raise ValueError("tool_name must not be empty")
    payload = json.dumps(args or {}, ensure_ascii=False, default=_json_default)
    command_args = ["invoke", "--tool", tool_name.strip(), "--args-json", payload]
    if workspace:
        command_args.extend(["--workspace", workspace])
    return run_runtime_cli(command_args, workspace=workspace, timeout_seconds=timeout_seconds)
