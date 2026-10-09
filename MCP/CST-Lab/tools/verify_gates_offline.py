"""Cross-check the automatic acceptance verdict against the historical judgement.

The gates in ``design.md`` are only worth having if they reproduce the verdict a
person reached by reading the same curve.  This script evaluates the real gates on
the real exported Touchstone files from the Fig. 15 coupling-feed sweep and
compares the numbers it measures against the numbers the historical analysis
script recorded for those same files.

Two independent implementations agreeing on real data is much stronger evidence
than the evaluator agreeing with a fixture it was written alongside.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "MCP" / "CST-Lab" / "src"))

from cst_lab.contracts import evaluate_gates, load_design, read_touchstone  # noqa: E402

DESIGN = (
    REPO_ROOT / "projects" / "dual-mode-open-loop-filters" / "designs" / "fig15-filter-d" / "design.md"
)

SWEEP = (
    REPO_ROOT
    / "cst_runs"
    / "fig15-four-pole-output-feed-gap-upper-extension-_20260831_fecba3395920"
    / "sweep-evidence"
)

#: What the historical analysis recorded for these exact exports, from
#: brain/raw/trace-snapshots/fig15-filter-d-coupling-feed-optimized-r2feed0200-20260831.
#: ``interior`` numbers are over 1.010-1.090 GHz, the window the gates use.
HISTORICAL = {
    "r2feed_0195": {"r2_feed_gap": 0.195, "interior_worst_s11_db": -7.921, "interior_s21_floor_db": -0.927},
    "r2feed_0200": {"r2_feed_gap": 0.200, "interior_worst_s11_db": -8.268, "interior_s21_floor_db": -0.875},
    "r2feed_0205": {"r2_feed_gap": 0.205, "interior_worst_s11_db": -7.810, "interior_s21_floor_db": -0.965},
}

#: The historical numbers are rounded to 3 decimals and were computed on exported
#: CSV rather than the Touchstone file, so exact equality is not expected. A
#: hundredth of a dB is far tighter than any threshold in the gates.
TOLERANCE_DB = 0.01


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    header, gates, _ = load_design(DESIGN)
    by_id = {gate.id: gate for gate in gates}

    cases = []
    disagreements = []
    for name, expected in HISTORICAL.items():
        path = SWEEP / name / f"{name}.s2p"
        if not path.exists():
            disagreements.append(f"{name}: export is missing at {path}")
            continue
        data = read_touchstone(path)
        report = evaluate_gates(gates, data)
        measured = {result.id: result for result in report.gates}

        checks = []
        for gate_id, key in (
            ("interior_return_loss", "interior_worst_s11_db"),
            ("interior_insertion_loss", "interior_s21_floor_db"),
        ):
            ours = measured[gate_id].measured
            theirs = expected[key]
            agree = ours is not None and abs(ours - theirs) <= TOLERANCE_DB
            checks.append(
                {
                    "gate": gate_id,
                    "ours_db": None if ours is None else round(ours, 4),
                    "historical_db": theirs,
                    "delta_db": None if ours is None else round(ours - theirs, 4),
                    "agrees": agree,
                }
            )
            if not agree:
                disagreements.append(
                    f"{name}/{gate_id}: we measure {ours}, history recorded {theirs}"
                )

        cases.append(
            {
                "export": str(path.relative_to(REPO_ROOT)),
                "r2_feed_gap": expected["r2_feed_gap"],
                "samples": len(data),
                "sweep_ghz": [data.frequencies_hz[0] / 1e9, data.frequencies_hz[-1] / 1e9],
                "acceptance": report.to_json(),
                "cross_checks": checks,
            }
        )

    # The gate must also discriminate: if every export got the same verdict the
    # comparison above would be satisfied by an evaluator that ignores its input.
    verdicts = {
        case["r2_feed_gap"]: next(
            g["status"] for g in case["acceptance"]["gates"] if g["id"] == "interior_return_loss"
        )
        for case in cases
    }
    if len(set(verdicts.values())) < 2:
        disagreements.append(
            f"interior_return_loss gave the same verdict for every export ({verdicts}); "
            "a gate that cannot separate the sweep proves nothing"
        )

    report = {
        "design": str(DESIGN.relative_to(REPO_ROOT)),
        "gates": [gate.describe() for gate in gates],
        "cases": cases,
        "interior_return_loss_verdicts": verdicts,
        "disagreements": disagreements,
        "status": "pass" if not disagreements else "fail",
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if not disagreements else 1


if __name__ == "__main__":
    raise SystemExit(main())
