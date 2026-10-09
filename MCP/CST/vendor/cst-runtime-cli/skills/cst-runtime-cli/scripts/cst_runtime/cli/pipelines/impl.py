from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

from ...core.errors import error_response
from ...core.objective import compute_objective
from ...core.utils import safe_log_db as _safe_log_db
from ...core.project import _infer_category


def _parse_s11_json(file_path: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(file_path).read_text(encoding="utf-8-sig"))
        xdata = payload.get("xdata") or []
        ydata = payload.get("ydata") or []
        if not xdata or not ydata:
            return None
        db_values: list[float] = []
        for item in ydata:
            if isinstance(item, dict):
                real = float(item.get("real", 0.0))
                imag = float(item.get("imag", 0.0))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                real, imag = float(item[0]), float(item[1])
            elif isinstance(item, (int, float)):
                real, imag = float(item), 0.0
            else:
                real, imag = 0.0, 0.0
            db_values.append(_safe_log_db(math.hypot(real, imag)))
        if not db_values:
            return None
        min_idx = db_values.index(min(db_values))
        return {
            "run_id": payload.get("run_id"),
            "min_db": min(db_values),
            "best_freq": xdata[min_idx] if min_idx < len(xdata) else None,
            "point_count": len(db_values),
            "file": Path(file_path).name,
        }
    except Exception:
        return None


def _max_exported_run_id(project_path: str) -> int:
    p = Path(project_path).expanduser().resolve()
    exports_dir = p.parent.parent / "exports"
    if not exports_dir.is_dir():
        return 0
    max_rid = 0
    for f in exports_dir.glob("s11_run*.json"):
        m = re.search(r"s11_run(\d+)\.json$", f.name)
        if m:
            max_rid = max(max_rid, int(m.group(1)))
    return max_rid


# ── inspect-project (file-based, no COM/DE) ──

def _read_parameters_from_file(project_path: str) -> tuple[dict[str, Any], int]:
    """Read parameters from Model/Parameters.json on disk."""
    import json
    import re
    from pathlib import Path
    from ...core.utils import abs_project_path

    def _is_plain_number(expr: str) -> bool:
        stripped = expr.strip()
        if not stripped:
            return False
        return bool(re.fullmatch(r'-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?', stripped))

    normalized = abs_project_path(project_path)
    pdir = Path(normalized).with_suffix("")
    params_json = pdir / "Model" / "Parameters.json"
    params: dict[str, Any] = {}
    if not params_json.is_file():
        return params, 0

    try:
        pdata = json.loads(params_json.read_text(encoding="utf-8"))
        for entry in pdata.get("parameters", []):
            name = entry.get("name", "")
            if not name:
                continue
            expr = entry.get("expr", "")
            raw_val = entry.get("value", "")
            desc = entry.get("descr", "")
            try:
                value = float(raw_val) if raw_val else None
            except (ValueError, TypeError):
                value = None
            is_derived = not _is_plain_number(expr) if expr else False
            params[name] = {
                "value": value,
                "description": desc,
                "category": _infer_category(name),
                "expression": expr,
                "is_derived": is_derived,
            }
        derived_count = sum(1 for p in params.values() if p["is_derived"])
        return params, derived_count
    except Exception:
        return params, 0


def _read_entities_from_pir(project_path: str) -> tuple[list[dict[str, str]], int, dict[str, Any]]:
    """Read entities via cst_project_info_reader (offline). Returns (entities, count, extra_info)."""
    extra: dict[str, Any] = {}
    try:
        from _cst_interface import cst_project_info_reader as pir
        from ...core.utils import abs_project_path
        uri = pir.get_document_uri_for_file(abs_project_path(project_path))
        explorer = pir.CSTProjectPropertiesExplorer(uri)
        data = explorer.get_project_data()
        entities: list[dict[str, str]] = []
        block_names = data.block_names or []
        for bname in block_names:
            parts = str(bname).split(":", 1)
            component = parts[0] if len(parts) > 1 else ""
            name = parts[1] if len(parts) > 1 else parts[0]
            entities.append({"component": component, "name": name})
        extra = {
            "solver_name": data.active_solver_name or "",
            "min_frequency": data.min_frequency,
            "max_frequency": data.max_frequency,
            "frequency_unit": str(data.frequency_unit) if data.is_frequency_unit_set else "",
            "cst_version": data.full_version_string or "",
        }
        return entities, len(entities), extra
    except Exception as exc:
        return [], 0, {"pir_error": str(exc)}


