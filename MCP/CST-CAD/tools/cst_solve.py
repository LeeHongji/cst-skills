"""Apply an optional solver override, save, solve, and export S-parameters.

Follows the project safety rules: the working copy is saved before the solver
starts, every CST message produced during the run is captured, and the project
is closed before any offline result extraction happens.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("CST_INSTALL_ROOT", r"C:\CST")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "CST"))

from cst_automation import CSTSessionManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--override-vba", action="append", default=[])
    parser.add_argument("--touchstone")
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    manager = CSTSessionManager()
    manager.connect()
    manager.open_project(str(project_path))
    project = manager._require_project()
    seen = len(project.get_messages() or [])

    session: dict[str, Any] = {"project": str(project_path), "overrides": [], "started_at": time.time()}

    for override in args.override_vba:
        path = Path(override)
        title = path.stem
        manager.add_to_history(title, path.read_text(encoding="utf-8"))
        messages = project.get_messages() or []
        fresh = messages[seen:]
        seen = len(messages)
        session["overrides"].append({"block": title, "messages": [dict(m) for m in fresh]})
        print(f"[override {title}] messages={len(fresh)}")

    # Rule 5: save the working copy before the solver runs.
    manager.save_project()
    print("saved before solve")

    solve_start = time.time()
    try:
        manager.run_solver()
        session["solver_rpc"] = "returned"
    except Exception as exc:
        session["solver_rpc"] = "raised"
        session["solver_error"] = f"{type(exc).__name__}: {exc}"
    session["solver_seconds"] = time.time() - solve_start
    print(f"solver returned after {session['solver_seconds']:.1f} s ({session.get('solver_rpc')})")

    messages = project.get_messages() or []
    fresh = messages[seen:]
    seen = len(messages)
    session["solver_messages"] = [dict(m) for m in fresh]
    session["solver_errors"] = [dict(m) for m in fresh if str(m.get("type", "")).upper() == "ERROR"]
    for message in fresh[-40:]:
        print(f"    {message.get('type')}: {str(message.get('text'))[:300]}")

    manager.save_project()
    session["saved_after_solve"] = True

    if args.touchstone:
        # CST resolves a relative export path against the project's Result directory
        # and reports success either way, so pass an absolute path and confirm the
        # file afterwards rather than trusting the return value.
        target = Path(args.touchstone).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            manager.export_touchstone(str(target.with_suffix("")), impedance=50.0, export_type="S", data_format="RI")
            session["touchstone"] = str(target)
            session["touchstone_exists"] = target.exists()
            session["touchstone_bytes"] = target.stat().st_size if target.exists() else 0
            print(f"touchstone -> {target} exists={target.exists()} bytes={session['touchstone_bytes']}")
        except Exception as exc:
            session["touchstone_error"] = f"{type(exc).__name__}: {exc}"
            print(f"touchstone export failed: {session['touchstone_error']}")
        manager.save_project()

    try:
        results = manager.list_results()
        session["result_tree_count"] = results["count"]
        session["result_tree_sample"] = [item for item in results["items"] if "S-Parameters" in str(item)][:20]
    except Exception as exc:
        session["result_tree_error"] = f"{type(exc).__name__}: {exc}"

    session["finished_at"] = time.time()
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"log={log_path} solver_errors={len(session.get('solver_errors', []))}")
    return 0 if not session.get("solver_errors") and session.get("solver_rpc") == "returned" else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
