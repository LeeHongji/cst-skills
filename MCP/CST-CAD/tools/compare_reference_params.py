"""Read-only comparison of the generated IR against the reference project history.

Every difference is classified so that a paper-interpretation choice is never
mistaken for a code-generation defect.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cst_cad import ir  # noqa: E402

PARAM = re.compile(r'MakeSureParameterExists\s+"([^"]+)"\s*,\s*"([^"]*)"')

# Parameters the reference declares that the new IR deliberately does not carry as
# geometry identity, with the reason. These are analysis setup or unused material
# data, not shape intent.
EXPECTED_ABSENT = {
    "fmin": "analysis setup: lives in simulation.frequency, excluded from model_intent_id",
    "f0": "analysis setup: lives in simulation.frequency, excluded from model_intent_id",
    "fmax": "analysis setup: lives in simulation.frequency, excluded from model_intent_id",
    "sigma_cu": "material property: carried on the material record, not as a CST parameter",
    "tanD_sub": "material property: carried on the material record, not as a CST parameter",
    "er_sub": "material property: carried on the material record, not as a CST parameter",
}

# The reference hand-wrote one global per shared resonator dimension. The IR builds
# each resonator from the same parameterised helper, so the equivalent quantity is
# named per resonator. Each entry is checked numerically, not assumed.
RENAMED = {
    "pad_y0": ["r1_pad_y0", "r2_pad_y0"],
    "pad_y1": ["r1_pad_y1", "r2_pad_y1"],
    "leg_y0": ["r1_leg_y0", "r2_leg_y0"],
    "top_inner_y": ["r1_top_inner_y", "r2_top_inner_y"],
}

# The reference named both pad edges; the IR names the left edge and carries the
# right edge as an expression on the solid. Checked as a derived quantity.
DERIVED_IN_IR = {
    "r1_pad_x1": ("r1_pad_x0", "r1_pad_w"),
    "r2_pad_x1": ("r2_pad_x0", "r2_pad_w"),
}


def main() -> int:
    history_path = Path(sys.argv[1])
    ir_path = Path(sys.argv[2])
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    reference: dict[str, str] = {}
    for name, expression in PARAM.findall(history_path.read_text(encoding="utf-8")):
        reference[name] = expression

    document = ir.read(ir_path)
    generated = {item["name"]: item for item in document["parameters"]}

    def evaluate(expression: str, table: dict[str, str], cache: dict[str, float]) -> float:
        if expression in cache:
            return cache[expression]
        text = expression.replace("^", "**")
        names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
        scope = {name: evaluate(table[name], table, cache) for name in names if name in table}
        value = float(eval(text, {"__builtins__": {}}, scope))  # noqa: S307 - history text is local evidence
        cache[expression] = value
        return value

    cache: dict[str, float] = {}
    same_value: list[dict] = []
    different_value: list[dict] = []
    only_reference: list[dict] = []
    only_generated: list[dict] = []

    for name, expression in sorted(reference.items()):
        try:
            reference_value = evaluate(expression, reference, cache)
        except Exception as exc:  # pragma: no cover - defensive
            reference_value = float("nan")
            print(f"could not evaluate {name}={expression}: {exc}", file=sys.stderr)
        if name not in generated:
            entry = {
                "name": name,
                "reference_expression": expression,
                "reference_value": reference_value,
                "classification": "intentional-omission",
                "reason": EXPECTED_ABSENT.get(name, "UNEXPLAINED - investigate"),
            }
            if name in RENAMED:
                counterparts = {
                    other: float(generated[other]["value"]) for other in RENAMED[name] if other in generated
                }
                agree = len(counterparts) == len(RENAMED[name]) and all(
                    abs(value - reference_value) <= 1e-9 for value in counterparts.values()
                )
                entry["classification"] = "renamed-per-resonator"
                entry["counterparts"] = counterparts
                entry["reason"] = (
                    f"one shared global in the reference, one per resonator in the IR; "
                    f"all counterparts equal {reference_value:g}"
                    if agree
                    else "UNEXPLAINED - renamed counterparts do not agree numerically"
                )
            elif name in DERIVED_IN_IR:
                base, span = DERIVED_IN_IR[name]
                if base in generated and span in generated:
                    value = float(generated[base]["value"]) + float(generated[span]["value"])
                    entry["classification"] = "derived-in-ir"
                    entry["derived_from"] = f"{base}+{span}"
                    entry["derived_value"] = value
                    entry["reason"] = (
                        f"not a named IR parameter; carried as {base}+{span} = {value:g} on the solid"
                        if abs(value - reference_value) <= 1e-9
                        else "UNEXPLAINED - derived counterpart does not agree numerically"
                    )
            only_reference.append(entry)
            continue
        value = float(generated[name]["value"])
        record = {
            "name": name,
            "reference_expression": expression,
            "reference_value": reference_value,
            "generated_expression": generated[name].get("expression"),
            "generated_value": value,
            "delta": value - reference_value,
            "provenance": generated[name]["provenance"],
        }
        if abs(value - reference_value) <= 1e-9:
            same_value.append(record)
        else:
            different_value.append(record)

    for name, item in sorted(generated.items()):
        if name not in reference:
            only_generated.append(
                {
                    "name": name,
                    "generated_expression": item.get("expression"),
                    "generated_value": item["value"],
                    "provenance": item["provenance"],
                    "classification": "new-in-ir",
                }
            )

    unexplained = [item for item in only_reference if item["reason"].startswith("UNEXPLAINED")]
    report = {
        "reference_history": str(history_path.resolve()),
        "geometry_ir": str(ir_path.resolve()),
        "model_intent_id": document["model_intent_id"],
        "summary": {
            "reference_parameters": len(reference),
            "generated_parameters": len(generated),
            "matching_value": len(same_value),
            "differing_value": len(different_value),
            "only_in_reference": len(only_reference),
            "only_in_ir": len(only_generated),
            "unexplained_omissions": len(unexplained),
        },
        "verdict": (
            "no code-generation defect: every shared parameter agrees to 1e-9 and every "
            "omission is an explained identity/analysis split"
            if not different_value and not unexplained
            else "differences require classification"
        ),
        "differing_value": different_value,
        "only_in_reference": only_reference,
        "only_in_ir": only_generated,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("summary", "verdict", "differing_value")}, ensure_ascii=False, indent=2))
    print(f"\nonly in reference ({len(only_reference)}):")
    for item in only_reference:
        print(f"  {item['name']:<16} = {item['reference_value']:<10.6g} [{item['classification']}] {item['reason']}")
    print(f"\nonly in IR ({len(only_generated)}): {', '.join(item['name'] for item in only_generated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
