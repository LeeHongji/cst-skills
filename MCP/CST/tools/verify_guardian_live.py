#!/usr/bin/env python3
"""Live verification of the CST session guardian against a running CST.

Four scenarios, each producing evidence on disk rather than a console claim:

``L0``  A real DRC run on a neutral microstrip IR passes; the same IR with two
        solids forced to overlap fails.  CST is never launched, which is the
        point: a modelling conflict caught here cannot become a blocking prompt
        later.  The active guardian check is deliberately independent of the
        frozen Fig. 15 legacy package.
``L3``  A genuine CST-owned modal whose text the rule table recognises is answered
        with ``WM_COMMAND`` and the worker keeps running.
``L4``  A genuine CST-owned modal whose text is unrecognised is screenshotted, the
        worker is killed, and both the supervisor and CST survive.
``guard``  Every call CST accepts without complaint -- a garbage parameter value,
        an expression referring to nothing, a zero conductor width, deleting a
        parameter still in use -- is refused before it reaches CST, and the model
        is unchanged afterwards.
``param``  The production path: a parameter change on a copy of a solved project
        must complete and the new value must read back from CST.

Two things about the prompts used here are worth stating plainly, because both
were established by measurement and both limit what these scenarios prove:

* The L3/L4 prompts are manufactured with a VBA ``MsgBox``.  Quiet mode does not
  suppress those -- it suppresses CST's *own* prompts -- so they stay visible on
  the production settings, which is what makes them usable as a fixture.  The
  cost is that the rule table's text patterns are exercised against wording this
  file chose, not wording CST chose.
* Every scenario runs against an instance this script launched, not against
  whatever CST the engineer has open.  Attaching to a long-lived interactive
  instance produced results that turned out to describe damage left by earlier
  experiments rather than the behaviour under test.

Usage:
    python tools/verify_guardian_live.py --output <dir> [--skip-live]
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(REPO / "MCP" / "CST-CAD" / "src"))

from cst_guardian import (  # noqa: E402
    KNOWN_RULES,
    cst_instance_pids,
    enumerate_dialogs,
    normalize_button_text,
    release_dialog,
    run_guarded,
    running_cst_pids,
)

WORKER = Path(__file__).resolve().parent / "guardian_worker.py"
SOLVED_PROJECT = (
    REPO
    / "cst_runs"
    / "cursor-cst-link-test-stepped-impedance-lpf_20260910"
    / "working"
    / "stepped_impedance_lpf_2p4ghz.cst"
)

STALE_RESULTS_TEXT = "The results will be deleted."
UNKNOWN_TEXT = "Guardian L4 probe: an unrecognised question"


# -- L0 ----------------------------------------------------------------------


def _find_solid(doc: dict, net_name: str, solid_id: str) -> dict | None:
    for net in doc.get("nets", []):
        if net.get("name") != net_name:
            continue
        for solid in net.get("solids", []):
            if solid.get("id") == solid_id:
                return solid
    return None


def _centre(box: dict[str, float]) -> tuple[float, float]:
    return ((box["x0"] + box["x1"]) / 2.0, (box["y0"] + box["y1"]) / 2.0)


def _neutral_guardian_ir() -> dict:
    """Build the small no-solve fixture used by the active L0 DRC check.

    This is intentionally a local, paper-free microstrip coupon.  Keeping it in
    code makes the guardian test self-contained and prevents the active harness
    from depending on the frozen Fig. 15 reconstruction.
    """
    from cst_cad.dsl import ModelBuilder

    model = ModelBuilder(model_id="neutral-microstrip-guardian", title="Neutral microstrip guardian fixture")
    model.units(length="mm", frequency="GHz")
    t_cu = model.param("t_cu", 0.035, provenance="assumption")
    h = model.param("h", 1.0, provenance="assumption")
    model.param("r2_feed_gap", 0.5, minimum=0.1, maximum=1.0, provenance="assumption")
    model.material("Sub", kind="normal", epsilon=4.4, mu=1.0, tan_delta=0.02)
    model.material("PEC", kind="pec")
    model.layer("sub", 0.0, h, "Sub", role="substrate")
    model.layer("top", h, h + t_cu, "PEC", role="signal")

    board = model.net("BOARD", "sub", net_class="reference")
    board.box(-6.0, -6.0, 20.0, 22.0)
    resonator = model.net("RESONATOR_1", "top")
    resonator.rect(0.0, 0.0, 0.4, 10.0, solid_id="line")
    resonator.rect(-3.0, 10.0, 3.4, 0.4, solid_id="arm")
    feed = model.net("SOURCE_FEED", "top")
    feed.rect(0.9, 0.0, 0.4, 8.0, solid_id="line")
    model.port("P1", 1, "RESONATOR_1", "ymin", 0.0, 0.0, 0.0, 0.4, 0.0, h + t_cu)
    model.rule("width", "min_width", "layer:top", min_width=0.28)
    model.rule("spacing", "min_spacing", "layer:top", min_spacing=0.15)
    model.rule("no_short", "no_cross_net_short", "layer:top")
    return model.build()


def scenario_l0(output: Path) -> dict[str, object]:
    """DRC must pass on the neutral IR and fail once two solids overlap."""
    from cst_cad import drc

    out = output / "l0-drc-prevention"
    out.mkdir(parents=True, exist_ok=True)

    doc = _neutral_guardian_ir()
    clean = drc.run(doc)
    (out / "drc-clean.json").write_text(
        json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Move the source feed line on top of resonator 1: an unambiguous conflict
    # of exactly the kind CST reports as a modelling error.
    broken = copy.deepcopy(doc)
    victim = _find_solid(broken, "SOURCE_FEED", "line")
    target = _find_solid(broken, "RESONATOR_1", "arm")
    if victim is None or target is None:
        return {
            "scenario": "L0",
            "status": "error",
            "detail": "expected solids SOURCE_FEED:line and RESONATOR_1:outer_left",
        }
    vx, vy = _centre(victim["box"])
    tx, ty = _centre(target["box"])
    for axis, delta in (("x", tx - vx), ("y", ty - vy)):
        victim["box"][f"{axis}0"] += delta
        victim["box"][f"{axis}1"] += delta
    victim.pop("expressions", None)  # numeric override, no longer expression-derived

    dirty = drc.run(broken)
    (out / "drc-overlapping.json").write_text(
        json.dumps(dirty, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "overlapping-ir.json").write_text(
        json.dumps(broken, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    failed = [c for c in dirty.get("checks", []) if c.get("status") != "pass"]
    return {
        "scenario": "L0",
        "status": "pass"
        if clean.get("status") == "pass" and dirty.get("status") != "pass"
        else "fail",
        "clean_status": clean.get("status"),
        "clean_summary": clean.get("summary"),
        "overlapping_status": dirty.get("status"),
        "overlapping_summary": dirty.get("summary"),
        "rules_that_caught_it": [c.get("rule") for c in failed],
        "cst_launched": False,
        "evidence": str(out),
    }


# -- shared CST helpers ------------------------------------------------------


def _cleanup_dialogs(pids: list[int]) -> list[dict[str, object]]:
    """Dismiss any prompt still on screen so the next scenario starts clean.

    Selection is by control id, never by caption.  An earlier version matched
    captions against {"ok","yes","no",...} and silently cleaned nothing on this
    machine, where the same buttons read "\u662f(&Y)" and "\u5426(&N)" -- which let a stale
    prompt leak into the following scenario and produce a passing result for
    entirely the wrong reason.
    """
    dismissed: list[dict[str, object]] = []
    for pid in pids:
        for dialog in enumerate_dialogs(pid):
            record: dict[str, object] = {
                "cst_pid": pid,
                "title": dialog.title,
                "text": list(dialog.child_text),
            }
            try:
                button = release_dialog(dialog)
            except Exception as exc:
                record["error"] = str(exc)
                dismissed.append(record)
                continue
            if button is None:
                record["error"] = "no standard button to press"
            else:
                record["pressed"] = normalize_button_text(button.text)
                record["control_id"] = button.control_id
            dismissed.append(record)
    return dismissed


def _assert_clean(label: str, cst_pid: int) -> dict[str, object]:
    """Release leftovers and report whether the scenario can start clean."""
    released = _cleanup_dialogs(cst_instance_pids(cst_pid))
    if released:
        time.sleep(1.5)
    remaining = [
        dialog.to_json()
        for pid in cst_instance_pids(cst_pid)
        for dialog in enumerate_dialogs(pid)
    ]
    return {"label": label, "released": released, "still_present": remaining}


@contextlib.contextmanager
def dedicated_instance():
    """Launch a CST instance for this run and shut it down afterwards.

    Reusing a long-lived interactive instance is what made an earlier round of
    these measurements worthless: a parameter change appeared to hang for 180 s,
    and the cause was a history rebuild left stuck by a previous experiment in
    that same instance, not the change itself.  A fresh instance per verification
    run is the only way the outcome describes the code under test.
    """
    from cst_guardian.paths import ensure_cst_paths

    ensure_cst_paths()
    import cst.interface as ci

    de = ci.DesignEnvironment.new(options=["--quiet"])
    try:
        yield int(de.pid())
    finally:
        with contextlib.suppress(Exception):
            de.close()


def _worker_records(log_dir: Path) -> list[dict[str, object]]:
    """Parse every JSON object the worker printed.

    The worker pretty-prints, so records span several lines and cannot be read
    line by line; ``raw_decode`` walks the stream instead.
    """
    path = log_dir / "worker-stdout.txt"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    decoder = json.JSONDecoder()
    records: list[dict[str, object]] = []
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
            records.append(obj)
        index = end
    return records


def _worker_json(log_dir: Path, stage: str | None = None) -> dict[str, object]:
    """The worker's last record, optionally the last one at a given stage."""
    records = _worker_records(log_dir)
    if stage is not None:
        records = [r for r in records if r.get("stage") == stage]
    return records[-1] if records else {}


