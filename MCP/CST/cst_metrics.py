from __future__ import annotations

import cmath
import math
import re
from statistics import mean, median
from typing import Any


FREQUENCY_SCALE = {
    "Hz": 1.0,
    "kHz": 1e3,
    "MHz": 1e6,
    "GHz": 1e9,
    "THz": 1e12,
}


def _complex(value: Any) -> complex:
    if isinstance(value, complex):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return complex(float(value), 0.0)
    if isinstance(value, dict) and set(value) >= {"real", "imag"}:
        return complex(float(value["real"]), float(value["imag"]))
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return complex(float(value[0]), float(value[1]))
    if isinstance(value, str):
        cleaned = value.strip().replace("i", "j")
        return complex(cleaned)
    raise ValueError(f"Unsupported complex value: {value!r}")


def _unit_from_label(label: str | None) -> str | None:
    if not label:
        return None
    for unit in FREQUENCY_SCALE:
        if re.search(rf"(?<![A-Za-z]){re.escape(unit)}(?![A-Za-z])", label, re.IGNORECASE):
            return unit
    return None


def _representation(value: complex, name: str) -> float:
    if name == "real":
        return value.real
    if name == "imaginary":
        return value.imag
    if name == "magnitude":
        return abs(value)
    if name == "power":
        return abs(value) ** 2
    if name == "phase_deg":
        return math.degrees(cmath.phase(value))
    if name == "db20":
        magnitude = abs(value)
        return -math.inf if magnitude == 0 else 20.0 * math.log10(magnitude)
    if name == "db10":
        power = abs(value) ** 2
        return -math.inf if power == 0 else 10.0 * math.log10(power)
    raise ValueError(f"Unsupported scalar representation: {name}")


def normalize_1d_result(
    result: dict[str, Any], representation: str = "complex", x_unit: str | None = None
) -> dict[str, Any]:
    rows = result.get("data")
    if not isinstance(rows, list):
        raise ValueError("CST 1D result must contain a data array")
    source_unit = x_unit or _unit_from_label(result.get("xlabel"))
    points: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        try:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                raise ValueError("expected [x, y]")
            x = float(row[0])
            y = _complex(row[1])
            if not math.isfinite(x) or not math.isfinite(y.real) or not math.isfinite(y.imag):
                raise ValueError("non-finite source value")
            point: dict[str, Any] = {
                "x": x,
                "real": y.real,
                "imag": y.imag,
                "magnitude": abs(y),
            }
            if representation != "complex":
                scalar = _representation(y, representation)
                point["value"] = None if not math.isfinite(scalar) else scalar
                if scalar == -math.inf:
                    point["special_value"] = "-Infinity"
            points.append(point)
        except (TypeError, ValueError, OverflowError) as exc:
            invalid.append({"index": index, "reason": str(exc)})
    return {
        "status": "valid" if points and not invalid else ("partial" if points else "invalid"),
        "tree_path": result.get("tree_path"),
        "title": result.get("title"),
        "x_label": result.get("xlabel"),
        "y_label": result.get("ylabel"),
        "x_unit": source_unit,
        "representation": representation,
        "source_point_count": len(rows),
        "valid_point_count": len(points),
        "invalid_points": invalid,
        "truncated": bool(result.get("truncated")),
        "points": points,
    }


