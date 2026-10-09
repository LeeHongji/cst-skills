"""Run one solve-and-export through the guardian and report what the guard saw.

Every live verification script so far has open-coded the same ``run_guarded`` call
around ``guardian_worker.py solve``. This is that call, on its own, so a run can be
driven without borrowing a verification script that carries an unrelated design's
paths baked into it.

The guard report is the point, not the exit code: it records the dialogs answered,
the escalations, and now also any modal that disabled CST's main window without
offering anything readable to answer.

Usage:
  guarded_solve.py --project <path.cst> --export <stem> --log-dir <dir> [--timeout S]

``--export`` must not carry a Touchstone suffix: CST appends ``.s2p``, ``.s4p`` and
so on according to the port count, so the caller cannot know it up front.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("CST_INSTALL_ROOT", r"C:\CST")
_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from cst_guardian import run_guarded  # noqa: E402

PYTHON = _HERE.parents[1] / ".venv" / "Scripts" / "python.exe"
WORKER = _HERE.parent / "guardian_worker.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=7200.0)
    args = parser.parse_args(argv)

    if args.export.suffix.lower().startswith(".s") and args.export.suffix.lower().endswith("p"):
        parser.error(
            f"--export must be a stem without a Touchstone suffix; got {args.export.name!r}"
        )
    if not args.project.exists():
        parser.error(f"project does not exist: {args.project}")

    args.log_dir.mkdir(parents=True, exist_ok=True)
    args.export.parent.mkdir(parents=True, exist_ok=True)

    report = run_guarded(
        [
            str(PYTHON),
            str(WORKER),
            "solve",
            "--project",
            str(args.project.resolve()),
            "--export",
            str(args.export.resolve()),
        ],
        log_dir=args.log_dir,
        timeout_s=args.timeout,
    )

    exported = sorted(args.export.parent.glob(args.export.name + ".s*p"))
    summary = {
        "outcome": report.outcome,
        "exit_code": report.exit_code,
        "elapsed_s": round(report.elapsed_s, 1),
        "dialogs_answered": len(report.dialogs_answered),
        "escalations": len(report.escalations),
        "exports": [str(path) for path in exported],
        "log_dir": str(args.log_dir),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report.outcome == "completed" and exported else 1


if __name__ == "__main__":
    raise SystemExit(main())