def _read_solver_from_ads(project_path: str) -> dict[str, Any]:
    """Read solver type and port count from Model/3D/Model.ads on disk."""
    from pathlib import Path
    from ...core.utils import abs_project_path

    normalized = abs_project_path(project_path)
    ads_path = Path(normalized).with_suffix("") / "Model" / "3D" / "Model.ads"
    if not ads_path.is_file():
        return {}
    try:
        text = ads_path.read_text(encoding="utf-8")
        info: dict[str, Any] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and "]" in stripped:
                key = stripped[1:stripped.index("]")]
                val = stripped[stripped.index("]") + 1:].strip()
                if key == "SOLVERTYPE":
                    info["solver_type"] = val
                elif key == "NUMBEROFPORTS":
                    try:
                        info["number_of_ports"] = int(val)
                    except (ValueError, TypeError):
                        pass
        return info
    except Exception:
        return {}


def _read_frequency_and_version_from_docstore(project_path: str) -> dict[str, Any]:
    """Read frequency range and CST version from simulationproperties.docstore."""
    from pathlib import Path
    from ...core.utils import abs_project_path

    normalized = abs_project_path(project_path)
    doc_path = Path(normalized).with_suffix("") / "Model" / "simulationproperties.docstore"
    if not doc_path.is_file():
        return {}
    try:
        import sqlite3
        import cbor2

        db = sqlite3.connect(str(doc_path))
        blob = db.execute(
            "SELECT data FROM filestore_unchunked_data WHERE id=3"
        ).fetchone()
        db.close()
        if blob is None:
            return {}
        decoded = cbor2.loads(blob[0])

        # Navigate: !d → {!d} → root_project → {!d} → 3d_info → {!d} → value → {!d} → frequency → {!d}
        info: dict[str, Any] = {}
        payload = decoded.get("!d", {}).get("!d", {})
        try:
            freq = payload["root_project"]["!d"]["3d_info"]["!d"]["value"]["!d"]["frequency"]["!d"]
            fmin = freq.get("minimum", {}).get("!d")
            fmax = freq.get("maximum", {}).get("!d")
            if fmin is not None and fmax is not None:
                info["frequency_range_ghz"] = {"min": float(fmin), "max": float(fmax)}
        except (KeyError, TypeError):
            pass

        # CST version from common path
        try:
            ver = payload["root_project"]["!d"]["common"]["!d"]["cst_version"]["!d"]
            version_str = ver.get("full_version_string", {}).get("!d", "")
            if version_str:
                info["cst_version"] = version_str
        except (KeyError, TypeError):
            pass

        return info
    except Exception:
        return {}


def _read_entities_from_fct(project_path: str) -> tuple[list[dict[str, str]], int]:
    """Read solid entity names from Model/3D/Model.fct on disk."""
    import re
    from pathlib import Path
    from ...core.utils import abs_project_path

    normalized = abs_project_path(project_path)
    fct_path = Path(normalized).with_suffix("") / "Model" / "3D" / "Model.fct"
    if not fct_path.is_file():
        return [], 0
    try:
        raw = fct_path.read_bytes()
        entities: list[dict[str, str]] = []
        seen: set[str] = set()
        # Names are concatenated with "solid$" delimiter
        for part in raw.split(b"solid$"):
            if not part:
                continue
            # Remove trailing null bytes / binary noise
            clean = part.rstrip(b"\x00").decode("ascii", errors="replace")
            if ":" not in clean:
                continue
            idx = clean.index(":")
            component = clean[:idx]
            name = clean[idx + 1:]
            if not name or not component:
                continue
            key = f"{component}:{name}"
            if key not in seen:
                seen.add(key)
                entities.append({"component": component, "name": name})
        return entities, len(entities)
    except Exception:
        return [], 0


