"""Compare the geometry IR against what CST actually built.

The IR says what the model should be; a saved ``.cst`` says what CST made of
it. This module reduces both to the same shape - a set of named entities with
bounding boxes, plus a parameter table - and reports the differences. It is the
correctness proof for the code generator and the data source for the Phase 2
"intent versus CST actual" panel.

Observations arrive as JSON so this module never imports CST. Two producers are
supported: the vendored runtime CLI ``inspect-project`` (entity names and
parameters, no bounding boxes) and ``tools/cst_observe.py`` (adds bounding
boxes read through the CST VBA API).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import emit_vba, ir

REPORT_SCHEMA_VERSION = 1

#: Bounding box agreement threshold in model length units. CST reports the
#: loose bounding box, which is exact for planar bricks; 1e-6 mm is far below
#: any meshable feature while still catching a genuine code-generation slip.
DEFAULT_TOLERANCE = 1e-6


def sanitize_name(name: str) -> str:
    """Trim the trailing buffer garbage CST/runtime-CLI can append to names.

    Observed on this machine: the final entity returned by ``inspect-project``
    carries several kilobytes of uninitialised memory after a NUL, which would
    otherwise make an exact name comparison fail for the last solid only.
    """
    text = str(name)
    for index, character in enumerate(text):
        if character == "\x00" or (ord(character) < 32 and character not in "\t") or ord(character) == 0xFFFD:
            return text[:index].strip()
    return text.strip()


def normalize_observation(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept either runtime-CLI or cst_observe output and normalize it."""
    entities: list[dict[str, Any]] = []
    for entity in raw.get("entities", []) or []:
        if isinstance(entity, str):
            component, _, name = entity.partition(":")
        else:
            component = sanitize_name(entity.get("component", ""))
            name = sanitize_name(entity.get("name", ""))
        component = sanitize_name(component)
        name = sanitize_name(name)
        if not name:
            continue
        record: dict[str, Any] = {
            "component": component,
            "name": name,
            "full_name": f"{component}:{name}" if component else name,
        }
        box = entity.get("bounding_box") if isinstance(entity, dict) else None
        if box:
            record["bounding_box"] = {key: float(box[key]) for key in ("x0", "y0", "z0", "x1", "y1", "z1")}
        if isinstance(entity, dict) and entity.get("material"):
            record["material"] = sanitize_name(entity["material"])
        entities.append(record)

    parameters: dict[str, float] = {}
    for name, value in (raw.get("parameters") or {}).items():
        numeric = value.get("value") if isinstance(value, dict) else value
        try:
            parameters[sanitize_name(name)] = float(numeric)
        except (TypeError, ValueError):
            continue

    return {
        "project_path": raw.get("project_path"),
        "entities": sorted(entities, key=lambda item: item["full_name"]),
        "parameters": parameters,
        "solver_info": raw.get("solver_info"),
        "producer": raw.get("producer", "runtime-cli inspect-project"),
    }


