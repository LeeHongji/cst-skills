"""Read the entities, bounding boxes and parameters CST actually holds.

Produces the observation JSON consumed by ``cst-cad verify-against-cst``. The
bounding boxes come from ``Solid.GetLooseBoundingBoxOfShape``, which the
vendored runtime CLI does not expose, so this walks the shape list in VBA and
writes the numbers to a scratch file rather than parsing the message window.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

os.environ.setdefault("CST_INSTALL_ROOT", r"C:\CST")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "CST"))

from cst_automation import CSTSessionManager  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cst_cad.observation import VBA_TEMPLATE, parse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project")
    parser.add_argument("--output", required=True)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    manager = CSTSessionManager()
    manager.connect()
    if args.project:
        manager.open_project(str(Path(args.project).resolve()))
    info = manager.get_project_info()

    scratch = Path(tempfile.gettempdir()) / "cst_cad_observation.txt"
    scratch.unlink(missing_ok=True)
    # A read-only query does not belong in the model history, so this is the
    # one place execute_vba is the right tool rather than add_to_history.
    manager.execute_vba(VBA_TEMPLATE.format(output=str(scratch).replace("\\", "\\\\")))

    if not scratch.exists():
        messages = manager.get_project_info().get("messages_tail", [])
        raise RuntimeError(f"observation VBA produced no output. Recent CST messages: {json.dumps(messages, ensure_ascii=False)}")

    observation = parse(scratch.read_text(encoding="utf-8", errors="replace"))
    observation["project_path"] = (info.get("active_project") or {}).get("filename")
    observation["producer"] = "cst_observe.py Solid.GetLooseBoundingBoxOfShape"
    observation["design_environment_pid"] = info.get("design_environment_pid")

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(observation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"entities={len(observation['entities'])} parameters={len(observation['parameters'])} -> {target}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
