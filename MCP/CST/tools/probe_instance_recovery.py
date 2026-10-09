#!/usr/bin/env python3
"""Is a CST instance still usable after the guardian kills a worker?

L4 kills a worker that is blocked on an unrecognised prompt.  The worker was
inside a VBA call at that moment, so the macro never returns and CST may be left
believing a structure macro is still in progress.  If it is, the instance is
poisoned: later history operations report "Prevented attempt to change the value
for parameter ... inside history rebuild" and then block, and ``Rebuild`` fails
with "The rebuild operation cannot be used inside a structure macro".

That failure was first met by accident, as a 180 s hang in a parameter change
that had nothing obviously to do with the preceding escalation test.  This probe
establishes the link deliberately, because it decides whether escalation must
also recycle the CST instance.

Three phases, each on its own freshly launched instance and its own copy of the
project, so none can inherit another's damage.  Every phase performs some first
action and then attempts the same parameter change on the same instance:

* ``answered``  -- the prompt matches a shipped rule, is clicked, the worker
  completes normally.  This is the control.
* ``killed``    -- the prompt is unrecognised, so it is escalated, the worker is
  killed and the orphan released.  Tests whether an escalation kill alone
  poisons the instance.
* ``nested_rebuild`` -- a history block containing ``Rebuild`` is submitted,
  which asks CST to rebuild inside a rebuild.  It never returns, so the worker is
  killed on timeout.  Tests whether *that* is what poisons the instance.

Usage:
    python tools/probe_instance_recovery.py --source <pristine.cst> \
        --workdir <scratch> --name l3 --value 14.25
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cst_guardian import run_guarded  # noqa: E402
from cst_guardian.paths import ensure_cst_paths  # noqa: E402

WORKER = Path(__file__).resolve().parent / "guardian_worker.py"

#: Wording that matches the one shipped auto-answer rule, ``stale-results-discard``.
KNOWN_TEXT = "The results will be deleted."
#: Wording that matches nothing, so it must escalate.
UNKNOWN_TEXT = "Guardian recovery probe: an unrecognised question"


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


def _worker(pid: int, *args: str) -> list[str]:
    return [sys.executable, str(WORKER), "--pid", str(pid), "--no-quiet", *args]


def _summary(report) -> dict[str, object]:
    return {
        "outcome": report.outcome,
        "exit_code": report.exit_code,
        "elapsed_s": round(report.elapsed_s, 2),
        "answered": len(report.dialogs_answered),
        "escalated": len(report.escalations),
        "released": len(report.released),
    }


def _first_action(label: str, project: Path, name: str, value: str) -> list[str]:
    if label == "nested_rebuild":
        return [
            "vba",
            "--project",
            str(project),
            "--title",
            "guardian nested rebuild",
            "--code",
            f'StoreParameter("{name}", "{value}")\nRebuild\n',
        ]
    text = KNOWN_TEXT if label == "answered" else UNKNOWN_TEXT
    return ["msgbox", "--project", str(project), "--text", text]


def run_phase(
    label: str,
    *,
    source: Path,
    workdir: Path,
    name: str,
    value: str,
    timeout_s: float,
    quiet_instance: bool,
) -> dict[str, object]:
    import cst.interface as ci

    project = _fresh_copy(source, workdir / label)
    de = ci.DesignEnvironment.new(options=[])
    pid = int(de.pid())
    quiet_on_launch = None
    try:
        quiet_on_launch = bool(de.in_quiet_mode())
    except Exception:
        pass
    if not quiet_instance:
        # A programmatically launched instance comes up quiet whether or not
        # ``--quiet`` is passed, so the only way to measure CST's behaviour with
        # prompts live is to turn quiet mode off after launch.
        de.set_quiet_mode(False)
    quiet_now = None
    try:
        quiet_now = bool(de.in_quiet_mode())
    except Exception:
        pass
    logs = workdir / label / "logs"
    try:
        prompt = run_guarded(
            _worker(pid, *_first_action(label, project, name, value)),
            log_dir=logs / "1-prompt",
            timeout_s=timeout_s,
            cst_pids=None,
            require_clean_start=True,
        )
        time.sleep(3.0)
        change = run_guarded(
            _worker(
                pid,
                "set-parameter",
                "--project",
                str(project),
                "--name",
                name,
                "--value",
                value,
            ),
            log_dir=logs / "2-parameter",
            timeout_s=timeout_s,
            cst_pids=None,
            require_clean_start=False,
        )
    finally:
        try:
            de.close()
        except Exception:
            pass
    change_stdout = (logs / "2-parameter" / "worker-stdout.txt").read_text(
        encoding="utf-8", errors="replace"
    )
    return {
        "phase": label,
        "cst_pid": pid,
        "quiet_mode_on_launch": quiet_on_launch,
        "quiet_mode_during_phase": quiet_now,
        "first_action": _first_action(label, project, name, value)[0],
        "first_action_result": _summary(prompt),
        "parameter_change": _summary(change),
        "parameter_stdout": change_stdout[-1500:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--timeout", type=float, default=75.0)
    parser.add_argument(
        "--no-quiet-instance",
        action="store_true",
        help="turn quiet mode off on the launched instance, so CST's prompts are live",
    )
    parser.add_argument("--phase", action="append", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    ensure_cst_paths()
    results = []
    phases = args.phase or ["answered", "killed", "nested_rebuild"]
    for label in phases:
        result = run_phase(
            label,
            source=args.source.resolve(),
            workdir=args.workdir.resolve(),
            name=args.name,
            value=args.value,
            timeout_s=args.timeout,
            quiet_instance=not args.no_quiet_instance,
        )
        results.append(result)
        first = result["first_action_result"]
        print(
            "%-15s first=%-10s answered=%d escalated=%d released=%d  "
            "-> parameter=%-10s (%.1fs)"
            % (
                label,
                first["outcome"],
                first["answered"],
                first["escalated"],
                first["released"],
                result["parameter_change"]["outcome"],
                result["parameter_change"]["elapsed_s"],
            )
        )
        time.sleep(5.0)

    verdict = {r["phase"]: r["parameter_change"]["outcome"] for r in results}
    payload = {
        "source": str(args.source.resolve()),
        "parameter": {"name": args.name, "value": args.value},
        "quiet_instance": not args.no_quiet_instance,
        "verdict": verdict,
        "escalation_kill_poisons_instance": (
            verdict.get("answered") == "completed" and verdict.get("killed") != "completed"
        ),
        "nested_rebuild_poisons_instance": (
            verdict.get("answered") == "completed"
            and verdict.get("nested_rebuild") != "completed"
        ),
        "phases": results,
    }
    print(json.dumps(verdict, indent=2))
    for key in ("escalation_kill_poisons_instance", "nested_rebuild_poisons_instance"):
        print("%s: %s" % (key, payload[key]))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