def read_observation(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return normalize_observation(raw)


def _box_delta(expected: dict[str, float] | None, actual: dict[str, float] | None) -> float | None:
    if not expected or not actual:
        return None
    return max(abs(float(expected[key]) - float(actual[key])) for key in ("x0", "y0", "z0", "x1", "y1", "z1"))


def compare(
    document: dict[str, Any],
    observation: dict[str, Any],
    tolerance: float = DEFAULT_TOLERANCE,
    name_map: dict[str, str] | None = None,
    check_parameters: bool = True,
) -> dict[str, Any]:
    """Compare IR expectations against a CST observation."""
    mapping = name_map or {}
    expected_entities = emit_vba.expected_entities(document)
    actual_by_name = {entity["full_name"]: entity for entity in observation.get("entities", [])}
    matched_actual: set[str] = set()

    entity_rows: list[dict[str, Any]] = []
    for expected in expected_entities:
        target = mapping.get(expected["full_name"], expected["full_name"])
        actual = actual_by_name.get(target)
        row: dict[str, Any] = {
            "net": expected["net"],
            "expected_full_name": expected["full_name"],
            "compared_against": target,
            "expected_bounding_box": expected["bounding_box"],
            "primitive_count": expected["primitive_count"],
        }
        if actual is None:
            row.update(status="missing", actual_full_name=None, actual_bounding_box=None, max_abs_delta=None)
        else:
            matched_actual.add(target)
            delta = _box_delta(expected["bounding_box"], actual.get("bounding_box"))
            row.update(
                actual_full_name=actual["full_name"],
                actual_bounding_box=actual.get("bounding_box"),
                max_abs_delta=delta,
            )
            if delta is None:
                row["status"] = "name_only_match"
            else:
                row["status"] = "match" if delta <= tolerance else "bounding_box_mismatch"
        entity_rows.append(row)

    for name, actual in sorted(actual_by_name.items()):
        if name in matched_actual:
            continue
        entity_rows.append(
            {
                "net": None,
                "expected_full_name": None,
                "compared_against": name,
                "actual_full_name": name,
                "expected_bounding_box": None,
                "actual_bounding_box": actual.get("bounding_box"),
                "max_abs_delta": None,
                "status": "unexpected",
            }
        )

    parameter_rows: list[dict[str, Any]] = []
    if check_parameters:
        actual_parameters = observation.get("parameters", {})
        for parameter in sorted(document.get("parameters", []), key=lambda item: str(item["name"])):
            name = parameter["name"]
            actual_value = actual_parameters.get(name)
            row = {
                "name": name,
                "expected": float(parameter["value"]),
                "actual": actual_value,
                "provenance": parameter.get("provenance"),
            }
            if actual_value is None:
                row["status"] = "missing"
                row["delta"] = None
            else:
                delta = abs(float(parameter["value"]) - float(actual_value))
                row["delta"] = delta
                row["status"] = "match" if delta <= max(tolerance, 1e-9) else "mismatch"
            parameter_rows.append(row)

    entity_failures = [row for row in entity_rows if row["status"] in {"missing", "unexpected", "bounding_box_mismatch"}]
    parameter_failures = [row for row in parameter_rows if row["status"] != "match"]

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "model_intent_id": document.get("model_intent_id"),
        "model_id": document.get("model_id"),
        "project_path": observation.get("project_path"),
        "producer": observation.get("producer"),
        "tolerance": tolerance,
        "status": "match" if not entity_failures and not parameter_failures else "mismatch",
        "summary": {
            "entities_expected": len(expected_entities),
            "entities_observed": len(actual_by_name),
            "entities_matched": sum(1 for row in entity_rows if row["status"] in {"match", "name_only_match"}),
            "entities_missing": sum(1 for row in entity_rows if row["status"] == "missing"),
            "entities_unexpected": sum(1 for row in entity_rows if row["status"] == "unexpected"),
            "entities_bounding_box_mismatch": sum(1 for row in entity_rows if row["status"] == "bounding_box_mismatch"),
            "parameters_checked": len(parameter_rows),
            "parameters_mismatched": len(parameter_failures),
            "max_bounding_box_delta": max(
                (row["max_abs_delta"] for row in entity_rows if row.get("max_abs_delta") is not None),
                default=None,
            ),
        },
        "entities": entity_rows,
        "parameters": parameter_rows,
    }


def render_table(report: dict[str, Any]) -> str:
    """Render the entity comparison as a fixed-width table for review."""
    header = ("net", "expected entity", "observed entity", "status", "max |delta|")
    rows = [
        (
            str(row.get("net") or "-"),
            str(row.get("expected_full_name") or "-"),
            str(row.get("actual_full_name") or "-"),
            str(row["status"]),
            "-" if row.get("max_abs_delta") is None else f"{row['max_abs_delta']:.3e}",
        )
        for row in report.get("entities", [])
    ]
    widths = [max(len(header[i]), *(len(row[i]) for row in rows)) if rows else len(header[i]) for i in range(5)]
    lines = [" | ".join(header[i].ljust(widths[i]) for i in range(5))]
    lines.append("-+-".join("-" * widths[i] for i in range(5)))
    for row in rows:
        lines.append(" | ".join(row[i].ljust(widths[i]) for i in range(5)))
    return "\n".join(lines)
