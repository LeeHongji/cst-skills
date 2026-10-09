from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def error_response(error_type: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"status": "error", "error_type": error_type, "message": message, **extra}


def _try_import_optuna():
    try:
        import optuna
        return optuna, None
    except ImportError:
        return None, error_response(
            "optuna_not_installed",
            "optuna is required for optimization. Install with: pip install optuna",
            runtime_module="cst_runtime.core.optimizer",
        )


_parse_json = lambda v, d=None: json.loads(v) if isinstance(v, str) and v.strip() else (v or d)


def _make_constraints_func(constraint_defs: list[dict]) -> Any:
    """Return an Optuna sampler constraint callback backed by trial user attrs."""
    import optuna
    def constraints_func(trial: "optuna.trial.Trial") -> list[float]:
        vals = trial.user_attrs.get("constraints", [])
        if not vals:
            return [0.0] * len(constraint_defs)
        return vals
    return constraints_func


def _make_sampler(
    optuna: Any,
    sampler: str,
    n_startup_trials: int,
    constraint_defs: list[dict] | None = None,
) -> Any:
    sampler_name = sampler.casefold()
    constraints_func = _make_constraints_func(constraint_defs) if constraint_defs else None
    if sampler_name == "tpe":
        return optuna.samplers.TPESampler(
            seed=42,
            n_startup_trials=int(n_startup_trials),
            constraints_func=constraints_func,
        )
    if sampler_name in {"nsga-ii", "nsgaii"}:
        return optuna.samplers.NSGAIISampler(seed=42, constraints_func=constraints_func)
    if constraints_func is not None:
        raise ValueError(f"sampler '{sampler}' does not support constraints")
    if sampler_name == "cma-es":
        return optuna.samplers.CmaEsSampler(seed=42, n_startup_trials=int(n_startup_trials))
    if sampler_name == "random":
        return optuna.samplers.RandomSampler(seed=42)
    raise ValueError(f"unknown sampler: {sampler}")


def _constraint_defs(study: Any) -> list[dict]:
    return _parse_json(study.user_attrs.get("constraint_defs", "[]"), [])


def _is_feasible(trial: Any, constrained: bool) -> bool:
    if not constrained:
        return True
    values = trial.user_attrs.get("constraints")
    return bool(values is not None and all(float(value) <= 0.0 for value in values))


def _best_single_trial(study: Any, trials: list[Any]) -> Any | None:
    if not trials:
        return None
    reverse = str(study.direction).upper().endswith("MAXIMIZE")
    return sorted(trials, key=lambda trial: float(trial.value), reverse=reverse)[0]


def create_study(
    storage_path: str,
    study_name: str,
    parameters: str | dict,
    direction: str = "minimize",
    directions: list[str] | None = None,
    value_names: list[str] | None = None,
    constraints: list[dict] | None = None,
    sampler: str = "tpe",
    n_startup_trials: int = 10,
) -> dict[str, Any]:
    optuna, err = _try_import_optuna()
    if err:
        return err
    sp = Path(storage_path).expanduser().resolve()
    sp.parent.mkdir(parents=True, exist_ok=True)
    storage = f"sqlite:///{sp.as_posix()}"
    try:
        params_dict = _parse_json(parameters, {})
    except (json.JSONDecodeError, TypeError) as e:
        return error_response("invalid_parameters", str(e))
    try:
        resolved_directions = directions or [direction]
        is_multi = len(resolved_directions) > 1
        sampler_obj = _make_sampler(optuna, sampler, n_startup_trials, constraints)
        kwargs: dict[str, Any] = dict(
            storage=storage,
            study_name=study_name,
            load_if_exists=True,
            sampler=sampler_obj,
        )
        if is_multi:
            dir_map = {"minimize": optuna.study.StudyDirection.MINIMIZE, "maximize": optuna.study.StudyDirection.MAXIMIZE}
            kwargs["directions"] = [dir_map[d] for d in resolved_directions]
        else:
            kwargs["direction"] = resolved_directions[0]
        study = optuna.create_study(**kwargs)
        study.set_user_attr("parameters", json.dumps(params_dict, ensure_ascii=False))
        study.set_user_attr("sampler", sampler)
        study.set_user_attr("n_startup_trials", int(n_startup_trials))
        if value_names:
            study.set_user_attr("value_names", json.dumps(value_names, ensure_ascii=False))
        if is_multi:
            study.set_user_attr("multi_objective", "true")
        if constraints:
            study.set_user_attr("constraint_defs", json.dumps(constraints, ensure_ascii=False))
        return {
            "status": "success", "study_name": study_name, "storage": str(sp),
            "directions": resolved_directions, "sampler": sampler,
            "sampler_class": type(study.sampler).__name__,
            "parameters": params_dict, "number_of_trials": len(study.trials),
            "multi_objective": is_multi, "constrained": bool(constraints),
            "runtime_module": "cst_runtime.core.optimizer",
        }
    except Exception as exc:
        return error_response("create_study_failed", str(exc), study_name=study_name)