def _worker_argv(pid: int, *args: str) -> list[str]:
    """Build worker argv pinned to one Design Environment.

    ``connect_to_any`` is unusable here: with more than one CST instance running
    it is not determined which one the worker attaches to, so the project could be
    opened in a different instance from the one being observed.
    """
    return [sys.executable, str(WORKER), "--pid", str(pid), *args]


def _vba_scenario(
    name: str,
    output: Path,
    project: Path,
    message: str,
    *,
    cst_pid: int,
    expect: str,
    timeout_s: float,
    kill_on_escalation: bool,
) -> dict[str, object]:
    out = output / name
    out.mkdir(parents=True, exist_ok=True)
    precondition = _assert_clean(name, cst_pid)
    pids_before = running_cst_pids()
    argv = _worker_argv(
        cst_pid,
        "msgbox",
        "--project",
        str(project),
        "--text",
        message,
    )
    report = run_guarded(
        argv,
        log_dir=out,
        timeout_s=timeout_s,
        cst_pid_roots=[cst_pid],
        poll_interval_s=0.4,
        stable_polls=2,
        kill_on_escalation=kill_on_escalation,
    )
    time.sleep(1.0)
    cleanup = _cleanup_dialogs(cst_instance_pids(cst_pid))
    pids_after = running_cst_pids()
    observed = report.dialogs_answered + report.escalations
    return {
        "scenario": name,
        "status": "pass" if report.outcome == expect else "fail",
        "expected_outcome": expect,
        "outcome": report.outcome,
        "precondition": precondition,
        "started_clean": not precondition["still_present"],
        "worker_reaped": report.exit_code is not None,
        "dialogs_answered": len(report.dialogs_answered),
        "escalations": len(report.escalations),
        "orphans_released": len(report.released),
        "screenshots": [e.get("screenshot") for e in observed if e.get("screenshot")],
        "observed_dialog_text": [
            (e.get("dialog") or {}).get("child_text") for e in observed
        ],
        "observed_buttons": [
            [b.get("text") for b in (e.get("dialog") or {}).get("buttons", [])]
            for e in observed
        ],
        "cst_pids_before": pids_before,
        "cst_pids_after": pids_after,
        "cst_survived": bool(set(pids_before) & set(pids_after)),
        "harness_cleanup": cleanup,
        "evidence": str(out),
    }