def _read_farfield_monitors_from_dsn(project_path: str) -> tuple[list[str], int]:
    """Read farfield monitors from Model/3D/Model.dsn on disk."""
    import re
    from pathlib import Path
    from ...core.utils import abs_project_path

    normalized = abs_project_path(project_path)
    dsn_path = Path(normalized).with_suffix("") / "Model" / "3D" / "Model.dsn"
    if not dsn_path.is_file():
        return [], 0
    try:
        text = dsn_path.read_text(encoding="utf-8")
        monitors: list[str] = []
        in_monitor = False
        montype = None
        monname = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("*** newmonitor"):
                in_monitor = True
                montype = None
                monname = ""
            elif stripped.startswith("*** endmonitor") and in_monitor:
                in_monitor = False
                if montype == 18 and monname:
                    monitors.append(monname)
            elif in_monitor:
                m = re.match(r'montype:\s*(\d+)', stripped)
                if m:
                    montype = int(m.group(1))
                m = re.match(r'monname:\s*"(.+)"', stripped)
                if m:
                    monname = m.group(1)
        return monitors, len(monitors)
    except Exception:
        return [], 0


def pipeline_inspect_project(project_path: str) -> dict[str, Any]:
    from ...core.utils import abs_project_path

    normalized = abs_project_path(project_path)
    from pathlib import Path
    if not Path(normalized).is_file():
        return error_response(
            "project_file_missing",
            f"project_path does not exist: {normalized}",
            step="inspect-project:validate",
        )

    # Read parameters from file
    params, derived_count = _read_parameters_from_file(normalized)
    parameters_count = len(params)

    # Read entities via cst_project_info_reader (primary), fallback to file
    entities, entities_count, pir_extra = _read_entities_from_pir(normalized)
    pir_failed = bool(pir_extra.get("pir_error"))
    if pir_failed or not entities:
        file_entities, file_count = _read_entities_from_fct(normalized)
        if file_entities:
            entities = file_entities
            entities_count = file_count

    # Read solver info — PIR primary, fallback to Model.ads
    solver_info: dict[str, Any] = {}
    if pir_extra.get("solver_name"):
        solver_info["solver_name"] = pir_extra["solver_name"]
    else:
        ads_info = _read_solver_from_ads(normalized)
        if ads_info.get("solver_type"):
            solver_info["solver_type"] = ads_info["solver_type"]
        if ads_info.get("number_of_ports") is not None:
            solver_info["number_of_ports"] = ads_info["number_of_ports"]

    # Read frequency/version — PIR primary, fallback to docstore
    if pir_extra.get("min_frequency") is not None:
        solver_info["frequency_range_ghz"] = {
            "min": pir_extra["min_frequency"],
            "max": pir_extra["max_frequency"],
        }
    if pir_extra.get("cst_version"):
        solver_info["cst_version"] = pir_extra["cst_version"]
    if "frequency_range_ghz" not in solver_info or "cst_version" not in solver_info:
        doc_info = _read_frequency_and_version_from_docstore(normalized)
        if "frequency_range_ghz" not in solver_info and "frequency_range_ghz" in doc_info:
            solver_info["frequency_range_ghz"] = doc_info["frequency_range_ghz"]
        if "cst_version" not in solver_info and "cst_version" in doc_info:
            solver_info["cst_version"] = doc_info["cst_version"]

    # Read farfield monitors from Model.dsn
    ff_names, ff_count = _read_farfield_monitors_from_dsn(normalized)

    result: dict[str, Any] = {
        "status": "success",
        "pipeline": "inspect-project",
        "project_path": normalized,
        "method": "file_based",
        "parameters": params,
        "parameters_count": parameters_count,
        "entities": entities,
        "entities_count": entities_count,
        "farfield_monitors": ff_names,
        "farfield_monitors_count": ff_count,
    }
    if parameters_count > 0:
        result["derived_parameters_count"] = derived_count
    if solver_info:
        result["solver_info"] = solver_info
    if pir_failed:
        result["pir_note"] = (f"cst_project_info_reader unavailable: {pir_extra['pir_error']}"
                              " — some data from file fallback")

    return result