def ask_study(storage_path: str, study_name: str) -> dict[str, Any]:
    optuna, err = _try_import_optuna()
    if err:
        return err
    sp = Path(storage_path).expanduser().resolve()
    storage = f"sqlite:///{sp.as_posix()}"
    try:
        stored = optuna.load_study(storage=storage, study_name=study_name)
        sampler_name = str(stored.user_attrs.get("sampler", "tpe"))
        n_startup_trials = int(stored.user_attrs.get("n_startup_trials", 10))
        constraint_defs = _parse_json(stored.user_attrs.get("constraint_defs", "[]"), [])
        sampler_obj = _make_sampler(optuna, sampler_name, n_startup_trials, constraint_defs)
        study = optuna.load_study(
            storage=storage,
            study_name=study_name,
            sampler=sampler_obj,
        )
        param_raw = study.user_attrs.get("parameters", "{}")
        params_def = _parse_json(param_raw, {})
        trial = study.ask()
        params: dict[str, Any] = {}
        for pname, pdef in params_def.items():
            ptype = pdef.get("type", "float")
            low = pdef.get("min", pdef.get("low", 0))
            high = pdef.get("max", pdef.get("high", 1))
            if ptype == "int":
                params[pname] = trial.suggest_int(pname, int(low), int(high))
            elif ptype == "categorical":
                params[pname] = trial.suggest_categorical(pname, pdef.get("choices", []))
            else:
                params[pname] = trial.suggest_float(pname, float(low), float(high), log=pdef.get("log", False))
        return {
            "status": "success", "study_name": study_name,
            "trial_number": trial.number, "params": params,
            "runtime_module": "cst_runtime.core.optimizer",
        }
    except Exception as exc:
        return error_response("ask_study_failed", str(exc), study_name=study_name)


def _trial_set_constraints(study, trial_number: int, constraints: list[float]) -> None:
    """Set constraint values on a trial using its internal trial_id."""
    for t in study.trials:
        if t.number == trial_number:
            trial_id = t._trial_id
            break
    else:
        raise ValueError(f"trial {trial_number} not found")
    import optuna.trial as tmod
    trial_obj = tmod.Trial(study, trial_id)
    trial_obj.set_user_attr("constraints", constraints)