def scenario_l3(output: Path, project: Path, cst_pid: int) -> dict[str, object]:
    """A recognised prompt is clicked and the worker continues."""
    return _vba_scenario(
        "l3-known-dialog",
        output,
        project,
        STALE_RESULTS_TEXT,
        cst_pid=cst_pid,
        expect="completed",
        timeout_s=120.0,
        kill_on_escalation=True,
    )


def scenario_l4(output: Path, project: Path, cst_pid: int) -> dict[str, object]:
    """An unrecognised prompt is escalated and the worker is killed."""
    return _vba_scenario(
        "l4-unknown-dialog",
        output,
        project,
        UNKNOWN_TEXT,
        cst_pid=cst_pid,
        expect="escalated",
        timeout_s=120.0,
        kill_on_escalation=True,
    )


def scenario_l1(output: Path, cst_pid: int) -> dict[str, object]:
    """Quiet mode is on for the duration of the session.

    This is the production setting, so it is asserted rather than merely
    recorded: every other quiet-mode scenario below is only meaningful if the
    session really was quiet while it ran.
    """
    out = output / "l1-quiet-mode"
    out.mkdir(parents=True, exist_ok=True)
    report = run_guarded(
        _worker_argv(cst_pid, "probe"),
        log_dir=out,
        timeout_s=60.0,
        cst_pid_roots=[cst_pid],
        require_clean_start=False,
    )
    session = _worker_json(out).get("session", {})
    return {
        "scenario": "l1-quiet-mode",
        "status": "pass"
        if report.outcome == "completed" and session.get("quiet_mode") is True
        else "fail",
        "outcome": report.outcome,
        "session": session,
        "evidence": str(out),
    }


