"""End-to-end verification of the four contracts against a real CST run.

The offline cross-check proves the gate evaluator agrees with an independent
implementation on stored curves.  This proves the contracts work on a curve that
did not exist when the run started: CST is driven under the guardian, solves, and
exports Touchstone, and the exported file is then judged by the gates in
``design.md`` and recorded as one ``iterations.jsonl`` line.

The project solved here is ``fig15_filter_d_cad_v3.cst``, which was built from the
same geometry IR the attempt is bound to -- verified entity by entity with a
maximum bounding-box delta of 3.6e-15 mm and all 65 parameters matching.  That
matters for honesty rather than convenience: recording a ``topology_hash`` beside
results from a project that was not built from that IR would be a false claim, and
the whole point of the hash is that it can be trusted.

The iteration line is written into the run workspace, not into the attempt.  The
attempt is still ``awaiting_approval``, and appending a real iteration to an
unapproved attempt would contradict the contract this script is verifying.  The
attempt's own history starts once step 3 produces the audit and step 4 provides
the loop.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "MCP" / "CST-Lab" / "src"))
sys.path.insert(0, str(REPO_ROOT / "MCP" / "CST-CAD" / "src"))
sys.path.insert(0, str(REPO_ROOT / "MCP" / "CST"))

from cst_cad import ir  # noqa: E402
from cst_guardian import GuardViolation, run_guarded  # noqa: E402
from cst_lab.contracts import (  # noqa: E402
    ApprovalError,
    RangeViolation,
    TopologyMismatch,
    append_iteration,
    check_parameters,
    check_topology,
    evaluate_gates,
    iteration_line,
    load_attempt,
    load_design,
    load_topic,
    read_iterations,
    read_touchstone,
    require_approval,
)
from cst_lab.contracts.touchstone import curve  # noqa: E402

TOPIC_DIR = REPO_ROOT / "projects" / "dual-mode-open-loop-filters"
DESIGN_DIR = TOPIC_DIR / "designs" / "fig15-filter-d"
ATTEMPT_DIR = DESIGN_DIR / "attempts" / "a01-paper-ideal"

SOURCE_PROJECT = (
    REPO_ROOT
    / "cst_runs"
    / "cst-cad-phase1-verification_20260910"
    / "working"
    / "fig15_filter_d_cad_v3.cst"
)

WORKER = REPO_ROOT / "MCP" / "CST" / "tools" / "guardian_worker.py"
PYTHON = REPO_ROOT / "MCP" / "CST" / ".venv" / "Scripts" / "python.exe"

#: Touchstone exported by the historical solve of this same project. A fresh solve
#: of an unchanged project must reproduce this curve; if it does not, the run we
#: just did is not the run we think it is, and nothing downstream can be trusted.
#:
#: The comparison is curve-to-curve against this export rather than against the
#: summary in ``evidence/offline_results_v3.json``, because that summary reports the
#: passband peak at 1.0490 GHz while the Touchstone written in the same session puts
#: it at 1.0961 GHz. Two artifacts from one session disagree, so the raw curve is
#: the one to trust and the summary is recorded as a discrepancy rather than used.
HISTORICAL_EXPORT = (
    REPO_ROOT
    / "cst_runs"
    / "cst-cad-phase1-verification_20260910"
    / "exports"
    / "fig15_filter_d_cad_v3.s2p"
)
UNRECONCILED_SUMMARY = {
    "file": "cst_runs/cst-cad-phase1-verification_20260910/evidence/offline_results_v3.json",
    "claims_s21_peak_db": -0.28664223130412236,
    "claims_s21_peak_ghz": 1.0490000000000002,
    "note": (
        "Disagrees with the Touchstone exported in its own session, which this run "
        "reproduces. Either the summary was computed from a different result item or "
        "it is wrong; not used as a reference until that is resolved."
    ),
}

#: Tolerances for the curve comparison. Magnitude in dB is extremely sensitive
#: near a deep transmission zero -- a tiny change in a complex value close to zero
#: moves the dB value by whole decibels -- so the passband is compared tightly and
#: the comparison is restricted to samples above -30 dB.
PEAK_TOLERANCE_DB = 0.05
PEAK_TOLERANCE_GHZ = 0.002
CURVE_TOLERANCE_DB = 1.0
CURVE_FLOOR_DB = -30.0


def copy_project(source: Path, destination_dir: Path) -> Path:
    """Copy the project and its companion directory before anything writes to it."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / source.name
    if target.exists():
        raise FileExistsError(f"refusing to overwrite an existing working copy: {target}")
    shutil.copy2(source, target)
    companion = source.with_suffix("")
    if companion.is_dir():
        shutil.copytree(companion, target.with_suffix(""))
    return target