def tell_study(
    storage_path: str, study_name: str, trial_number: int,
    value: float | None = None, values: list[float] | None = None,
    constraints: list[float] | None = None,
    state: str = "complete",
) -> dict[str, Any]:
    optuna, err = _try_import_optuna()
    if err:
        return err
    sp = Path(storage_path).expanduser().resolve()
    storage = f"sqlite:///{sp.as_posix()}"
    try:
        study = optuna.load_study(storage=storage, study_name=study_name)
        state_map = {
            "complete": optuna.trial.TrialState.COMPLETE,
            "pruned": optuna.trial.TrialState.PRUNED,
            "fail": optuna.trial.TrialState.FAIL,
            "failed": optuna.trial.TrialState.FAIL,
        }
        state_obj = state_map.get(state.casefold())
        if state_obj is None:
            return error_response("tell_invalid_state", f"unsupported trial state: {state}")
        resolved_values = values if values is not None else ([value] if value is not None else None)
        if state_obj == optuna.trial.TrialState.COMPLETE and resolved_values is None:
            return error_response("tell_no_value", "provide value or values")
        constraint_defs = _constraint_defs(study)
        if state_obj == optuna.trial.TrialState.COMPLETE and constraint_defs and constraints is None:
            return error_response(
                "tell_missing_constraints",
                "constrained studies require constraint values for completed trials",
            )
        if constraints is not None:
            _trial_set_constraints(study, trial_number, [float(c) for c in constraints])
        study.tell(trial_number, resolved_values, state=state_obj)
        trials = study.trials
        completed = [t for t in trials if t.state == optuna.trial.TrialState.COMPLETE]
        feasible = [t for t in completed if _is_feasible(t, bool(constraint_defs))]
        result: dict[str, Any] = {
            "status": "success", "study_name": study_name,
            "trial_number": trial_number, "values": resolved_values, "state": state,
            "total_trials": len(trials),
            "runtime_module": "cst_runtime.core.optimizer",
        }
        if feasible:
            try:
                best = _best_single_trial(study, feasible)
                assert best is not None
                result["best_value"] = best.values[0] if len(best.values) == 1 else best.values
                result["best_params"] = best.params
                result["best_trial_number"] = best.number
            except Exception:
                best_trials = study.best_trials[:10]
                result["best_values"] = [t.values for t in best_trials]
                result["best_params_list"] = [t.params for t in best_trials]
        return result
    except Exception as exc:
        return error_response("tell_study_failed", str(exc), study_name=study_name, trial_number=trial_number)


def best_study(storage_path: str, study_name: str) -> dict[str, Any]:
    optuna, err = _try_import_optuna()
    if err:
        return err
    sp = Path(storage_path).expanduser().resolve()
    storage = f"sqlite:///{sp.as_posix()}"
    try:
        study = optuna.load_study(storage=storage, study_name=study_name)
        trials = study.trials
        completed = [t for t in trials if t.state == optuna.trial.TrialState.COMPLETE]
        result: dict[str, Any] = {
            "status": "success", "study_name": study_name,
            "total_trials": len(trials), "completed_trials": len(completed),
            "runtime_module": "cst_runtime.core.optimizer",
        }
        is_mo = study.user_attrs.get("multi_objective") == "true"
        constraint_defs = _constraint_defs(study)
        feasible = [t for t in completed if _is_feasible(t, bool(constraint_defs))]
        result["feasible_trials"] = len(feasible)
        if feasible:
            if is_mo:
                result["best_values"] = [t.values for t in feasible[:10]]
                result["n_objectives"] = len(feasible[0].values)
            else:
                try:
                    best = _best_single_trial(study, feasible)
                    assert best is not None
                    result["best_value"] = best.value
                    result["best_params"] = best.params
                    result["best_trial_number"] = best.number
                except Exception:
                    pass
        return result
    except Exception as exc:
        return error_response("best_study_failed", str(exc), study_name=study_name)


def param_importances(storage_path: str, study_name: str) -> dict[str, Any]:
    optuna, err = _try_import_optuna()
    if err:
        return err
    sp = Path(storage_path).expanduser().resolve()
    storage = f"sqlite:///{sp.as_posix()}"
    try:
        study = optuna.load_study(storage=storage, study_name=study_name)
        try:
            from optuna.importance import get_param_importances
            importances = get_param_importances(study)
        except ImportError:
            return error_response("sklearn_missing", "scikit-learn is required for parameter importance. Install with: pip install scikit-learn", study_name=study_name)
        sorted_params = sorted(importances.items(), key=lambda x: -x[1])
        return {
            "status": "success", "study_name": study_name,
            "importances": {name: round(val, 4) for name, val in sorted_params},
            "top_param": sorted_params[0][0] if sorted_params else None,
            "runtime_module": "cst_runtime.core.optimizer",
        }
    except Exception as exc:
        return error_response("param_importances_failed", str(exc), study_name=study_name)