# ── prepare-experiment ──

def pipeline_prepare_experiment(
    project_path: str,
    param_name: str = "",
    param_value: float = 0,
    names: list[str] | None = None,
    values: list[float] | None = None,
) -> dict[str, Any]:
    from ...core.session import open_project as sm_open, close_project as sm_close
    from ...core.project import change_parameter, list_parameters, save_project

    resolved_names: list[str] = []
    resolved_values: list[float] = []
    if names and values:
        resolved_names = names
        resolved_values = values
    elif param_name:
        resolved_names = [param_name]
        resolved_values = [param_value]
    else:
        return error_response(
            "pipeline_param_missing",
            "provide param_name+param_value or names+values",
            step="prepare-experiment:validate",
        )

    if len(resolved_names) != len(resolved_values):
        return error_response(
            "pipeline_param_count_mismatch",
            f"names ({len(resolved_names)}) != values ({len(resolved_values)})",
            step="prepare-experiment:validate",
        )

    open_result = sm_open(project_path)
    if open_result.get("status") != "success":
        return open_result

    all_changed: dict[str, Any] = {}
    for n, v in zip(resolved_names, resolved_values):
        cr = change_parameter(project_path=project_path, name=n, value=v)
        if cr.get("status") != "success":
            sm_close(project_path, save=False)
            return error_response(
                "pipeline_change_param_failed",
                cr.get("message", f"failed to change {n}={v}"),
                step="prepare-experiment:change-param",
                change_result=cr,
            )
        all_changed.update(cr.get("changed", {}))

    confirm_result = list_parameters(project_path)
    if confirm_result.get("status") != "success":
        sm_close(project_path, save=False)
        return error_response(
            "pipeline_confirm_params_failed",
            confirm_result.get("message", "failed to confirm parameter change"),
            step="prepare-experiment:confirm",
        )

    save_result = save_project(project_path)
    if save_result.get("status") != "success":
        sm_close(project_path, save=False)
        return error_response(
            "pipeline_save_failed",
            save_result.get("message", "failed to save project"),
            step="prepare-experiment:save",
        )

    sm_close(project_path, save=False)
    return {
        "status": "success",
        "pipeline": "prepare-experiment",
        "project_path": open_result.get("project_path", project_path),
        "changed": all_changed,
        "param_names": resolved_names,
        "param_values": resolved_values,
        "parameters": confirm_result.get("parameters", {}),
    }


# ── run-experiment ──

