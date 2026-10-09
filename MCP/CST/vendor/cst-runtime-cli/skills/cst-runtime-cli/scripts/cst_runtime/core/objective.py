from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


def _s11_from_export(run_output: dict) -> dict[str, Any] | None:
    """Parse S11 from pipeline_run_experiment output."""
    s11_metric = run_output.get("s11_metric")
    if s11_metric and isinstance(s11_metric, dict):
        return s11_metric
    s11_path = run_output.get("s11_export_path", "")
    if not s11_path or not Path(s11_path).is_file():
        return None
    try:
        payload = json.loads(Path(s11_path).read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    xdata = payload.get("xdata") or []
    ydata = payload.get("ydata") or []
    if not xdata or not ydata:
        return None
    db_values = []
    for item in ydata:
        if isinstance(item, dict):
            real, imag = float(item.get("real", 0.0)), float(item.get("imag", 0.0))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            real, imag = float(item[0]), float(item[1])
        elif isinstance(item, (int, float)):
            real, imag = float(item), 0.0
        else:
            real, imag = 0.0, 0.0
        mag = math.hypot(real, imag)
        db = 20.0 * math.log10(mag) if mag > 1e-15 else -300.0
        db_values.append(db)
    if not db_values:
        return None
    min_idx = db_values.index(min(db_values))
    return {
        "run_id": payload.get("run_id"),
        "min_db": min(db_values),
        "best_freq": xdata[min_idx] if min_idx < len(xdata) else None,
        "point_count": len(db_values),
        "all_db": db_values,
        "all_freq": xdata,
    }


def _s11_min_db(run_output: dict) -> dict[str, Any]:
    parsed = _s11_from_export(run_output)
    if parsed is None:
        return {"status": "invalid", "error": "no_s11_data"}
    return {"value": parsed["min_db"], "details": parsed}


def _s11_at_freq(run_output: dict, freq: float) -> dict[str, Any]:
    parsed = _s11_from_export(run_output)
    if parsed is None:
        return {"status": "invalid", "error": "no_s11_data"}
    all_freq = parsed.get("all_freq", [])
    all_db = parsed.get("all_db", [])
    if not all_freq or not all_db:
        # s11_from_export returned partial data (s11_metric from pipeline).
        # Try reading the raw S11 file to get full frequency sweep.
        s11_path = run_output.get("s11_export_path", "")
        if s11_path and Path(s11_path).is_file():
            try:
                payload = json.loads(Path(s11_path).read_text(encoding="utf-8-sig"))
                all_freq = payload.get("xdata", [])
                ydata = payload.get("ydata", [])
                all_db = [
                    20.0 * math.log10(max(math.hypot(
                        float(d["real"]), float(d["imag"])), 1e-15))
                    for d in ydata
                ] if ydata and isinstance(ydata[0], dict) else []
            except Exception:
                pass
        if not all_freq or not all_db:
            return {"status": "invalid", "error": "no_frequency_data"}
    idx = min(range(len(all_freq)), key=lambda i: abs(float(all_freq[i]) - freq))
    return {"value": all_db[idx], "details": {"at_freq": all_freq[idx], "source": "s11"}}


def _gain_max(run_output: dict) -> dict[str, Any]:
    farfield_files = run_output.get("farfield_exported", [])
    if not farfield_files:
        return {"status": "invalid", "error": "no_farfield_data"}
    best_gain = -1e9
    best_file = ""
    for fpath in farfield_files:
        fpath = str(fpath)
        m = re.search(r"_(\d+\.?\d*)dBi", fpath)
        if m:
            val = float(m.group(1))
            if val > best_gain:
                best_gain = val
                best_file = fpath
    if best_gain > -1e8:
        return {"value": best_gain, "details": {"source_file": str(best_file)}}
    return {"status": "invalid", "error": "unparseable_farfield_data"}


def _bandwidth(run_output: dict, below_db: float = -10.0) -> dict[str, Any]:
    parsed = _s11_from_export(run_output)
    if parsed is None:
        return {"status": "invalid", "error": "no_s11_data"}
    all_freq = parsed.get("all_freq", [])
    all_db = parsed.get("all_db", [])
    if not all_freq or not all_db:
        return {"status": "invalid", "error": "no_freq_data"}
    below = [f for f, d in zip(all_freq, all_db) if d <= below_db]
    if len(below) >= 2:
        return {
            "value": max(below) - min(below),
            "details": {"below_db": below_db, "passband_edges": [min(below), max(below)]},
        }
    return {"value": 0.0, "details": {"below_db": below_db, "note": "no passband found"}}


_REGISTRY = {
    "s11_min_db": {"fn": lambda r, **kw: _s11_min_db(r), "params": [], "direction": "minimize"},
    "s11_at_freq": {"fn": lambda r, **kw: _s11_at_freq(r, **kw), "params": ["freq"], "direction": "minimize"},
    "gain_max": {"fn": lambda r, **kw: _gain_max(r), "params": [], "direction": "maximize"},
    "bandwidth": {"fn": lambda r, **kw: _bandwidth(r, **kw), "params": ["below_db"], "direction": "maximize"},
}


def compute_objective(objective_spec: dict, run_output: dict) -> dict[str, Any]:
    obj_type = objective_spec.get("type", "s11_min_db")
    if obj_type == "expression":
        return _compute_expression(objective_spec.get("expr", ""), run_output)
    entry = _REGISTRY.get(obj_type)
    if entry is None:
        return {"status": "invalid", "error": f"unknown objective type: {obj_type}"}
    kwargs = {k: objective_spec.get(k) for k in entry["params"] if k in objective_spec}
    result = entry["fn"](run_output, **kwargs)
    result["type"] = obj_type
    result["direction"] = objective_spec.get("direction", entry["direction"])
    result.setdefault("status", "invalid" if result.get("error") else "valid")
    return result


def _compute_expression(expr: str, run_output: dict) -> dict[str, Any]:
    parsed = _s11_from_export(run_output)
    if parsed is None:
        return {"status": "invalid", "error": "no_s11_data", "type": "expression"}
    env = {
        "s11_db": parsed.get("all_db", []),
        "s11_freq": parsed.get("all_freq", []),
        "min": min,
        "max": max,
        "len": len,
        "abs": abs,
    }
    try:
        value = eval(expr, {"__builtins__": {}}, env)
        return {"status": "valid", "value": float(value), "type": "expression", "details": {"expr": expr}}
    except Exception as e:
        return {"status": "invalid", "error": f"expression eval failed: {e}", "type": "expression"}
