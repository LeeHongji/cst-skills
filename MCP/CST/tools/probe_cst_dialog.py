#!/usr/bin/env python3
"""Record the full window timeline while a CST worker command runs.

Characterising a prompt needs more than one sample.  Opening a project alone
raises and drops several transient Qt windows (a progress bar, a splash), so a
single snapshot easily captures the wrong one.  This tool keeps every window that
appears, how long it stayed, and a screenshot of each, which is what turns an
unknown dialog into a table entry.

Usage:
    python tools/probe_cst_dialog.py --output <dir> -- <worker args...>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cst_guardian.paths import running_cst_pids  # noqa: E402
from cst_guardian.win32_dialogs import capture_window  # noqa: E402
from dump_cst_windows import dump  # noqa: E402

WORKER = Path(__file__).resolve().parent / "guardian_worker.py"


def snapshot() -> dict[int, dict[str, object]]:
    windows: dict[int, dict[str, object]] = {}
    for pid in running_cst_pids():
        for row in dump(pid):
            row["cst_pid"] = pid
            windows[int(row["hwnd"])] = row
    return windows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--linger", type=float, default=3.0,
                        help="keep sampling this long after the worker exits")
    parser.add_argument("worker_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    worker_args = [a for a in args.worker_args if a != "--"]
    if not worker_args:
        parser.error("supply worker arguments after --")

    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    baseline = snapshot()
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, str(WORKER), *worker_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    seen: dict[int, dict[str, object]] = {}
    exited_at: float | None = None
    while True:
        now = time.monotonic() - started
        for hwnd, row in snapshot().items():
            if hwnd in baseline:
                continue
            record = seen.setdefault(
                hwnd, {**row, "first_seen_s": round(now, 2), "samples": 0}
            )
            record["samples"] = int(record["samples"]) + 1
            record["last_seen_s"] = round(now, 2)
            if not record.get("screenshot"):
                path = output / f"window-{hwnd}.png"
                record["screenshot"] = str(path) if capture_window(hwnd, path) else None
            # Text can arrive after the window does; keep the richest observation.
            if len(row["child_text"]) > len(record["child_text"]):
                record["child_text"] = row["child_text"]
            if len(row["buttons"]) > len(record["buttons"]):
                record["buttons"] = row["buttons"]

        if proc.poll() is not None and exited_at is None:
            exited_at = now
        if exited_at is not None and now - exited_at >= args.linger:
            break
        if now > args.timeout:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            break
        time.sleep(args.interval)

    out, err = proc.communicate()
    report = {
        "worker_args": worker_args,
        "exit_code": proc.returncode,
        "worker_exited_at_s": exited_at,
        "elapsed_s": round(time.monotonic() - started, 2),
        "baseline_window_count": len(baseline),
        "new_windows": sorted(seen.values(), key=lambda r: r["first_seen_s"]),
        "worker_stdout": out,
        "worker_stderr": err,
    }
    (output / "dialog-timeline.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