def pipeline_run_experiment(
    project_path: str,
    farfield_names: list[str] | None = None,
    farfield_plot_mode: str = "Realized Gain",
    farfield_theta_step: float = 2.0,
    farfield_phi_step: float = 2.0,
    timeout_seconds: int = 3600,
    poll_interval_seconds: float = 10.0,
) -> dict[str, Any]:
    from ...core.session import open_project as sm_open, close_project as sm_close
    from ...core.simulation import start_simulation_async, is_simulation_running
    from ...core.results import export_run_results

    # Record pre-existing exported file count to detect if solver produced new results.
    # Checks the exports/ directory before and after export:
    #   - mode A (existing project): file number must increase
    #   - mode B (new project): first file is created (0 → N)
    max_before_export = _max_exported_run_id(project_path)

    open_result = sm_open(project_path)
    if open_result.get("status") != "success":
        return error_response(
            "pipeline_open_failed",
            open_result.get("message", "failed to open project for simulation"),
            step="run-experiment:open",
        )

    sim_result = start_simulation_async(project_path)
    if sim_result.get("status") != "success":
        sm_close(project_path, save=False)
        return error_response(
            "pipeline_sim_start_failed",
            sim_result.get("message", "failed to start simulation"),
            step="run-experiment:start-sim",
        )

    import time
    polls = 0
    waited = 0.0
    while True:
        time.sleep(poll_interval_seconds)
        waited += poll_interval_seconds
        polls += 1
        running_result = is_simulation_running(project_path)
        if running_result.get("status") != "success":
            sm_close(project_path, save=False)
            return error_response(
                "pipeline_sim_check_failed",
                running_result.get("message", "failed to check simulation status"),
                step="run-experiment:check",
                polls=polls,
                waited_seconds=waited,
            )
        if not running_result.get("running", True):
            break
        if waited >= timeout_seconds:
            sm_close(project_path, save=False)
            return error_response(
                "pipeline_sim_timeout",
                f"simulation still running after {waited:.0f}s",
                step="run-experiment:timeout",
                polls=polls,
                timeout_seconds=timeout_seconds,
            )

    close_result = sm_close(project_path, save=False)
    if close_result.get("status") != "success":
        return error_response(
            "pipeline_close_failed",
            close_result.get("message", "failed to close modeler session"),
            step="run-experiment:close",
        )

    export_result = export_run_results(
        project_path=project_path,
        farfield_names=farfield_names,
        farfield_plot_mode=farfield_plot_mode,
        farfield_theta_step=farfield_theta_step,
        farfield_phi_step=farfield_phi_step,
    )
    if export_result.get("status") != "success":
        return error_response(
            "pipeline_export_failed",
            export_result.get("message", "failed to export results"),
            step="run-experiment:export",
            export_result=export_result,
        )

    exported_files = export_result.get("exported", [])
    s11_files = [f for f in exported_files if re.search(r"s11_run\d+\.json$", str(f), re.IGNORECASE)]
    farfield_files = [f for f in exported_files if re.search(r"farfield", str(f), re.IGNORECASE)]

    s11_metric = None
    s11_export_path = ""
    if s11_files:
        s11_export_path = str(s11_files[-1])
        s11_metric = _parse_s11_json(s11_export_path)

    run_id = s11_metric.get("run_id") if s11_metric else None

    # Verify solver produced new results by checking if exported file number increased
    max_after_export = _max_exported_run_id(project_path)
    solver_produced_new_data = max_after_export > max_before_export

    output: dict[str, Any] = {
        "pipeline": "run-experiment",
        "project_path": open_result.get("project_path", project_path),
        "polls": polls,
        "waited_seconds": waited,
        "exported_count": len(exported_files),
        "exported": exported_files,
        "s11_export_path": s11_export_path,
        "s11_metric": s11_metric,
        "farfield_exported": farfield_files,
        "pre_export_max_file_num": max_before_export,
        "post_export_max_file_num": max_after_export,
    }
    if run_id is not None:
        output["run_id"] = run_id

    if not solver_produced_new_data:
        if exported_files:
            output["status"] = "success"
            output["solver_completed"] = False
            output["warning"] = "solver_result_cached"
            output["message"] = (
                f"Solver completed but produced no new run_id (exported file number "
                f"{max_after_export} unchanged). Existing results were re-exported. "
                f"This is a cache hit: the parameter combination already exists."
            )
        else:
            return {
                "status": "error",
                "error_type": "solver_did_not_complete",
                "message": (
                    f"Solver did not produce new results: "
                    f"exported file number {max_after_export} <= pre-existing {max_before_export}. "
                    f"No existing results were found either. "
                    f"The simulation may have failed silently (e.g. mesh error, geometry issue). "
                    f"Check CST solver logs in Result/*.log for details."
                ),
                **output,
            }
        return output

    output["status"] = "success"
    output["solver_completed"] = True
    return output


# ── run-probe-phase ──

