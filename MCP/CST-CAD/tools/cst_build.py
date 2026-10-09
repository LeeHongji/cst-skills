"""Inject generated CST-CAD history blocks into a CST project, one at a time.

Each block is submitted through ``add_to_history`` and the CST message log is
read immediately afterwards, so a failure is attributed to the block that
caused it instead of surfacing at the end of the build. Nothing is treated as
successful because the RPC returned: the run log records every CST message.

Usage:
  cst_build.py --vba-dir <dir> --project <path.cst> [--from N] [--stop-on-warning]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("CST_INSTALL_ROOT", r"C:\CST")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "CST"))

from cst_automation import CSTSessionManager  # noqa: E402

#: Message texts that CST emits routinely and that do not indicate a problem.
BENIGN = (
    "MakeSureParameterExists",
    "CST-CAD net ",
)


def classify(message: dict[str, Any]) -> str:
    kind = str(message.get("type", "")).upper()
    text = str(message.get("text", ""))
    if kind == "ERROR":
        return "error"
    if kind == "WARNING":
        return "warning" if not any(token in text for token in BENIGN) else "info"
    return "info"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vba-dir", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--stop-on-warning", action="store_true")
    parser.add_argument("--reuse", action="store_true", help="attach to an already open project instead of creating one")
    args = parser.parse_args()

    vba_dir = Path(args.vba_dir)
    project_path = Path(args.project).resolve()
    blocks = sorted(path for path in vba_dir.glob("*.vba") if path.name != "bundle.vba")
    blocks = [path for path in blocks if int(path.name[:2]) >= args.start]

    manager = CSTSessionManager()
    session: dict[str, Any] = {"project": str(project_path), "blocks": [], "vba_dir": str(vba_dir)}

    manager.connect()
    session["connected_pid"] = manager.get_project_info().get("design_environment_pid")

    if args.reuse:
        manager.open_project(str(project_path))
    else:
        if project_path.exists():
            raise FileExistsError(f"refusing to overwrite an existing project: {project_path}")
        project_path.parent.mkdir(parents=True, exist_ok=True)
        manager.new_project("mws")
        manager.save_project(str(project_path))
    session["project_after_create"] = manager.get_project_info().get("active_project")

    project = manager._require_project()
    seen = len(project.get_messages() or [])

    status = "ok"
    for path in blocks:
        title = path.stem
        code = path.read_text(encoding="utf-8")
        record: dict[str, Any] = {"block": title, "path": str(path), "vba_bytes": len(code)}
        try:
            manager.add_to_history(title, code)
            record["rpc"] = "accepted"
        except Exception as exc:
            record["rpc"] = "raised"
            record["exception"] = f"{type(exc).__name__}: {exc}"

        messages = project.get_messages() or []
        fresh = messages[seen:]
        seen = len(messages)
        record["messages"] = [{"type": message.get("type"), "text": message.get("text")} for message in fresh]
        record["errors"] = [message for message in fresh if classify(message) == "error"]
        record["warnings"] = [message for message in fresh if classify(message) == "warning"]

        print(f"[{title}] rpc={record['rpc']} messages={len(fresh)} errors={len(record['errors'])} warnings={len(record['warnings'])}")
        for message in fresh:
            print(f"    {message.get('type')}: {str(message.get('text'))[:400]}")
        session["blocks"].append(record)

        if record.get("rpc") == "raised" or record["errors"] or (args.stop_on_warning and record["warnings"]):
            status = "failed"
            break

    session["status"] = status
    try:
        manager.save_project()
        session["saved"] = True
    except Exception as exc:
        session["saved"] = False
        session["save_error"] = f"{type(exc).__name__}: {exc}"
    session["project_after_build"] = manager.get_project_info().get("active_project")

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nstatus={status} saved={session.get('saved')} log={log_path}")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
