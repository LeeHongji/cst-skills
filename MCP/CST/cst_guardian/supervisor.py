"""Parent-side supervision of a CST worker subprocess.

The COM session lives in a child process so that a blocked call can be killed
without taking down the supervisor.  Putting the session in the server process
instead would mean one unanswered prompt freezes knowledge queries too.

External PID scopes retain their existing CST lifecycle. For workers creating a
new CST instance, a Windows kernel job contains the entire newly created process
tree and reaps it even if the supervisor dies. Unrelated CST is never assigned.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Sequence

from .paths import cst_instance_pids, running_cst_pids
from .policy import KNOWN_RULES, Decision, DialogRule, decide, normalize_button_text
from .win32_dialogs import (
    ClickRefused,
    DialogInfo,
    capture_window,
    dialog_is_gone,
    enumerate_dialogs,
    main_windows_for_pid,
    press_button,
    release_dialog,
    unreadable_modals,
)

Outcome = Literal["completed", "worker_failed", "timeout", "escalated", "blocked"]

#: How long to wait for a clicked dialog to disappear before treating the click
#: as ineffective.
_CLICK_SETTLE_S = 2.0
#: Grace period between terminate() and kill().
_KILL_GRACE_S = 5.0
#: How long the same unreadable modal must keep CST's main window disabled before
#: it counts as a stall rather than as a progress window. CST disables its own main
#: window during legitimate long operations too, so this cannot be instant; it only
#: has to be far below the run timeout to be worth having.
_UNREADABLE_MODAL_GRACE_S = 120.0


@dataclass
class GuardReport:
    outcome: Outcome
    exit_code: int | None
    elapsed_s: float
    worker_argv: list[str]
    watched_pids: list[int]
    events: list[dict[str, object]] = field(default_factory=list)
    log_dir: Path | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "completed" and self.exit_code == 0

    @property
    def dialogs_answered(self) -> list[dict[str, object]]:
        return [e for e in self.events if e.get("action") == "click"]

    @property
    def escalations(self) -> list[dict[str, object]]:
        return [e for e in self.events if e.get("action") == "escalate"]

    @property
    def released(self) -> list[dict[str, object]]:
        return [e for e in self.events if e.get("action") == "released"]

    def to_json(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "elapsed_s": round(self.elapsed_s, 3),
            "worker_argv": list(self.worker_argv),
            "watched_pids": list(self.watched_pids),
            "dialogs_answered": len(self.dialogs_answered),
            "escalations": len(self.escalations),
            "orphans_released": len(self.released),
            "events": self.events,
            "log_dir": str(self.log_dir) if self.log_dir else None,
        }


class _DialogTracker:
    """Debounces dialog sightings so transient progress windows are ignored."""

    def __init__(self, stable_polls: int) -> None:
        self.stable_polls = stable_polls
        self._seen: dict[str, int] = {}
        self._handled: set[str] = set()

    def ready(self, dialog: DialogInfo) -> bool:
        key = dialog.fingerprint()
        if key in self._handled:
            return False
        count = self._seen.get(key, 0) + 1
        self._seen[key] = count
        return count >= self.stable_polls

    def mark_handled(self, dialog: DialogInfo) -> None:
        self._handled.add(dialog.fingerprint())

    def forget(self, dialog: DialogInfo) -> None:
        """Allow a dialog to be re-evaluated, e.g. after an ineffective click."""
        self._seen.pop(dialog.fingerprint(), None)


def _worker_env(env: dict[str, str] | None) -> dict[str, str]:
    """Force UTF-8 on the worker's streams.

    The log files are opened as UTF-8, but the child picks its own stdout
    encoding from the Windows ANSI code page, and CST's messages are not all
    representable there.  Observed live: a VBA syntax-error message raised
    ``UnicodeEncodeError: 'gbk' codec can't encode character`` and killed the
    worker after it had reported its starting state but before its result, which
    reads as a CST failure rather than an encoding one.
    """
    resolved = dict(os.environ if env is None else env)
    resolved.setdefault("PYTHONIOENCODING", "utf-8:backslashreplace")
    resolved.setdefault("PYTHONUTF8", "1")
    return resolved


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=_KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=_KILL_GRACE_S)


def run_guarded(
    argv: Sequence[str],
    *,
    log_dir: Path,
    timeout_s: float = 1800.0,
    cst_pids: Sequence[int] | None = None,
    cst_pid_roots: Sequence[int] | None = None,
    scope_worker_descendants: bool = False,
    poll_interval_s: float = 0.5,
    stable_polls: int = 2,
    rules: tuple[DialogRule, ...] = KNOWN_RULES,
    kill_on_escalation: bool = True,
    require_clean_start: bool = True,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> GuardReport:
    """Run ``argv`` as a worker while answering known CST dialogs.

    ``cst_pids`` is a fixed explicit set. ``cst_pid_roots`` dynamically follows
    the descendants of task-owned Design Environment processes, including
    modeler and solver helpers launched after the worker starts. If neither is
    supplied, the legacy installation-wide discovery remains available, but
    production callers must provide a scope so unrelated CST sessions are never
    observed or actuated.

    ``scope_worker_descendants`` is for a worker which creates its own new CST
    instance. Supervision then follows that worker's descendants from process
    creation, including a blocked DesignEnvironment.new call. It is mutually
    exclusive with external PID scopes; no installation-wide discovery occurs.
    On Windows 10+, kernel job containment is assigned atomically at creation;
    all newly owned descendants terminate when supervision ends or dies.

    ``require_clean_start`` refuses to begin while a prompt is already on screen.
    Starting anyway makes every observation untrustworthy: the watcher would see
    the pre-existing prompt first and attribute it to this run.  The guardian will
    not dismiss it either, because it cannot tell an orphan from a dialog a human
    is currently reading.
    """
    if scope_worker_descendants:
        if cst_pids is not None or cst_pid_roots is not None:
            raise ValueError("worker-owned scope cannot be combined with external CST PIDs")
        cst_pids, cst_pid_roots = (), ()
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "worker-stdout.txt"
    stderr_path = log_dir / "worker-stderr.txt"

    started = time.monotonic()
    tracker = _DialogTracker(stable_polls=stable_polls)
    #: First time each unreadable modal was seen, so a progress window that clears
    #: itself never accumulates dwell, and a genuine stall reports once.
    modal_first_seen: dict[str, float] = {}
    modal_reported: set[str] = set()
    events: list[dict[str, object]] = []
    watched: set[int] = set(_target_pids(cst_pids, cst_pid_roots))
    outcome: Outcome = "completed"

    if require_clean_start:
        preexisting = _preflight(events, cst_pids, cst_pid_roots, log_dir)
        if preexisting:
            report = GuardReport(
                outcome="blocked",
                exit_code=None,
                elapsed_s=time.monotonic() - started,
                worker_argv=list(argv),
                watched_pids=sorted(watched),
                events=events,
                log_dir=log_dir,
            )
            (log_dir / "guard-report.json").write_text(
                json.dumps(report.to_json(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return report

    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open(
        "w", encoding="utf-8"
    ) as err:
        contained = scope_worker_descendants and os.name == 'nt'
        options=dict(stdout=out,stderr=err,cwd=str(cwd) if cwd else None,env=_worker_env(env))
        if contained:
            from .windows_job import WindowsJobProcess
            process=WindowsJobProcess(list(argv),**options)
        else:
            process=subprocess.Popen(list(argv),**options,
                **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
        try:
            if scope_worker_descendants:
                cst_pid_roots = (process.pid,)
                events.append({"action": "scope", "worker_pid": process.pid,
                               "reason": "new task-owned CST descendants only",
                               "kernel_job_containment": contained})
            while True:
                if process.poll() is not None:
                    outcome = "completed" if process.returncode == 0 else "worker_failed"
                    break
                if time.monotonic() - started > timeout_s:
                    outcome = "timeout"
                    _record_timeout_dialogs(
                        events,
                        watched,
                        cst_pids,
                        cst_pid_roots,
                        log_dir,
                        len(events),
                    )
                    _terminate(process)
                    _release_orphans(events, cst_pids, cst_pid_roots, log_dir)
                    break

                pids = _target_pids(cst_pids, cst_pid_roots)
                watched.update(pids)
                escalated = False
                for pid in pids:
                    for dialog in enumerate_dialogs(pid):
                        if not tracker.ready(dialog):
                            continue
                        decision = decide(dialog, rules)
                        event = _handle(decision, pid, log_dir, len(events))
                        events.append(event)
                        if decision.action == "click" and event.get("effective"):
                            tracker.mark_handled(dialog)
                        elif decision.action == "click":
                            tracker.forget(dialog)
                            escalated = True
                        else:
                            tracker.mark_handled(dialog)
                            escalated = True
                    modals = unreadable_modals(pid)
                    live = {f"{pid}:{modal.fingerprint()}" for modal in modals}
                    for stale in [k for k in modal_first_seen if k.startswith(f"{pid}:")]:
                        if stale not in live:
                            # The modal went away on its own: it was a progress window,
                            # not a stall, so its dwell must not carry over.
                            modal_first_seen.pop(stale, None)
                    for modal in modals:
                        key = f"{pid}:{modal.fingerprint()}"
                        first = modal_first_seen.setdefault(key, time.monotonic())
                        held_s = time.monotonic() - first
                        if held_s < _UNREADABLE_MODAL_GRACE_S or key in modal_reported:
                            continue
                        modal_reported.add(key)
                        event: dict[str, object] = {
                            "index": len(events) + 1,
                            "pid": pid,
                            "action": "escalate",
                            "reason": "unreadable_modal",
                            "held_s": round(held_s, 1),
                            "modal": modal.to_json(),
                            "note": (
                                "CST's main window has been disabled by a modal that carries no "
                                "readable controls, so no policy can defend answering it"
                            ),
                        }
                        shot = (
                            log_dir
                            / f"unreadable-modal-{len(events) + 1:03d}-{modal.fingerprint()}.png"
                        )
                        try:
                            event["screenshot"] = str(shot) if capture_window(modal.hwnd, shot) else None
                        except Exception:  # noqa: BLE001
                            event["screenshot"] = None
                        events.append(event)
                        escalated = True
                if escalated and kill_on_escalation:
                    outcome = "escalated"
                    _terminate(process)
                    _release_orphans(events, cst_pids, cst_pid_roots, log_dir)
                    break
                time.sleep(poll_interval_s)
        finally:
            try:
                if process.poll() is None:
                    _terminate(process)
            finally:
                if contained:
                    events.append({'action':'owned-process-cleanup','kernel_job':process.close()})

    report = GuardReport(
        outcome=outcome,
        exit_code=process.returncode,
        elapsed_s=time.monotonic() - started,
        worker_argv=list(argv),
        watched_pids=sorted(watched),
        events=events,
        log_dir=log_dir,
    )
    (log_dir / "guard-report.json").write_text(
        json.dumps(report.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _screenshot(dialog: DialogInfo, log_dir: Path, index: int) -> str | None:
    path = log_dir / f"dialog-{index + 1:03d}-{dialog.fingerprint()}.png"
    try:
        return str(path) if capture_window(dialog.hwnd, path) else None
    except Exception:
        return None


def _handle(
    decision: Decision, pid: int, log_dir: Path, index: int
) -> dict[str, object]:
    """Act on ``decision`` and return the event record.

    The screenshot is always taken before acting, so the evidence shows the
    dialog as it appeared rather than after it was dismissed.
    """
    event = decision.to_json()
    event["observed_at_unix"] = time.time()
    event["cst_pid"] = pid
    event["screenshot"] = _screenshot(decision.dialog, log_dir, index)

    if decision.action != "click":
        event["effective"] = False
        return event

    assert decision.button is not None
    try:
        press_button(decision.dialog, decision.button)
    except ClickRefused as exc:
        event["action"] = "escalate"
        event["detail"] = f"click refused: {exc}"
        event["effective"] = False
        return event

    deadline = time.monotonic() + _CLICK_SETTLE_S
    while time.monotonic() < deadline:
        if dialog_is_gone(decision.dialog.hwnd):
            event["effective"] = True
            return event
        time.sleep(0.1)
    event["action"] = "escalate"
    event["detail"] = (
        f"clicked {decision.button.text!r} but the dialog is still on screen after "
        f"{_CLICK_SETTLE_S}s"
    )
    event["effective"] = False
    return event


def _target_pids(
    cst_pids: Sequence[int] | None,
    cst_pid_roots: Sequence[int] | None,
) -> list[int]:
    if cst_pids is None and cst_pid_roots is None:
        return running_cst_pids()
    resolved = set(cst_pids or ())
    for root_pid in cst_pid_roots or ():
        resolved.update(cst_instance_pids(int(root_pid)))
    return sorted(resolved)


def _preflight(
    events: list[dict[str, object]],
    cst_pids: Sequence[int] | None,
    cst_pid_roots: Sequence[int] | None,
    log_dir: Path,
) -> bool:
    """Record any prompt already on screen before the worker starts."""
    pids = _target_pids(cst_pids, cst_pid_roots)
    found = False
    for pid in pids:
        for dialog in enumerate_dialogs(pid):
            found = True
            events.append(
                {
                    "action": "blocked",
                    "detail": (
                        "a prompt was already on screen before this run started; "
                        "dismiss it (or release the orphan from the previous run) "
                        "before retrying"
                    ),
                    "observed_at_unix": time.time(),
                    "cst_pid": pid,
                    "screenshot": _screenshot(dialog, log_dir, len(events)),
                    "dialog": dialog.to_json(),
                    "effective": False,
                }
            )
    return found


def _release_orphans(
    events: list[dict[str, object]],
    cst_pids: Sequence[int] | None,
    cst_pid_roots: Sequence[int] | None,
    log_dir: Path,
) -> None:
    """Dismiss prompts left behind after the worker was killed.

    An orphaned prompt does not disappear with its caller; it keeps CST's modeller
    blocked for every later run, and a run that inherits a stale prompt reports
    the wrong dialog entirely.  The operation has already been abandoned at this
    point, so the answer cannot influence it -- but screenshots were taken before
    the kill, and the button actually pressed is recorded here.
    """
    pids = _target_pids(cst_pids, cst_pid_roots)
    for pid in pids:
        for dialog in enumerate_dialogs(pid):
            try:
                button = release_dialog(dialog)
            except Exception as exc:
                events.append(
                    {
                        "action": "release_failed",
                        "detail": f"could not release orphaned dialog: {exc}",
                        "observed_at_unix": time.time(),
                        "cst_pid": pid,
                        "dialog": dialog.to_json(),
                        "effective": False,
                    }
                )
                continue
            if button is None:
                events.append(
                    {
                        "action": "release_failed",
                        "detail": (
                            "orphaned dialog offers no standard button; CST's "
                            "modeller stays blocked until it is dismissed by hand"
                        ),
                        "observed_at_unix": time.time(),
                        "cst_pid": pid,
                        "dialog": dialog.to_json(),
                        "effective": False,
                    }
                )
                continue
            events.append(
                {
                    "action": "released",
                    "detail": (
                        "operation already abandoned; released the blocked GUI with "
                        "the least committal button available"
                    ),
                    "observed_at_unix": time.time(),
                    "cst_pid": pid,
                    "button": normalize_button_text(button.text),
                    "button_control_id": button.control_id,
                    "button_standard_name": button.standard_name,
                    "dialog": dialog.to_json(),
                    "effective": dialog_is_gone(dialog.hwnd),
                }
            )


def _record_timeout_dialogs(
    events: list[dict[str, object]],
    watched: set[int],
    cst_pids: Sequence[int] | None,
    cst_pid_roots: Sequence[int] | None,
    log_dir: Path,
    index: int,
) -> None:
    """Capture whatever is on screen when a timeout fires.

    A timeout with no readable prompt means either that the call is genuinely slow
    or that a pure-Qt modal is blocking it, and that distinction decides whether
    to raise the timeout or fix the model.  Falling back to a screenshot of CST's
    own windows is what makes the second case diagnosable at all.
    """
    pids = _target_pids(cst_pids, cst_pid_roots)
    watched.update(pids)
    found_any = False
    for pid in pids:
        for dialog in enumerate_dialogs(pid):
            found_any = True
            events.append(
                {
                    "action": "escalate",
                    "detail": "readable prompt present when the timeout fired",
                    "observed_at_unix": time.time(),
                    "cst_pid": pid,
                    "screenshot": _screenshot(dialog, log_dir, index + len(events)),
                    "dialog": dialog.to_json(),
                    "effective": False,
                }
            )
    if found_any:
        return
    for pid in pids:
        for hwnd in main_windows_for_pid(pid):
            path = log_dir / f"timeout-window-{pid}-{hwnd}.png"
            captured = False
            try:
                captured = bool(capture_window(hwnd, path))
            except Exception:
                captured = False
            events.append(
                {
                    "action": "escalate",
                    "detail": (
                        "timeout with no readable prompt; captured CST's own window "
                        "in case a pure-Qt modal is blocking"
                    ),
                    "observed_at_unix": time.time(),
                    "cst_pid": pid,
                    "screenshot": str(path) if captured else None,
                    "dialog": None,
                    "effective": False,
                }
            )