def pipeline_run_probe_phase(
    project_path: str,
    parameters: dict,
    study_storage: str,
    study_name: str,
    max_probes: int = 12,
    include_center: bool = True,
    objective: dict | None = None,
) -> dict[str, Any]:
    import shutil
    from pathlib import Path
    from ...core import doe as _doe
    from ...core import optimizer as _opt

    p = Path(project_path).expanduser().resolve()
    if not p.is_file():
        return error_response("project_not_found", f"project not found: {p}", step="probe-phase:validate")

    # 1. Copy working.cst → working_probe.cst (baseline isolation)
    probe_project = p.parent / "working_probe.cst"
    shutil.copy2(str(p), str(probe_project))
    probe_path = str(probe_project)

    # 2. Design probes via DOE
    design = _doe.design_probes(parameters, max_probes=max_probes, include_center=include_center)
    if design.get("status") != "success":
        return error_response("probe_design_failed",
            design.get("message", "failed to design probes"), step="probe-phase:design")

    probes = design["probes"]
    param_names = design["parameters"]

    # 3. Simulate each probe
    simulated: list[dict] = []
    cached: list[dict] = []
    failed: list[dict] = []
    for probe in probes:
        names = list(probe.keys())
        values = [probe[n] for n in names]
        prep = pipeline_prepare_experiment(probe_path, names=names, values=values)
        if prep.get("status") != "success":
            failed.append({"params": probe, "error": "prepare_failed"})
            continue
        sim = pipeline_run_experiment(probe_path)
        if sim.get("status") != "success":
            obj = compute_objective(objective or {}, sim)
            if not obj.get("error"):
                simulated.append({"params": probe, "value": obj["value"]})
            else:
                failed.append({"params": probe, "error": sim.get("error_type", "sim_failed")})
            continue
        obj = compute_objective(objective or {}, sim)
        if not obj.get("error"):
            result = {"params": probe, "value": obj["value"]}
            simulated.append(result)
            if not sim.get("solver_completed", True):
                cached.append(result)
        else:
            failed.append({"params": probe, "error": obj.get("error", "objective_failed")})

    # 4. Move exported files to exports/probe/
    exports_dir = p.parent.parent / "exports"
    probe_exports = exports_dir / "probe"
    probe_exports.mkdir(parents=True, exist_ok=True)
    for f in exports_dir.glob("s11_run*.json"):
        shutil.move(str(f), str(probe_exports / f.name))
    for f in exports_dir.glob("farfield_*"):
        shutil.move(str(f), str(probe_exports / f.name))

    if not simulated:
        return error_response("all_probes_failed",
            "no probe simulations produced valid results", step="probe-phase:simulate",
            n_total=len(probes), n_failed=len(failed))

    # 5. Analyze probe results
    analysis = _doe.analyze_probes(param_names, simulated)

    # 6. Inject probe results into study
    trials = [{"params": s["params"], "values": [s["value"]]} for s in simulated]
    inject = _opt.add_trials(study_storage, study_name, trials)
    trials_injected = inject.get("trials_added", 0)

    # Edge hit detection
    edge_hit: dict[str, bool] = {}
    for name, ranges in parameters.items():
        pmin = ranges.get("min", 0)
        pmax = ranges.get("max", 0)
        hits = [s for s in simulated if abs(s["params"].get(name, 0) - pmin) < 1e-9 or abs(s["params"].get(name, 0) - pmax) < 1e-9]
        edge_hit[name] = len(hits) > 0

    # Algorithm suggestion
    n_important = len(analysis.get("top_params", []))
    interactions = analysis.get("interactions", {})
    has_strong_interaction = any(v > 0.3 for v in interactions.values()) if interactions else False
    if n_important > 3 or has_strong_interaction:
        suggested_algorithm = "CMA-ES"
    else:
        suggested_algorithm = "TPE"

    return {
        "status": "success" if len(simulated) >= len(probes) / 2 else "warning",
        "pipeline": "run-probe-phase",
        "n_probes": len(probes),
        "n_simulated": len(simulated),
        "n_cached": len(cached),
        "n_failed": len(failed),
        "failed_probes": failed,
        "mean_value": analysis.get("mean_value"),
        "main_effects": analysis.get("main_effects", {}),
        "main_effects_normalized": analysis.get("main_effects_normalized", {}),
        "interactions": analysis.get("interactions", {}),
        "top_params": analysis.get("top_params", []),
        "trials_injected": trials_injected,
        "probe_project": str(probe_project),
        "exports_dir": str(probe_exports),
        "edge_hit": edge_hit,
        "suggested_algorithm": suggested_algorithm,
    }


