#!/usr/bin/env python3
"""Measure what CST does with each class of conflict while quiet mode is on.

Quiet mode is the production setting, so the failure modes that matter are the
ones that survive it.  A conflict can end up in one of five states and only two
of them are safe (see ``conflict_cases``); the dangerous ones are those where the
call returns normally and the caller has no way to know it did nothing.

Every case runs under the guardian, in its own freshly launched CST instance, on
its own fresh copy of the project, and the worker never saves.  Isolation is not
tidiness here: a refused parameter change leaves the modeller mid-rebuild, and a
later case measured on that instance reports the earlier case's damage as its
own.  That mistake has already been made once in this project and cost a day of
wrong conclusions.

The output is a matrix intended to be read, and a list of verdicts that need a
code-level guard.

Usage:
    python tools/probe_conflict_matrix.py --source <pristine.cst> \
        --workdir <scratch> --output matrix.json
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conflict_cases import CASES, UNSAFE_VERDICTS, classify  # noqa: E402
from cst_guardian import run_guarded, running_cst_pids  # noqa: E402
from cst_guardian.paths import ensure_cst_paths  # noqa: E402

WORKER = Path(__file__).resolve().parent / "guardian_worker.py"


@contextlib.contextmanager
def _instance():
    ensure_cst_paths()
    import cst.interface as ci

    de = ci.DesignEnvironment.new(options=["--quiet"])
    try:
        yield int(de.pid())
    finally:
        with contextlib.suppress(Exception):
            de.close()


def _fresh_copy(source: Path, target_dir: Path) -> Path:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    companion = source.with_suffix("")
    if companion.is_dir():
        shutil.copytree(companion, target_dir / companion.name)
    return target


def _records(log_dir: Path) -> list[dict]:
    path = log_dir / "worker-stdout.txt"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    decoder = json.JSONDecoder()
    out: list[dict] = []
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
        index = end
    return out


def run_case(case, *, source: Path, workdir: Path, timeout_s: float) -> dict:
    project = _fresh_copy(source, workdir / case.case_id)
    logs = workdir / case.case_id / "logs"
    with _instance() as pid:
        report = run_guarded(
            [
                sys.executable,
                str(WORKER),
                "--pid",
                str(pid),
                "conflict",
                "--project",
                str(project),
                "--case",
                case.case_id,
            ],
            log_dir=logs,
            timeout_s=timeout_s,
            require_clean_start=False,
        )
    records = _records(logs)
    after = next((r for r in records if r.get("stage") == "after"), None)
    before = next((r for r in records if r.get("stage") == "before"), {})
    crash = next((r for r in records if r.get("error_type")), None)
    new_messages = (after or {}).get("new_messages") or []
    verdict = classify(
        outcome=report.outcome,
        error=(after or {}).get("error"),
        before=before.get("state"),
        # None, not {}: a missing after-observation must not be read as "unchanged".
        after=(after or {}).get("state_after"),
        new_messages=new_messages,
    )
    return {
        "case": case.case_id,
        "category": case.category,
        "description": case.description,
        "should": case.should,
        "verdict": verdict,
        "needs_guard": verdict in UNSAFE_VERDICTS,
        "process_outcome": report.outcome,
        "elapsed_s": (after or {}).get("elapsed_s"),
        "error": (after or {}).get("error"),
        "worker_crash": crash,
        "state_before": before.get("state"),
        "state_after": (after or {}).get("state_after"),
        "dialogs_answered": len(report.dialogs_answered),
        "escalations": len(report.escalations),
        "cst_messages": [
            {"type": m.get("type"), "text": str(m.get("text", ""))[:400]}
            for m in new_messages
        ],
        "evidence": str(logs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--case", action="append", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    selected = [c for c in CASES if not args.case or c.case_id in args.case]
    results = []
    print("%-28s %-10s %-22s %s" % ("case", "category", "verdict", "detail"))
    for case in selected:
        result = run_case(
            case,
            source=args.source.resolve(),
            workdir=args.workdir.resolve(),
            timeout_s=args.timeout,
        )
        results.append(result)
        detail = (result["error"] or "").split("\\n")[0][:90]
        if not detail and result["cst_messages"]:
            first = result["cst_messages"][0]
            detail = "%s: %s" % (first["type"], first["text"].replace("\n", " ")[:80])
        print(
            "%-28s %-10s %-22s %s"
            % (result["case"], result["category"], result["verdict"], detail)
        )
        time.sleep(2.0)

    unsafe = [r for r in results if r["needs_guard"]]
    payload = {
        "generated_at_unix": time.time(),
        "quiet_mode": True,
        "source": str(args.source.resolve()),
        "case_count": len(results),
        "verdict_counts": {
            verdict: sum(1 for r in results if r["verdict"] == verdict)
            for verdict in sorted({r["verdict"] for r in results})
        },
        "cases_needing_a_code_guard": [r["case"] for r in unsafe],
        "cst_pids_at_end": running_cst_pids(),
        "cases": results,
    }
    print()
    print("verdict counts:", json.dumps(payload["verdict_counts"]))
    print("need a code guard:", payload["cases_needing_a_code_guard"])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
