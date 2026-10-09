#!/usr/bin/env python3
"""Find the parameter-change mechanism that actually returns, with evidence.

``cst_iterate`` applies a parameter delta on every iteration, so the call that
does it must be known to return and to take effect.  Choosing wrongly does not
raise: CST refuses the change and then blocks forever inside a history rebuild.

Each variant therefore runs

* in its own subprocess under a timeout, because a blocked variant cannot be
  detected any other way;
* against its own fresh copy of a pristine project, because a killed attempt
  leaves the project dirty and locked, and a later variant measured on that
  wreckage reports the previous variant's damage as its own;
* in its own freshly launched CST instance, for the same reason at process
  level -- a stuck history rebuild poisons every subsequent call on that
  instance.

CST's message queue is read after every attempt.  It is the only place where CST
explains a refusal ("Prevented attempt to change the value for parameter ...
inside history rebuild"), and that text is what distinguishes a mechanism that
silently did nothing from one that worked.

Usage:
    python tools/probe_parameter_apply.py --source <pristine.cst> \
        --workdir <scratch dir> --name l3 --value 14.25
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cst_guardian.paths import running_design_environment_pids  # noqa: E402

# Every statement operates on ``project`` / ``model3d`` and is measured alone.
VARIANTS: dict[str, str] = {
    # Does a history block work at all on a clean instance?  Without this the
    # blocking of the parameter variants below cannot be attributed to the
    # parameter change rather than to ``add_to_history`` itself.
    "history_benign": (
        "model3d.add_to_history("
        "'guardian benign', 'ReportInformationToWindow(\"guardian benign\")\\n')"
    ),
    # The Parameter List route CST's own warning message recommends.
    "store_direct_only": "model3d.StoreParameter({name!r}, {value!r})",
    "store_direct_then_rebuild": (
        "model3d.StoreParameter({name!r}, {value!r}); model3d.Rebuild()"
    ),
    "store_direct_then_parametric_update": (
        "model3d.StoreParameter({name!r}, {value!r}); "
        "model3d.RebuildOnParametricChange(False, False)"
    ),
    # The history/macro routes, kept so the failure mode stays documented.
    "history_store_only": (
        "model3d.add_to_history('set {name}', 'StoreParameter(\"{name}\", \"{value}\")\\n')"
    ),
    "execute_store_only": (
        "model3d._execute_vba_code("
        "'Sub Main\\nStoreParameter(\"{name}\", \"{value}\")\\nEnd Sub')"
    ),
}

RUNNER = r"""
import json, os, sys, time
sys.path.insert(0, r"{guardian}")
from cst_guardian import GuardedSession

T0 = time.monotonic()


def mark(stage, **extra):
    print(json.dumps({{"stage": stage, "t": round(time.monotonic() - T0, 2), **extra}}),
          flush=True)


def parameters(model3d):
    out = {{}}
    try:
        count = int(model3d.GetNumberOfParameters())
    except Exception as exc:
        return {{"_error": repr(exc)}}
    for index in range(count):
        try:
            out[model3d.GetParameterName(index)] = model3d.GetParameterSValue(index)
        except Exception:
            continue
    return out


def messages(project):
    try:
        return [m for m in project.get_messages()]
    except Exception as exc:
        return [{{"text": repr(exc), "type": "PROBE_ERROR"}}]


with GuardedSession(launch_if_needed=True, force_new=True,
                   enforce_quiet={quiet}) as guard:
    mark("launched", pid=guard.info.pid)
    project = guard.open_project(r"{project}")
    model3d = project.model3d
    mark("opened", before=parameters(model3d).get({name!r}))
    started = time.monotonic()
    try:
        {statement}
        error = None
    except Exception as exc:
        error = repr(exc)[:600]
    mark("applied", apply_s=round(time.monotonic() - started, 2), error=error)
    mark("read_back", after=parameters(model3d).get({name!r}))
    mark("messages", messages=messages(project))
    started = time.monotonic()
    try:
        project.save()
        save_error = None
    except Exception as exc:
        save_error = repr(exc)[:300]
    mark("saved", save_s=round(time.monotonic() - started, 2), error=save_error)
    started = time.monotonic()
    try:
        project.close()
        close_error = None
    except Exception as exc:
        close_error = repr(exc)[:300]
    mark("closed", close_s=round(time.monotonic() - started, 2), error=close_error)