# ── run-optimization-step ──

def pipeline_run_optimization_step(
    project_path: str,
    study_storage: str,
    study_name: str,
    objective: dict | None = None,
    sampler: str | None = None,
) -> dict[str, Any]:
    from ...core import optimizer as _opt

    # 0. Switch sampler if requested
    if sampler:
        from ...core.optimizer import switch_sampler as _switch_sampler
        switch_result = _switch_sampler(study_storage, study_name, sampler)
        if switch_result.get("status") != "success":
            return error_response("switch_sampler_failed",
                switch_result.get("message", "failed to switch sampler"), step="opt-step:switch-sampler")

    # 1. Ask study for next parameter suggestion
    ask = _opt.ask_study(study_storage, study_name)
    if ask.get("status") != "success":
        return error_response("ask_study_failed",
            ask.get("message", "study may be complete"), step="opt-step:ask",
            ask_result=ask)

    trial_number = ask["trial_number"]
    params = ask.get("params", {})
    names = list(params.keys())
    values = [params[n] for n in names]

    # 2. Prepare experiment (change params, save, close)
    prep = pipeline_prepare_experiment(project_path, names=names, values=values)
    if prep.get("status") != "success":
        _opt.tell_study(study_storage, study_name, trial_number, state="pruned")
        return error_response("prepare_failed",
            prep.get("message", "failed to prepare experiment"), step="opt-step:prepare")

    # 3. Run simulation and export
    sim = pipeline_run_experiment(project_path)
    if sim.get("status") != "success":
        obj = compute_objective(objective or {}, sim)
        if not obj.get("error"):
            _opt.tell_study(study_storage, study_name, trial_number, value=obj["value"])
            return {
                "status": "success",
                "pipeline": "run-optimization-step",
                "trial_id": trial_number,
                "params_used": params,
                "objective_value": obj["value"],
                "s11_metric": sim.get("s11_metric"),
                "study_best": None,
                "cache_hit": not sim.get("solver_completed", True),
                "steps_since_improvement": 0,
            }
        _opt.tell_study(study_storage, study_name, trial_number, state="pruned")
        return error_response("simulation_failed",
            sim.get("message", "simulation did not complete"), step="opt-step:simulate")

    # 4. Compute objective
    obj = compute_objective(objective or {}, sim)
    if obj.get("error"):
        _opt.tell_study(study_storage, study_name, trial_number, state="pruned")
        return error_response("objective_failed",
            obj["error"], step="opt-step:objective", objective_result=obj)

    objective_value = obj["value"]

    # 5. Tell study the result
    _opt.tell_study(study_storage, study_name, trial_number, value=objective_value)

    # 6. Read current best
    best = _opt.best_study(study_storage, study_name)
    study_best = None
    if best.get("best_value") is not None:
        study_best = {"value": best["best_value"], "params": best.get("best_params")}

    # 7. Compute steps since improvement
    steps_since_improvement = 0
    trial_num = trial_number or 0
    best_trial_num = best.get("best_trial_number")
    if best_trial_num is not None:
        steps_since_improvement = trial_num - best_trial_num

    return {
        "status": "success",
        "pipeline": "run-optimization-step",
        "trial_id": trial_number,
        "params_used": params,
        "objective_value": objective_value,
        "s11_metric": sim.get("s11_metric"),
        "study_best": study_best,
        "cache_hit": not sim.get("solver_completed", True),
        "steps_since_improvement": steps_since_improvement,
    }
