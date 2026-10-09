#!/usr/bin/env python3
"""Killable CST worker used by the guardian supervisor and its live tests.

Runs in its own process so a blocked COM call can be terminated without harming
the caller.  Every subcommand prints one JSON object on stdout when it completes;
a subcommand that blocks on a CST dialog prints nothing and is expected to be
killed by the supervisor.

Ends with ``os._exit`` so a COM object still held by CST cannot stall interpreter
shutdown after the work itself is done.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cst_guardian import GuardedSession, preconditions  # noqa: E402

# CST's messages are not ASCII and not all of them fit the Windows ANSI code
# page.  When stdout is redirected to a file it defaults to that code page, so a
# single message containing an unmappable character raises UnicodeEncodeError and
# kills the worker mid-report -- which looks like a CST failure rather than an
# encoding one.  Observed live: a VBA syntax error message killed two cases.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.flush()


def _session(args: argparse.Namespace) -> GuardedSession:
    return GuardedSession(
        pid=args.pid,
        launch_if_needed=args.launch,
        enforce_quiet=not args.no_quiet,
    )


def cmd_probe(args: argparse.Namespace) -> int:
    """Attach and report session state without touching any project."""
    with _session(args) as guard:
        _emit({"command": "probe", "session": guard.info.to_json()})
    return 0


def cmd_build_ir(args: argparse.Namespace) -> int:
    """Verification-only builder: validated IR, fresh run path, explicit owner PID.

    No arbitrary Python or caller-supplied VBA is accepted. Production MCP writes
    remain fail closed until the Step 4 facade is separately completed.
    """
    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo / "MCP/CST-CAD/src"))
    from cst_cad import ir, drc, emit_vba
    if args.pid is None or args.no_quiet:
        raise ValueError("build-ir requires an explicit task-owned --pid and quiet mode")
    target = Path(args.project).resolve()
    target.relative_to(repo / "cst_runs")
    if target.suffix.lower() != ".cst" or target.exists() or target.with_suffix("").exists():
        raise ValueError("build-ir requires a new .cst and new companion under cst_runs")
    document = ir.read(args.ir)
    problems = ir.validate(document)
    if problems:
        raise ValueError(str(problems))
    checks = drc.run(document)
    if checks["status"] != "pass":
        raise ValueError("DRC must pass before creating a CST project")
    blocks = emit_vba.build_blocks(document)
    for block in blocks:
        preconditions.check_history_code(block.code)
    emit_vba.write_blocks(document, target.parent / "vba")
    with _session(args) as guard:
        project = guard.new_project(target)
        try:
            for block in blocks:
                before = len(project.get_messages())
                preconditions.add_to_history(project.model3d, block.caption, block.code)
                messages = _raw_messages(project)[before:]
                _emit({"command": "build-ir", "stage": "block", "title": block.caption, "messages": messages})
                if any("error" in str(item.get("type", "")).lower() for item in messages):
                    raise RuntimeError(f"CST error after {block.caption}: {messages}")
            project.save()
            actual = _parameters(project)
            mismatches = {p["name"]: [p["value"], actual.get(p["name"])]
                          for p in document["parameters"]
                          if not math.isclose(float(actual.get(p["name"], "nan")), p["value"], rel_tol=0., abs_tol=1e-7)}
            if mismatches:
                raise RuntimeError(f"parameter read-back mismatch: {mismatches}")
            _emit({"command": "build-ir", "stage": "after", "session": guard.info.to_json(),
                   "project": str(target), "blocks": len(blocks), "parameters": actual,
                   "shape_count": int(project.model3d.Solid.GetNumberOfShapes()),
                   "drc": checks["status"]})
        finally:
            _close(project)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """Open a project read-only from the caller's perspective and report identity.

    CST may generate companion caches merely by opening a project, so callers
    verifying an archive must first copy the package into ``cst_runs``.  This
    command never saves or changes model history.
    """
    observation_path = getattr(args, "observation", None)
    if observation_path:
        repo = Path(__file__).resolve().parents[3]
        if args.pid is None or args.no_quiet:
            raise ValueError("geometry observation requires an explicit task PID and quiet mode")
        Path(args.project).resolve().relative_to(repo / "cst_runs")
        observation_path = Path(observation_path).resolve()
        observation_path.relative_to(repo / "cst_runs")
        if observation_path.exists() or observation_path.with_suffix(".txt").exists():
            raise FileExistsError("observation output must be new")
    with _session(args) as guard:
        project = guard.open_project(args.project)
        model3d = project.model3d
        try:
            if observation_path:
                sys.path.insert(0, str(repo / "MCP/CST-CAD/src"))
                from cst_cad.observation import VBA_TEMPLATE, parse
                scratch = observation_path.with_suffix(".txt")
                scratch.parent.mkdir(parents=True, exist_ok=True)
                code = VBA_TEMPLATE.format(output=str(scratch))
                # Fixed, read-only geometry query; never added to History.
                project.model3d._execute_vba_code("Sub Main\n" + code + "\nEnd Sub")
                observed = parse(scratch.read_text(encoding="utf-8", errors="replace"))
                if not observed["entities"] or not observed["parameters"]:
                    raise RuntimeError("CST geometry readback is incomplete")
                observed.update(project_path=str(Path(args.project).resolve()),
                                producer="Guardian Solid.GetLooseBoundingBoxOfShape", pid=args.pid)
                observation_path.write_text(json.dumps(observed, indent=2) + "\n", encoding="utf-8")
            shapes: list[str] = []
            shape_error = None
            try:
                count = int(model3d.Solid.GetNumberOfShapes())
                shapes = sorted(
                    str(model3d.Solid.GetNameOfShapeFromIndex(index))
                    for index in range(count)
                )
            except Exception as exc:
                count = 0
                shape_error = repr(exc)[:300]
            _emit(
                {
                    "command": "inspect",
                    "stage": "after",
                    "session": guard.info.to_json(),
                    "project": str(Path(args.project).resolve()),
                    "parameters": _parameters(project),
                    "shape_count": count,
                    "shape_names": shapes,
                    "shape_error": shape_error,
                    "messages_tail": _messages(project),
                }
            )
        finally:
            _close(project)
    return 0


def cmd_vba(args: argparse.Namespace) -> int:
    """Open a project and add one named VBA block to the history tree."""
    with _session(args) as guard:
        project = guard.open_project(args.project)
        _emit(
            {
                "command": "vba",
                "stage": "before",
                "session": guard.info.to_json(),
                "project": args.project,
            }
        )
        try:
            preconditions.add_to_history(project.model3d, args.title, args.code)
            _emit({"command": "vba", "stage": "after", "title": args.title})
        finally:
            _close(project)
    return 0


def cmd_msgbox(args: argparse.Namespace) -> int:
    """Manufacture a real CST-owned modal dialog and block on it.

    Uses transient VBA execution rather than ``add_to_history`` on purpose: a
    ``MsgBox`` written into the history tree would persist in the project and
    re-fire on every later rebuild, corrupting the working copy it was meant to
    test against.
    """
    with _session(args) as guard:
        project = guard.open_project(args.project)
        _emit(
            {
                "command": "msgbox",
                "stage": "before",
                "session": guard.info.to_json(),
                "project": args.project,
                "text": args.text,
            }
        )
        code = f'Sub Main\nMsgBox "{args.text}", {args.buttons}\nEnd Sub'
        try:
            project.model3d._execute_vba_code(code)
            _emit({"command": "msgbox", "stage": "after", "text": args.text})
        finally:
            _close(project)
    return 0


def _close(project) -> None:
    """Close the project so the next worker does not meet an 'already open' prompt."""
    try:
        project.close()
    except Exception:
        pass


def cmd_set_parameter(args: argparse.Namespace) -> int:
    """Change a parameter through the guarded Parameter List route.

    Goes through :func:`cst_guardian.preconditions.set_parameter` rather than
    calling ``StoreParameter`` directly, because CST accepts a garbage value, an
    expression referring to nothing, and an unknown parameter name (which it
    silently creates) without a single message.  The guard also reads the value
    back through the numeric accessor, since the string accessor returns the
    stored expression and would happily echo garbage.
    """
    with _session(args) as guard:
        project = guard.open_project(args.project)
        before = _parameters(project)
        _emit(
            {
                "command": "set-parameter",
                "stage": "before",
                "session": guard.info.to_json(),
                "parameter": args.name,
                "old_value": before.get(args.name),
                "new_value": args.value,
            }
        )
        try:
            result = preconditions.set_parameter(
                project.model3d, args.name, args.value
            )
            _emit(
                {
                    "command": "set-parameter",
                    "stage": "after",
                    **result,
                    "messages_tail": _messages(project),
                }
            )
        finally:
            _close(project)
    return 0


def cmd_sleep(args: argparse.Namespace) -> int:
    """Hold a CST session open and do nothing, so the watchdog has something to reap.

    L2 must be provable without a dialog: a worker can also stop making progress
    for reasons the guardian cannot see (a solver that never converges, a hung
    COM call).  Sleeping inside a live session reproduces that without needing
    CST to misbehave.
    """
    with _session(args) as guard:
        _emit({"command": "sleep", "stage": "before", "session": guard.info.to_json()})
        time.sleep(args.seconds)
        _emit({"command": "sleep", "stage": "after", "seconds": args.seconds})
    return 0


def cmd_iterate(args: argparse.Namespace) -> int:
    """Apply several parameter values in one session, verifying each read-back.

    One successful parameter change proves the call works; ``cst_iterate`` needs
    it to keep working, so this repeats it in a single session and reports the
    value CST hands back each time.  A change that silently stops taking effect
    after the first iteration would otherwise look identical to success.
    """
    values = [v.strip() for v in args.values.split(",") if v.strip()]
    with _session(args) as guard:
        project = guard.open_project(args.project)
        model3d = project.model3d
        _emit(
            {
                "command": "iterate",
                "stage": "before",
                "session": guard.info.to_json(),
                "parameter": args.name,
                "start_value": _parameters(project).get(args.name),
                "requested": values,
            }
        )
        applied = []
        try:
            for value in values:
                started = time.monotonic()
                result = preconditions.set_parameter(model3d, args.name, value)
                applied.append(
                    {
                        "requested": value,
                        "read_back": _parameters(project).get(args.name),
                        "evaluated": result["after"],
                        "elapsed_s": round(time.monotonic() - started, 2),
                    }
                )
            project.save()
            _emit(
                {
                    "command": "iterate",
                    "stage": "after",
                    "applied": applied,
                    "all_took_effect": all(
                        str(a["read_back"]) == str(a["requested"]) for a in applied
                    ),
                    "messages_tail": _messages(project),
                }
            )
        finally:
            _close(project)
    return 0


def cmd_solve(args: argparse.Namespace) -> int:
    """Run the solver and export Touchstone, which is the only reviewable output.

    Solver output under a companion ``Result/`` directory is regenerable cache, so
    a run whose only product is that cache cannot be re-reviewed without
    re-solving.  The export is what makes the run evidence.
    """
    import importlib

    with _session(args) as guard:
        project = guard.open_project(args.project)
        _emit({"command": "solve", "stage": "before", "session": guard.info.to_json()})
        try:
            project.save()
            messages_before = len(_raw_messages(project))
            started = time.monotonic()
            project.model3d.run_solver()
            solve_s = round(time.monotonic() - started, 2)
            project.save()
            _emit({"command": "solve", "stage": "solved", "solve_s": solve_s})
            export = importlib.import_module(
                "cst.post_processing.s_parameters"
            ).export_touchstone
            target = Path(args.export).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            # CST appends the port-count suffix itself, so a caller-supplied one
            # produces "s-parameters.s2p.s2p".  The port count is not known here,
            # which is precisely why CST is left to choose it.
            stem = target
            if re.fullmatch(r"\.s\d+p", target.suffix, re.IGNORECASE):
                stem = target.with_suffix("")
            native_impedance = getattr(args, "native_port_impedance", False)
            export(project, str(stem), impedance=50.0, export_type="S", format="RI",
                   renormalize=not native_impedance)
            produced = sorted(str(p) for p in stem.parent.glob(stem.name + ".s*p"))
            messages = [str(item) for item in _raw_messages(project)[messages_before:]]
            incomplete = [m for m in messages if any(text in m.lower() for text in
                          ("could not have been satisfied", "solver aborted", "solver failed"))]
            _emit(
                {
                    "command": "solve",
                    "stage": "after",
                    "solve_s": solve_s,
                    "export": produced,
                    "export_exists": bool(produced),
                    "export_normalization": "native modal ports" if native_impedance else "50 ohm",
                    "messages_tail": messages,
                    "energy_criterion_count": sum("steady state energy criterion met" in m.lower() for m in messages),
                    "converged": False if incomplete else (True if any(
                        "steady state energy criterion met" in m.lower() for m in messages) else None),
                }
            )
            if incomplete:
                raise RuntimeError(f"Solver returned without convergence: {incomplete}")
        finally:
            _close(project)
    return 0


def _observe(model3d, case) -> dict[str, object]:
    """Read the state a conflict case could damage, through CST's own accessors.

    Reading back is the whole point: CST's way of refusing a parameter change is
    to log a warning and keep the old value, so "did it work" cannot be answered
    from the Python return value.
    """
    state: dict[str, object] = {}
    try:
        count = int(model3d.Solid.GetNumberOfShapes())
        state["shapes"] = count
        # Names, not just the count: a duplicate name and a merged overlap both
        # leave the count unchanged for different reasons.
        state["shape_names"] = sorted(
            str(model3d.Solid.GetNameOfShapeFromIndex(i)) for i in range(count)
        )
    except Exception as exc:
        state["shapes"] = f"error: {exc!r}"[:120]
    try:
        state["parameter_count"] = int(model3d.GetNumberOfParameters())
    except Exception as exc:
        state["parameter_count"] = f"error: {exc!r}"[:120]
    if case.watch_parameter:
        name = case.watch_parameter
        for label, call in (
            ("value", lambda: model3d.GetParameterSValue(_index_of(model3d, name))),
            ("expression", lambda: model3d.RestoreParameterExpression(name)),
            ("exists", lambda: bool(model3d.DoesParameterExist(name))),
        ):
            try:
                state[f"{name}.{label}"] = call()
            except Exception as exc:
                state[f"{name}.{label}"] = f"error: {exc!r}"[:120]
    for name in case.watch_exists:
        try:
            state[f"{name}.exists"] = bool(model3d.DoesParameterExist(name))
        except Exception as exc:
            state[f"{name}.exists"] = f"error: {exc!r}"[:120]
    return state


def _index_of(model3d, name: str) -> int:
    for index in range(int(model3d.GetNumberOfParameters())):
        if model3d.GetParameterName(index) == name:
            return index
    raise LookupError(name)


def cmd_conflict(args: argparse.Namespace) -> int:
    """Run one registered conflict case and report what CST did about it."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from conflict_cases import CASES_BY_ID

    case = CASES_BY_ID[args.case]
    with _session(args) as guard:
        project = guard.open_project(args.project)
        model3d = project.model3d
        before_messages = _raw_messages(project)
        before = _observe(model3d, case)
        _emit(
            {
                "command": "conflict",
                "stage": "before",
                "case": case.case_id,
                "category": case.category,
                "session": guard.info.to_json(),
                "state": before,
            }
        )
        error = None
        started = time.monotonic()
        try:
            exec(case.statement, {"model3d": model3d, "project": project})  # noqa: S102
        except Exception as exc:
            error = repr(exc)[:900]
        elapsed = round(time.monotonic() - started, 2)
        after = _observe(model3d, case)
        after_messages = _raw_messages(project)
        _emit(
            {
                "command": "conflict",
                "stage": "after",
                "case": case.case_id,
                "elapsed_s": elapsed,
                "error": error,
                "state": before,
                "state_after": after,
                "new_messages": after_messages[len(before_messages) :],
            }
        )
        # The project is deliberately NOT saved: a conflict case must not be able
        # to persist damage into the copy the next case might reuse.
        _close(project)
    return 0