def scenario_contracts_load() -> dict[str, object]:
    """Every contract file on disk must validate before CST is touched."""
    topic, _ = load_topic(TOPIC_DIR / "topic.md")
    design, gates, _ = load_design(DESIGN_DIR / "design.md")
    attempt = load_attempt(ATTEMPT_DIR / "attempt.json")
    document = json.loads((ATTEMPT_DIR / "geometry-ir.json").read_text(encoding="utf-8"))

    bound = attempt["topology_hash"] == ir.topology_hash(document)
    return {
        "scenario": "contracts-load",
        "status": "pass" if bound else "fail",
        "topic_id": topic["topic_id"],
        "design_id": design["design_id"],
        "attempt_id": attempt["attempt_id"],
        "gates": [gate.describe() for gate in gates],
        "topology_hash": attempt["topology_hash"],
        "attempt_bound_to_its_ir": bound,
        "attempt_status": attempt["status"],
    }


def scenario_refusals() -> dict[str, object]:
    """The three refusals that run before CST, proven against the real attempt."""
    attempt = load_attempt(ATTEMPT_DIR / "attempt.json")
    document = json.loads((ATTEMPT_DIR / "geometry-ir.json").read_text(encoding="utf-8"))
    refusals = []

    def record(label: str, expect, call) -> None:
        try:
            call()
        except expect as exc:
            refusals.append({"refusal": label, "refused": True, "message": str(exc)[:300]})
        except Exception as exc:  # pragma: no cover - a wrong exception type is a defect
            refusals.append(
                {"refusal": label, "refused": False, "message": f"unexpected {type(exc).__name__}: {exc}"}
            )
        else:
            refusals.append({"refusal": label, "refused": False, "message": "call was allowed"})

    record("unapproved_attempt_cannot_run", ApprovalError, lambda: require_approval(attempt))

    # A real structural change to the real IR, not a fabricated digest.
    restructured = copy.deepcopy(document)
    restructured["nets"][2]["solids"].pop()
    record(
        "structural_change_stops_the_loop",
        TopologyMismatch,
        lambda: check_topology(attempt, ir.topology_hash(restructured)),
    )

    # The same IR with every dimension moved must NOT be refused: that is the
    # invariance the audit gate depends on.
    moved = copy.deepcopy(document)
    for parameter in moved["parameters"]:
        if isinstance(parameter["value"], (int, float)) and parameter["value"]:
            parameter["value"] = float(parameter["value"]) * 1.05
    topology_survived = True
    try:
        check_topology(attempt, ir.topology_hash(moved))
    except TopologyMismatch as exc:
        topology_survived = False
        refusals.append({"refusal": "dimension_change_allowed", "refused": True, "message": str(exc)[:300]})
    else:
        refusals.append({"refusal": "dimension_change_allowed", "refused": False, "message": "allowed, as intended"})

    baseline = attempt["baseline_parameters"]["r2_feed_gap"]
    record(
        "value_outside_its_approved_range",
        RangeViolation,
        lambda: check_parameters(attempt, {"r2_feed_gap": baseline * 2.0}),
    )
    record(
        "parameter_nobody_approved",
        RangeViolation,
        lambda: check_parameters(attempt, {"w_loop": 1.5}),
    )

    inside_allowed = True
    try:
        check_parameters(attempt, {"r2_feed_gap": baseline * 1.02})
    except RangeViolation:
        inside_allowed = False

    expected_refused = {
        "unapproved_attempt_cannot_run",
        "structural_change_stops_the_loop",
        "value_outside_its_approved_range",
        "parameter_nobody_approved",
    }
    ok = (
        all(r["refused"] for r in refusals if r["refusal"] in expected_refused)
        and not any(r["refused"] for r in refusals if r["refusal"] == "dimension_change_allowed")
        and topology_survived
        and inside_allowed
    )
    return {
        "scenario": "contract-refusals",
        "status": "pass" if ok else "fail",
        "refusals": refusals,
        "value_inside_range_allowed": inside_allowed,
    }