def scenario_l2(output: Path, cst_pid: int) -> dict[str, object]:
    """A worker that stops making progress is reaped and CST survives.

    No dialog is involved.  L3 and L4 both depend on the guardian being able to
    see a prompt; this is the case where there is nothing to see, which is the one
    that actually caught two real hangs during development.
    """
    out = output / "l2-timeout-watchdog"
    out.mkdir(parents=True, exist_ok=True)
    pids_before = running_cst_pids()
    started = time.time()
    report = run_guarded(
        _worker_argv(cst_pid, "sleep", "--seconds", "300"),
        log_dir=out,
        timeout_s=20.0,
        cst_pid_roots=[cst_pid],
        require_clean_start=False,
    )
    elapsed = time.time() - started
    pids_after = running_cst_pids()
    return {
        "scenario": "l2-timeout-watchdog",
        "status": "pass"
        if report.outcome == "timeout"
        and report.exit_code is not None
        and cst_pid in pids_after
        and elapsed < 90.0
        else "fail",
        "outcome": report.outcome,
        "worker_reaped": report.exit_code is not None,
        "elapsed_s": round(elapsed, 1),
        "cst_pids_before": pids_before,
        "cst_pids_after": pids_after,
        "cst_survived": cst_pid in pids_after,
        "evidence": str(out),
    }


def scenario_iterate(
    output: Path, project: Path, cst_pid: int, parameter: str, values: list[str]
) -> dict[str, object]:
    """Repeated parameter changes must complete and each must take effect.

    This is the call ``cst_iterate`` makes on every iteration.  It is asserted on
    read-back rather than on the absence of an exception, because the way CST
    refuses a parameter change is to log a warning and carry on: writing
    ``StoreParameter`` into the history tree makes it report "Prevented attempt to
    change the value for parameter ... inside history rebuild" and leave the old
    value in place.  A test that only checked for an exception would pass.
    """
    out = output / "param-iterations"
    out.mkdir(parents=True, exist_ok=True)
    report = run_guarded(
        _worker_argv(
            cst_pid,
            "iterate",
            "--project",
            str(project),
            "--name",
            parameter,
            "--values",
            ",".join(values),
        ),
        log_dir=out,
        timeout_s=300.0,
        cst_pid_roots=[cst_pid],
        require_clean_start=False,
    )
    after = _worker_json(out, stage="after")
    applied = after.get("applied") or []
    took_effect = bool(after.get("all_took_effect"))
    return {
        "scenario": "param-iterations",
        "status": "pass"
        if report.outcome == "completed"
        and took_effect
        and len(applied) == len(values)
        else "fail",
        "outcome": report.outcome,
        "parameter": parameter,
        "requested_values": values,
        "applied": applied,
        "all_took_effect": took_effect,
        "dialogs_answered": len(report.dialogs_answered),
        "escalations": len(report.escalations),
        "cst_messages": after.get("messages_tail"),
        "evidence": str(out),
    }


def scenario_guards(output: Path, project: Path, cst_pid: int) -> dict[str, object]:
    """Every call CST accepts without complaint must be refused before it lands.

    The conflict matrix measured what CST does with nineteen deliberately wrong
    calls under quiet mode: only five raise.  This scenario runs the dangerous
    ones back through the guards against the same real CST and asserts two
    things -- that each is refused, and that the parameter table is unchanged
    afterwards.  Refusing after CST has already accepted the value would leave
    the next call reading a model containing what we rejected.
    """
    out = output / "guard-refusals"
    out.mkdir(parents=True, exist_ok=True)
    report = run_guarded(
        _worker_argv(cst_pid, "guard", "--project", str(project)),
        log_dir=out,
        timeout_s=180.0,
        cst_pid_roots=[cst_pid],
        require_clean_start=False,
    )
    after = _worker_json(out, stage="after")
    attempts = after.get("attempts") or []
    return {
        "scenario": "guard-refusals",
        "status": "pass"
        if report.outcome == "completed"
        and attempts
        and after.get("all_refused")
        and after.get("model_never_changed")
        else "fail",
        "outcome": report.outcome,
        "attempt_count": len(attempts),
        "all_refused": after.get("all_refused"),
        "model_never_changed": after.get("model_never_changed"),
        "attempts": [
            {
                "attempt": a["attempt"],
                "refused": a["refused"],
                "model_unchanged": a["model_unchanged"],
                "refusal": (a.get("refusal") or a.get("unexpected_error") or "")[:200],
            }
            for a in attempts
        ],
        "evidence": str(out),
    }