def evaluate_metric(result: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    required = {
        "name",
        "signal",
        "representation",
        "unit",
        "domain",
        "aggregation",
        "direction",
        "missing_data_policy",
        "quality_gates",
    }
    missing = sorted(required - set(definition))
    if missing:
        return {"status": "invalid", "error": f"Metric definition missing: {missing}"}
    representation = definition["representation"]
    if representation == "complex":
        return {"status": "invalid", "error": "Complex data requires a scalar representation before aggregation"}
    window = definition.get("frequency_window")
    expected_unit = window.get("unit") if window else None
    normalized = normalize_1d_result(result, representation=representation)
    if normalized["truncated"]:
        return {"status": "invalid", "error": "Source result is truncated", "evidence": normalized}
    if normalized["status"] != "valid":
        return {"status": "invalid", "error": "Source result contains missing or invalid points", "evidence": normalized}
    source_unit = normalized["x_unit"]
    points = normalized["points"]
    if window:
        if source_unit is None:
            return {"status": "invalid", "error": "Frequency unit is unknown; provide it in the CST x-axis label"}
        if source_unit not in FREQUENCY_SCALE or expected_unit not in FREQUENCY_SCALE:
            return {"status": "invalid", "error": f"Unsupported frequency unit conversion: {source_unit} -> {expected_unit}"}
        factor = FREQUENCY_SCALE[source_unit] / FREQUENCY_SCALE[expected_unit]
        converted = [{**point, "window_x": point["x"] * factor} for point in points]
        start, stop = float(window["start"]), float(window["stop"])
        if start >= stop:
            return {"status": "invalid", "error": "frequency_window.start must be less than stop"}
        xs = [point["window_x"] for point in converted]
        tolerance = float(
            definition.get(
                "coverage_tolerance",
                1e-6 * max(1.0, abs(start), abs(stop), abs(stop - start)),
            )
        )
        if min(xs) > start + tolerance or max(xs) < stop - tolerance:
            return {
                "status": "invalid",
                "error": "Frequency window is not fully covered by source data",
                "coverage": {"data_start": min(xs), "data_stop": max(xs), "requested_start": start, "requested_stop": stop, "tolerance": tolerance, "unit": expected_unit},
            }
        selected = [
            point for point in converted
            if start - tolerance <= point["window_x"] <= stop + tolerance
        ]
    else:
        selected = points
    if not selected:
        return {"status": "invalid", "error": "No source points satisfy the metric domain"}
    scalar_values: list[float] = []
    negative_infinity = False
    for point in selected:
        if point.get("special_value") == "-Infinity":
            negative_infinity = True
            scalar_values.append(-math.inf)
        elif point.get("value") is not None:
            scalar_values.append(float(point["value"]))
    if not scalar_values:
        return {"status": "invalid", "error": "No scalar values are available"}
    aggregation = definition["aggregation"]
    if aggregation == "min":
        value = min(scalar_values)
    elif aggregation == "max":
        value = max(scalar_values)
    elif aggregation == "mean":
        if negative_infinity:
            return {"status": "invalid", "error": "Mean is undefined with exact zero magnitude in logarithmic representation"}
        value = mean(scalar_values)
    elif aggregation == "median":
        value = median(scalar_values)
    elif aggregation == "ripple":
        value = max(scalar_values) - min(scalar_values)
    elif aggregation == "at":
        target = definition.get("target_x")
        if target is None:
            return {"status": "invalid", "error": "aggregation 'at' requires target_x"}
        coordinate = "window_x" if window else "x"
        point = min(selected, key=lambda candidate: abs(candidate[coordinate] - float(target)))
        value = -math.inf if point.get("special_value") == "-Infinity" else point["value"]
    elif aggregation in {"argmin_x", "argmax_x"}:
        coordinate = "window_x" if window else "x"
        chooser = min if aggregation == "argmin_x" else max
        point = chooser(
            selected,
            key=lambda candidate: -math.inf
            if candidate.get("special_value") == "-Infinity"
            else float(candidate["value"]),
        )
        value = float(point[coordinate])
    else:
        return {"status": "invalid", "error": f"Unsupported aggregation: {aggregation}"}
    if not math.isfinite(value):
        value_payload: float | str = "-Infinity" if value == -math.inf else str(value)
    else:
        value_payload = value
    return {
        "status": "valid",
        "metric": definition["name"],
        "value": value_payload,
        "unit": definition["unit"],
        "representation": representation,
        "aggregation": aggregation,
        "point_count": len(selected),
        "source": {
            "tree_path": normalized["tree_path"],
            "x_unit": source_unit,
            "x_label": normalized["x_label"],
            "y_label": normalized["y_label"],
        },
    }