#: Calls CST measurably accepts without complaint, each paired with the guard
#: that must refuse it.  Kept next to the conflict matrix on purpose: every entry
#: here exists because a row of that matrix came back "applied".
GUARD_ATTEMPTS: tuple[tuple[str, str], ...] = (
    ("unknown_parameter_name", "set_parameter(m, 'l3_typo', 14.0)"),
    ("non_numeric_value", "set_parameter(m, 'l3', 'not_a_number')"),
    ("undefined_reference", "set_parameter(m, 'l3', 'zz_undefined*2')"),
    ("self_reference", "set_parameter(m, 'l3', 'l3+1')"),
    ("empty_value", "set_parameter(m, 'l3', '')"),
    (
        "out_of_approved_range",
        "set_parameter(m, 'wh', 0.0, allowed_range=(0.28, 0.43))",
    ),
    ("delete_parameter_in_use", "delete_parameter(m, 'l3')"),
    (
        "store_parameter_in_history",
        "add_to_history(m, 'probe', 'StoreParameter(\"l3\", \"13.0\")\\n')",
    ),
    # Only ``Rebuild`` here: a block that also stored a parameter would be
    # refused for that instead, and the nested-rebuild guard would go untested.
    (
        "nested_rebuild_in_history",
        "add_to_history(m, 'probe', 'Solid.Rename \"a\", \"b\"\\nRebuild\\n')",
    ),
    ("msgbox_in_history", "add_to_history(m, 'probe', 'MsgBox \"blocked\"\\n')"),
)