def add_trials(
    storage_path: str, study_name: str,
    trials: list[dict],
) -> dict[str, Any]:
    """Inject pre-computed trials into a study (e.g. from manual grid scan).

    Each trial dict: {"params": {"R": 0.1}, "values": [-28.7], "constraints": [0.0]}
    """
    optuna, err = _try_import_optuna()
    if err:
        return err
    sp = Path(storage_path).expanduser().resolve()
    storage = f"sqlite:///{sp.as_posix()}"
    try:
        study = optuna.load_study(storage=storage, study_name=study_name)
        param_raw = study.user_attrs.get("parameters", "{}")
        params_def = _parse_json(param_raw, {})
        constraint_defs = _constraint_defs(study)
        distributions: dict[str, Any] = {}
        for pname, pdef in params_def.items():
            ptype = pdef.get("type", "float")
            low = pdef.get("min", pdef.get("low", 0))
            high = pdef.get("max", pdef.get("high", 1))
            if ptype == "int":
                distributions[pname] = optuna.distributions.IntDistribution(int(low), int(high))
            else:
                log = pdef.get("log", False)
                distributions[pname] = optuna.distributions.FloatDistribution(float(low), float(high), log=log)
        added = 0
        for td in trials:
            params = td.get("params", {})
            values = td.get("values", [td.get("value", 0)])
            constraints = td.get("constraints")
            if constraint_defs and constraints is None:
                return error_response(
                    "add_trials_missing_constraints",
                    "constrained studies require constraint values for every added trial",
                )
            trial = optuna.create_trial(
                params=params,
                distributions=distributions,
                values=values,
                state=optuna.trial.TrialState.COMPLETE,
                user_attrs={"constraints": constraints} if constraints is not None else None,
            )
            study.add_trial(trial)
            added += 1
        return {
            "status": "success", "study_name": study_name,
            "trials_added": added, "total_trials": len(study.trials),
            "runtime_module": "cst_runtime.core.optimizer",
        }
    except Exception as exc:
        return error_response("add_trials_failed", str(exc), study_name=study_name)


def switch_sampler(storage_path: str, study_name: str, new_sampler: str) -> dict[str, Any]:
    optuna, err = _try_import_optuna()
    if err:
        return err
    sp = Path(storage_path).expanduser().resolve()
    storage = f"sqlite:///{sp.as_posix()}"
    try:
        study = optuna.load_study(storage=storage, study_name=study_name)
        trials = study.trials
        user_attrs = dict(study.user_attrs)
        constraint_defs = _parse_json(user_attrs.get("constraint_defs", "[]"), [])
        n_startup_trials = int(user_attrs.get("n_startup_trials", 10))
        sampler_obj = _make_sampler(optuna, new_sampler, n_startup_trials, constraint_defs)
        study.set_user_attr("sampler", new_sampler)
        return {
            "status": "success", "study_name": study_name,
            "sampler": new_sampler, "total_trials": len(trials),
            "sampler_class": type(sampler_obj).__name__,
            "trials_preserved": len(trials),
            "runtime_module": "cst_runtime.core.optimizer",
        }
    except Exception as exc:
        return error_response("switch_sampler_failed", str(exc), study_name=study_name, sampler=new_sampler)


def terminate_check(storage_path: str, study_name: str) -> dict[str, Any]:
    optuna, err = _try_import_optuna()
    if err:
        return err
    sp = Path(storage_path).expanduser().resolve()
    storage = f"sqlite:///{sp.as_posix()}"
    try:
        study = optuna.load_study(storage=storage, study_name=study_name)
        from optuna.terminator import Terminator
        terminator = Terminator()
        should_terminate = terminator.should_terminate(study)
        return {
            "status": "success", "study_name": study_name,
            "should_terminate": should_terminate,
            "total_trials": len(study.trials),
            "runtime_module": "cst_runtime.core.optimizer",
        }
    except Exception as exc:
        return error_response("terminate_check_failed", str(exc), study_name=study_name)