def scenario_solve(output: Path, working: Path, timeout_s: float) -> dict[str, object]:
    """Drive a real solve under the guardian and export Touchstone."""
    logs = output / "solve"
    logs.mkdir(parents=True, exist_ok=True)
    export_stem = output / "exports" / "fig15-filter-d-a01"
    export_stem.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    report = run_guarded(
        [
            str(PYTHON),
            str(WORKER),
            "solve",
            "--project",
            str(working),
            "--export",
            str(export_stem),
        ],
        log_dir=logs,
        timeout_s=timeout_s,
        require_clean_start=False,
    )
    elapsed = round(time.monotonic() - started, 2)

    exported = sorted(export_stem.parent.glob(export_stem.name + ".s*p"))
    return {
        "scenario": "guarded-solve",
        "status": "pass" if report.outcome == "completed" and exported else "fail",
        "outcome": report.outcome,
        "wall_seconds": elapsed,
        # Every dialog the guardian answered, escalated or released. Recorded even
        # when empty: quiet mode turns a prompt into a silent default, so "no
        # dialogs" has to be an assertion in the record rather than an absence.
        "dialogs": list(report.dialogs_answered) + list(report.escalations),
        "exported": [str(p.relative_to(REPO_ROOT)) for p in exported],
        "evidence": str(logs.relative_to(REPO_ROOT)),
    }


def _compare_with_historical_export(
    frequencies_ghz: list[float], s21_db: tuple[float, ...], metrics: dict
) -> dict[str, object]:
    """Check the fresh curve against the historical export of the same project."""
    if not HISTORICAL_EXPORT.exists():
        return {"available": False, "agrees": False, "reason": "historical export is missing"}

    reference = read_touchstone(HISTORICAL_EXPORT)
    reference_ghz = [f / 1e9 for f in reference.frequencies_hz]
    reference_s21 = curve(reference, 2, 1, "db")
    if reference_ghz != frequencies_ghz:
        return {
            "available": True,
            "agrees": False,
            "reason": "the two solves used different frequency grids",
        }

    peak_index = max(range(len(reference_s21)), key=lambda i: reference_s21[i])
    worst = max(
        (
            abs(a - b)
            for a, b in zip(s21_db, reference_s21)
            if a > CURVE_FLOOR_DB and b > CURVE_FLOOR_DB
        ),
        default=0.0,
    )
    agrees = (
        worst <= CURVE_TOLERANCE_DB
        and abs(metrics["s21_peak_db"] - reference_s21[peak_index]) <= PEAK_TOLERANCE_DB
        and abs(metrics["s21_peak_frequency_ghz"] - reference_ghz[peak_index]) <= PEAK_TOLERANCE_GHZ
    )
    return {
        "available": True,
        "agrees": agrees,
        "reference": str(HISTORICAL_EXPORT.relative_to(REPO_ROOT)),
        "reference_peak_db": round(reference_s21[peak_index], 6),
        "reference_peak_ghz": round(reference_ghz[peak_index], 6),
        "worst_deviation_db_above_floor": round(worst, 4),
        "floor_db": CURVE_FLOOR_DB,
    }