mark("session_exited")
os._exit(0)
"""


def _stages(stdout: str) -> list[dict]:
    stages = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            stages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return stages


def _reap(leaked: list[int]) -> list[dict]:
    """Shut down CST instances a killed child left behind.

    A stranded instance holds the project lock, so the next variant would fail
    with "already open in another instance" and be recorded as a variant defect.
    """
    reaped = []
    for pid in leaked:
        code = (
            "import sys; sys.path.insert(0, r'%s');"
            "from cst_guardian.paths import ensure_cst_paths; ensure_cst_paths();"
            "import cst.interface as ci; ci.DesignEnvironment.connect(%d).close()"
            % (str(Path(__file__).resolve().parents[1]), pid)
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
            )
            graceful = proc.returncode == 0
        except subprocess.TimeoutExpired:
            graceful = False
        if not graceful:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True
            )
        reaped.append({"pid": pid, "graceful": graceful})
    return reaped


def run_variant(
    label: str,
    statement: str,
    *,
    source: Path,
    workdir: Path,
    name: str,
    value: str,
    quiet: bool,
    timeout: float,
) -> dict:
    project = _fresh_copy(source, workdir / label)
    code = RUNNER.format(
        guardian=str(Path(__file__).resolve().parents[1]),
        project=str(project),
        statement=statement.format(name=name, value=value),
        name=name,
        quiet="True" if quiet else "False",
    )
    before_pids = set(running_design_environment_pids())
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        outcome = "returned" if proc.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        outcome = "blocked"
    wall_s = round(time.monotonic() - started, 2)
    stages = _stages(out)
    leaked = sorted(set(running_design_environment_pids()) - before_pids)
    return {
        "variant": label,
        "statement": statement.format(name=name, value=value),
        "outcome": outcome,
        "wall_s": wall_s,
        "reached": [s["stage"] for s in stages],
        "stages": stages,
        "stderr": err.strip()[-600:],
        "leaked_pids": leaked,
        "reaped": _reap(leaked) if leaked else [],
    }


def _fresh_copy(source: Path, target_dir: Path) -> Path:
    """Copy the pristine project and its companion directory into ``target_dir``."""
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    companion = source.with_suffix("")
    if companion.is_dir():
        shutil.copytree(companion, target_dir / companion.name)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="pristine .cst")
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--only", action="append", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    selected = {k: v for k, v in VARIANTS.items() if not args.only or k in args.only}
    results = []
    for label, statement in selected.items():
        result = run_variant(
            label,
            statement,
            source=args.source.resolve(),
            workdir=args.workdir.resolve(),
            name=args.name,
            value=args.value,
            quiet=args.quiet,
            timeout=args.timeout,
        )
        results.append(result)
        applied = next((s for s in result["stages"] if s["stage"] == "applied"), {})
        read_back = next((s for s in result["stages"] if s["stage"] == "read_back"), {})
        print(
            "%-36s %-9s wall=%6.1fs apply=%s after=%r leaked=%s"
            % (
                label,
                result["outcome"],
                result["wall_s"],
                applied.get("apply_s"),
                read_back.get("after"),
                result["leaked_pids"],
            )
        )
        if applied.get("error"):
            print("    apply error:", applied["error"][:300])
        time.sleep(3.0)

    payload = {
        "source": str(args.source.resolve()),
        "parameter": {"name": args.name, "value": args.value},
        "quiet_mode": args.quiet,
        "timeout_s": args.timeout,
        "variants": results,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
