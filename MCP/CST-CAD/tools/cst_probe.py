"""Read-only CST Design Environment probe.

Reports the running Design Environment, its version, and the currently open
projects without modifying anything. Run with the MCP/CST venv interpreter.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("CST_INSTALL_ROOT", r"C:\CST")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "CST"))

from cst_automation import CSTSessionManager, dumps  # noqa: E402


def main() -> None:
    manager = CSTSessionManager()
    report: dict = {"detect": manager.detect_environment()}
    try:
        report["running"] = manager.list_running()
    except Exception as exc:  # pragma: no cover - environment dependent
        report["running_error"] = repr(exc)
    try:
        report["connect"] = manager.connect()
    except Exception as exc:  # pragma: no cover - environment dependent
        report["connect_error"] = repr(exc)
    print(dumps(report))


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
