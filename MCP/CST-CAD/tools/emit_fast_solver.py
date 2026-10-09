"""Emit a budget-controlled solver override from an existing geometry IR.

The IR's ``simulation`` section is deliberately outside ``model_intent_id``, so
re-running the same geometry at a cheaper accuracy setting is a pure analysis
change and does not fork the model identity. This script exercises that
property: it rewrites only mesh adaption and solver accuracy, then emits the
two affected history blocks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cst_cad import emit_vba, ir  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ir_path")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-passes", type=int, default=5)
    parser.add_argument("--max-delta-s", type=float, default=0.01)
    parser.add_argument("--accuracy-rom", default="5e-5")
    parser.add_argument("--result-samples", type=int, default=401)
    parser.add_argument("--drop-monitors", action="store_true")
    args = parser.parse_args()

    document = ir.read(args.ir_path)
    before = document["model_intent_id"]

    document["simulation"]["convergence"]["max_passes"] = args.max_passes
    document["simulation"]["convergence"]["max_delta_s"] = args.max_delta_s
    document["simulation"]["settings"]["accuracy_rom"] = args.accuracy_rom
    document["simulation"]["settings"]["result_samples"] = args.result_samples
    if args.drop_monitors:
        document["simulation"]["monitors"] = []

    after = ir.model_intent_id(document)

    target = Path(args.output_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / "91_solver_fast.vba"
    path.write_text(emit_vba._solver_block(document).rstrip() + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "model_intent_id_before": before,
                "model_intent_id_after": after,
                "identity_unchanged": before == after,
                "note": "only simulation.* changed, so the physical model identity must be unchanged",
                "written": [str(path)],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