def scenario_solve(
    output: Path, project: Path, cst_pid: int, timeout_s: float
) -> dict[str, object]:
    """A real solver run under quiet mode must finish and produce exported evidence.

    Everything above proves the guardian does not get stuck.  This proves it can
    still do the job: the solver runs to completion unattended and the result
    leaves the ``Result/`` cache as a Touchstone file, which is what survives
    reclamation and can be re-reviewed.
    """
    out = output / "task-solve"
    out.mkdir(parents=True, exist_ok=True)
    export = out / "s-parameters.s2p"
    report = run_guarded(
        _worker_argv(
            cst_pid, "solve", "--project", str(project), "--export", str(export)
        ),
        log_dir=out,
        timeout_s=timeout_s,
        cst_pid_roots=[cst_pid],
        require_clean_start=False,
    )
    after = _worker_json(out, stage="after")
    produced = sorted(p.name for p in out.glob("s-parameters.s*p"))
    return {
        "scenario": "task-solve",
        "status": "pass"
        if report.outcome == "completed" and produced
        else "fail",
        "outcome": report.outcome,
        "solve_s": after.get("solve_s"),
        "exported_files": produced,
        "dialogs_answered": len(report.dialogs_answered),
        "escalations": len(report.escalations),
        "cst_messages": after.get("messages_tail"),
        "evidence": str(out),
    }


def copy_project(source: Path, destination_dir: Path) -> Path:
    """Copy a ``.cst`` and its companion directory into a fresh workspace.

    Never operate on the original: the source is a user artefact and the run
    workspace is the only place a write is allowed.
    """
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / source.name
    if target.exists():
        return target  # reuse the existing working copy; never re-copy over it
    shutil.copy2(source, target)
    companion = source.with_suffix("")
    if companion.is_dir():
        shutil.copytree(companion, destination_dir / companion.name)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-solve", action="store_true", help="skip the solver run")
    parser.add_argument(
        "--skip-live",
        "--skip-real",
        dest="skip_live",
        action="store_true",
        help="run only the neutral no-solve DRC guard check",
    )
    parser.add_argument("--parameter", default="l3")
    parser.add_argument(
        "--values",
        default="14.0,14.25,14.5",
        help="comma-separated values applied in sequence",
    )
    parser.add_argument("--solve-timeout", type=float, default=1800.0)
    args = parser.parse_args(argv)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = [scenario_l0(output)]

    if args.skip_live:
        report = {
            "generated_at_unix": time.time(),
            "quiet_mode": True,
            "known_rules": [
                {"rule_id": r.rule_id, "action": r.action} for r in KNOWN_RULES
            ],
            "scenarios": results,
            "all_passed": all(r.get("status") in {"pass", "observed", "skipped"} for r in results),
            "live_suite_skipped": True,
        }
        (output / "verification-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["all_passed"] else 1

    values = [v.strip() for v in args.values.split(",") if v.strip()]
    with dedicated_instance() as cst_pid:
        working = copy_project(SOLVED_PROJECT, output / "working")
        results.append(
            {
                "scenario": "copy-source-project",
                "status": "pass",
                "source": str(SOLVED_PROJECT),
                "working_copy": str(working),
            }
        )
        results.append(scenario_l1(output, cst_pid))
        results.append(scenario_l2(output, cst_pid))
        results.append(scenario_l3(output, working, cst_pid))
        results.append(scenario_l4(output, working, cst_pid))
        results.append(scenario_guards(output, working, cst_pid))
        results.append(
            scenario_iterate(output, working, cst_pid, args.parameter, values)
        )
        if not args.skip_solve:
            results.append(
                scenario_solve(output, working, cst_pid, args.solve_timeout)
            )
        pids_at_end = cst_instance_pids(cst_pid)
        leftover = [
            dialog.to_json()
            for pid in pids_at_end
            for dialog in enumerate_dialogs(pid)
        ]
        results.append(
            {
                "scenario": "no-leftover-dialogs",
                "status": "pass" if not leftover else "fail",
                "cst_pid": cst_pid,
                "cst_survived_whole_suite": cst_pid in pids_at_end,
                "leftover_dialogs": leftover,
            }
        )

    report = {
        "generated_at_unix": time.time(),
        "quiet_mode": True,
        "known_rules": [
            {"rule_id": r.rule_id, "action": r.action} for r in KNOWN_RULES
        ],
        "scenarios": results,
        "all_passed": all(
            r.get("status") in {"pass", "observed", "skipped"} for r in results
        ),
    }
    (output / "verification-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