def cmd_guard(args: argparse.Namespace) -> int:
    """Attempt every known-dangerous call through the guards, against real CST.

    Two things are asserted per attempt: the guard refused it, and the model is
    byte-for-byte the state it started in.  The second matters as much as the
    first -- a guard that raises after CST has already accepted the value would
    leave the next call reading a model that contains what we refused.
    """
    from cst_guardian.preconditions import (  # noqa: F401 - used by the attempts
        GuardViolation,
        add_to_history,
        delete_parameter,
        set_parameter,
    )

    with _session(args) as guard:
        project = guard.open_project(args.project)
        model3d = project.model3d
        namespace = {
            "m": model3d,
            "set_parameter": set_parameter,
            "delete_parameter": delete_parameter,
            "add_to_history": add_to_history,
        }
        baseline = _parameters(project)
        _emit(
            {
                "command": "guard",
                "stage": "before",
                "session": guard.info.to_json(),
                "parameters": baseline,
            }
        )
        attempts = []
        try:
            for label, statement in GUARD_ATTEMPTS:
                refusal = None
                unexpected = None
                try:
                    exec(statement, namespace)  # noqa: S102 - literal source above
                except GuardViolation as exc:
                    refusal = str(exc)[:400]
                except Exception as exc:
                    unexpected = repr(exc)[:400]
                state = _parameters(project)
                attempts.append(
                    {
                        "attempt": label,
                        "statement": statement,
                        "refused": refusal is not None,
                        "refusal": refusal,
                        "unexpected_error": unexpected,
                        "model_unchanged": state == baseline,
                        "changed_parameters": {
                            k: [baseline.get(k), state.get(k)]
                            for k in sorted(set(baseline) | set(state))
                            if baseline.get(k) != state.get(k)
                        },
                    }
                )
            _emit(
                {
                    "command": "guard",
                    "stage": "after",
                    "attempts": attempts,
                    "all_refused": all(a["refused"] for a in attempts),
                    "model_never_changed": all(a["model_unchanged"] for a in attempts),
                    "messages_tail": _messages(project),
                }
            )
        finally:
            _close(project)
    return 0


