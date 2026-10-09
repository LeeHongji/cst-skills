"""Build an ``attempt.json`` from a geometry IR.

Generated rather than hand-written because three of its fields must agree exactly
with the IR: ``topology_hash``, ``model_intent_id``, and the audited parameter
values.  A hand-transcribed hash that is one character wrong would refuse every
iteration with a topology mismatch, and a hand-transcribed baseline would make the
approved ranges centre on a value that was never audited.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "MCP" / "CST-CAD" / "src"))
sys.path.insert(0, str(REPO_ROOT / "MCP" / "CST-Lab" / "src"))

from cst_cad import ir  # noqa: E402
from cst_lab.contracts import default_ranges, write_attempt  # noqa: E402

#: Provenance values that represent an interpretation a human has to accept.
REVIEWABLE = ("assumption", "strong_inference")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ir", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--design-id", required=True)
    parser.add_argument("--topic-id", required=True)
    parser.add_argument("--max-iterations", type=int, required=True)
    parser.add_argument(
        "--range-fraction",
        type=float,
        default=0.20,
        help="half-width of each approved range as a fraction of the audited value",
    )
    parser.add_argument("--notes", default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    document = json.loads(args.ir.read_text(encoding="utf-8"))
    parameters = document["parameters"]

    baseline = {p["name"]: float(p["value"]) for p in parameters if isinstance(p["value"], (int, float))}
    # Only parameters the model marks tunable get a range.  Everything else is
    # refused by check_parameters, which is the behaviour we want: a derived
    # coordinate must be recomputed by model.py, never set directly.
    tunable = [p["name"] for p in parameters if p.get("tunable")]

    attempt = {
        "schema_version": 1,
        "attempt_id": args.attempt_id,
        "design_id": args.design_id,
        "topic_id": args.topic_id,
        "topology_hash": ir.topology_hash(document),
        "model_intent_id": ir.model_intent_id(document),
        "baseline_parameters": baseline,
        "approved_ranges": default_ranges(baseline, fraction=args.range_fraction, only=tunable),
        "assumptions": [
            {
                "parameter": p["name"],
                "provenance": p["provenance"],
                "statement": p.get("description") or p.get("source") or "no statement recorded",
            }
            for p in sorted(parameters, key=lambda p: (p["provenance"], p["name"]))
            if p["provenance"] in REVIEWABLE
        ],
        "max_iterations": args.max_iterations,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "awaiting_approval",
    }
    if args.notes:
        attempt["notes"] = args.notes

    written = write_attempt(args.output, attempt)
    print(
        json.dumps(
            {
                "written": str(written),
                "topology_hash": attempt["topology_hash"],
                "approved_parameters": sorted(attempt["approved_ranges"]),
                "baseline_count": len(baseline),
                "assumption_count": len(attempt["assumptions"]),
                "status": attempt["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