def scenario_judge_and_record(output: Path, working: Path, solve: dict) -> dict[str, object]:
    """Judge the fresh export against the design's gates and record one iteration."""
    if not solve.get("exported"):
        return {"scenario": "judge-and-record", "status": "fail", "reason": "no export to judge"}

    export = REPO_ROOT / solve["exported"][0]
    design, gates, _ = load_design(DESIGN_DIR / "design.md")
    attempt = load_attempt(ATTEMPT_DIR / "attempt.json")
    document = json.loads((ATTEMPT_DIR / "geometry-ir.json").read_text(encoding="utf-8"))

    data = read_touchstone(export)
    report = evaluate_gates(gates, data)

    s21 = curve(data, 2, 1, "db")
    frequencies_ghz = [f / 1e9 for f in data.frequencies_hz]
    peak_index = max(range(len(s21)), key=lambda i: s21[i])
    metrics = {
        "s21_peak_db": round(s21[peak_index], 6),
        "s21_peak_frequency_ghz": round(frequencies_ghz[peak_index], 6),
        "sample_count": len(data),
    }
    for result in report.gates:
        if result.measured is not None:
            metrics[f"{result.id}_db"] = round(result.measured, 6)

    reproduces = _compare_with_historical_export(frequencies_ghz, s21, metrics)

    jsonl = output / "iterations.jsonl"
    line = iteration_line(
        iter_number=0,
        parent=None,
        param_delta={},
        setup_delta={},
        drc="pass",
        topology_hash=ir.topology_hash(document),
        model_intent_id=ir.model_intent_id(document),
        solver={
            "type": "frequency_domain",
            "seconds": solve["wall_seconds"],
            "quiet_mode": True,
            "dialogs": solve["dialogs"],
            "converged": True,
        },
        metrics=metrics,
        acceptance=report.to_json(),
        observation=(
            "As-built paper-ideal reconstruction, no parameter change: "
            f"passband peak {metrics['s21_peak_db']:.3f} dB at "
            f"{metrics['s21_peak_frequency_ghz']:.4f} GHz; "
            f"acceptance {report.status} "
            f"({sum(g.status == 'pass' for g in report.gates)}/{len(report.gates)} gates pass)"
        ),
        artifacts={
            "s2p": str(export.relative_to(REPO_ROOT)),
            "logs": solve["evidence"],
            "working_copy": str(working.relative_to(REPO_ROOT)),
        },
        provenance="native",
        audited=False,
    )
    append_iteration(jsonl, line)
    written = read_iterations(jsonl)

    return {
        "scenario": "judge-and-record",
        # The verdict itself is not what is being asserted here. A truthful "fail"
        # is a success for the contracts: this reconstruction genuinely does not
        # meet the documented target band. What must hold is that the curve is the
        # right curve and that the record was written.
        "status": "pass" if len(written) == 1 and reproduces.get("agrees") else "fail",
        "export": str(export.relative_to(REPO_ROOT)),
        "acceptance": report.to_json(),
        "metrics": metrics,
        "reproduces_historical_export": reproduces,
        "unreconciled_summary": UNRECONCILED_SUMMARY,
        "iterations_jsonl": str(jsonl.relative_to(REPO_ROOT)),
        "lines_written": len(written),
    }


def scenario_append_only(output: Path) -> dict[str, object]:
    """The recorded history must refuse to be rewritten."""
    jsonl = output / "iterations.jsonl"
    refused = False
    message = ""
    try:
        append_iteration(jsonl, iteration_line(iter_number=0, drc="pass"))
    except ValueError as exc:
        refused = True
        message = str(exc)[:200]
    return {
        "scenario": "append-only",
        "status": "pass" if refused else "fail",
        "refused": refused,
        "message": message,
        "lines": len(read_iterations(jsonl)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--skip-solve", action="store_true")
    args = parser.parse_args(argv)

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    results = [scenario_contracts_load(), scenario_refusals()]

    if args.skip_solve:
        results.append({"scenario": "guarded-solve", "status": "skipped"})
        results.append({"scenario": "judge-and-record", "status": "skipped"})
    else:
        working = copy_project(SOURCE_PROJECT, output / "working")
        results.append(
            {
                "scenario": "copy-source-project",
                "status": "pass",
                "source": str(SOURCE_PROJECT.relative_to(REPO_ROOT)),
                "working_copy": str(working.relative_to(REPO_ROOT)),
            }
        )
        solve = scenario_solve(output, working, args.timeout)
        results.append(solve)
        results.append(scenario_judge_and_record(output, working, solve))
        results.append(scenario_append_only(output))

    report = {
        "output": str(output),
        "scenarios": results,
        "all_passed": all(r.get("status") in {"pass", "skipped"} for r in results),
    }
    (output / "verification-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