def _raw_messages(project) -> list[dict[str, object]]:
    try:
        return [dict(m) if isinstance(m, dict) else {"text": str(m)} for m in project.get_messages()]
    except Exception:
        return []


def _parameters(project) -> dict[str, object]:
    """Read the parameter table through CST's own object model.

    ``model3d`` exposes the VBA object model directly, so the accessors are
    ``GetNumberOfParameters`` / ``GetParameterName`` / ``GetParameterSValue``.  An
    earlier version called a ``get_all_parameter_names`` helper that does not
    exist and swallowed the ``AttributeError``, silently reporting no parameters.
    """
    model3d = project.model3d
    values: dict[str, object] = {}
    try:
        count = int(model3d.GetNumberOfParameters())
    except Exception as exc:
        return {"_error": repr(exc)}
    for index in range(count):
        try:
            name = model3d.GetParameterName(index)
            values[name] = model3d.GetParameterSValue(index)
        except Exception:
            continue
    return values


def _messages(project) -> list[str]:
    try:
        messages = project.get_messages()
    except Exception:
        return []
    if isinstance(messages, list):
        return [str(m) for m in messages[-20:]]
    return [str(messages)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, default=None, help="attach to this CST pid")
    parser.add_argument("--launch", action="store_true", help="launch CST if none is running")
    parser.add_argument(
        "--no-quiet",
        action="store_true",
        help="do not enforce quiet mode (required to exercise the L3 dialog table)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("probe").set_defaults(func=cmd_probe)

    build = sub.add_parser("build-ir", help="Build validated IR in a fresh verification working copy")
    build.add_argument("--ir", required=True)
    build.add_argument("--project", required=True)
    build.set_defaults(func=cmd_build_ir)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("project")
    inspect.add_argument("--observation", help="Read geometry bounds and parameters into a new run-local JSON")
    inspect.set_defaults(func=cmd_inspect)

    vba = sub.add_parser("vba")
    vba.add_argument("--project", required=True)
    vba.add_argument("--title", default="guardian probe")
    vba.add_argument("--code", required=True)
    vba.set_defaults(func=cmd_vba)

    msgbox = sub.add_parser("msgbox")
    msgbox.add_argument("--project", required=True)
    msgbox.add_argument("--text", required=True)
    msgbox.add_argument("--buttons", type=int, default=4, help="VBA MsgBox flags; 4 = Yes/No")
    msgbox.set_defaults(func=cmd_msgbox)

    param = sub.add_parser("set-parameter")
    param.add_argument("--project", required=True)
    param.add_argument("--name", required=True)
    param.add_argument("--value", required=True)
    param.set_defaults(func=cmd_set_parameter)

    napping = sub.add_parser("sleep")
    napping.add_argument("--seconds", type=float, default=600.0)
    napping.set_defaults(func=cmd_sleep)

    iterate = sub.add_parser("iterate")
    iterate.add_argument("--project", required=True)
    iterate.add_argument("--name", required=True)
    iterate.add_argument("--values", required=True, help="comma-separated values")
    iterate.set_defaults(func=cmd_iterate)

    solve = sub.add_parser("solve")
    solve.add_argument("--project", required=True)
    solve.add_argument("--export", required=True, help="Touchstone output path")
    solve.add_argument("--native-port-impedance", action="store_true",
                       help="Keep modal port normalization, e.g. for hollow waveguide validation")
    solve.set_defaults(func=cmd_solve)

    conflict = sub.add_parser("conflict")
    conflict.add_argument("--project", required=True)
    conflict.add_argument("--case", required=True)
    conflict.set_defaults(func=cmd_conflict)

    guard_check = sub.add_parser("guard")
    guard_check.add_argument("--project", required=True)
    guard_check.set_defaults(func=cmd_guard)

    args = parser.parse_args(argv)
    # Emitted before anything can block, so a killed worker still shows how far it
    # got.  Without it, a hang during connect or open is indistinguishable from a
    # hang in the work itself.
    _emit(
        {
            "command": args.command,
            "stage": "start",
            "pid_requested": args.pid,
            "quiet_enforced": not args.no_quiet,
        }
    )
    try:
        from cst_trace import trace_function
        code = trace_function(args.func)(args)
    except Exception as exc:  # surfaced through the supervisor's stderr log
        _emit({"error_type": type(exc).__name__, "error": str(exc)})
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
