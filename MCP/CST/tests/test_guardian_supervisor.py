from __future__ import annotations

import json
import sys
import time

import pytest

from cst_guardian import supervisor
from cst_guardian.supervisor import _DialogTracker, run_guarded
from cst_guardian.win32_dialogs import ButtonInfo, DialogInfo, UnreadableModal

STALE_RESULTS = "The results will be deleted."


def dialog(text: str = STALE_RESULTS, hwnd: int = 4242, native: bool = True) -> DialogInfo:
    return DialogInfo(
        hwnd=hwnd,
        title="CST Studio Suite",
        class_name="#32770" if native else "QWidget",
        enabled=True,
        child_text=(text,),
        buttons=(ButtonInfo(hwnd=hwnd + 1, text="&Yes", control_id=6, enabled=True),),
    )


@pytest.fixture(autouse=True)
def no_screenshots(monkeypatch):
    monkeypatch.setattr(supervisor, "_screenshot", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def no_release(monkeypatch):
    """Orphan release needs a real window; assert on it explicitly where relevant."""
    monkeypatch.setattr(supervisor, "release_dialog", lambda dialog: None)


def dialogs_appear_after(count: int, dialog_factory):
    """Return an enumerate_dialogs stub that stays empty for the first ``count`` polls.

    Lets a test exercise the in-run dialog path without tripping the clean-start
    preflight, which is a separate behaviour with its own test.
    """
    state = {"calls": 0}

    def enumerate_stub(_pid):
        state["calls"] += 1
        return [] if state["calls"] <= count else [dialog_factory()]

    return enumerate_stub


@pytest.fixture
def no_dialogs(monkeypatch):
    monkeypatch.setattr(supervisor, "enumerate_dialogs", lambda pid: [])
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [])


def worker(code: str) -> list[str]:
    return [sys.executable, "-c", code]


# -- tracker -----------------------------------------------------------------


def test_tracker_debounces_until_stable():
    tracker = _DialogTracker(stable_polls=3)
    d = dialog()
    assert tracker.ready(d) is False
    assert tracker.ready(d) is False
    assert tracker.ready(d) is True


def test_tracker_ignores_a_handled_dialog():
    tracker = _DialogTracker(stable_polls=1)
    d = dialog()
    assert tracker.ready(d) is True
    tracker.mark_handled(d)
    assert tracker.ready(d) is False


def test_tracker_reevaluates_after_forget():
    tracker = _DialogTracker(stable_polls=2)
    d = dialog()
    tracker.ready(d)
    tracker.forget(d)
    assert tracker.ready(d) is False  # counter restarted
    assert tracker.ready(d) is True


def test_fingerprint_survives_hwnd_reuse_but_splits_on_buttons():
    assert dialog(hwnd=1).fingerprint() == dialog(hwnd=999).fingerprint()
    other = DialogInfo(
        hwnd=1,
        title="CST Studio Suite",
        class_name="#32770",
        enabled=True,
        child_text=(STALE_RESULTS,),
        buttons=(ButtonInfo(hwnd=2, text="&Delete", control_id=6, enabled=True),),
    )
    assert other.fingerprint() != dialog(hwnd=1).fingerprint()


# -- worker lifecycle --------------------------------------------------------


def test_successful_worker_reports_completed(tmp_path, no_dialogs):
    report = run_guarded(worker("print('ok')"), log_dir=tmp_path, poll_interval_s=0.01)
    assert report.outcome == "completed"
    assert report.exit_code == 0
    assert report.ok is True
    assert (tmp_path / "worker-stdout.txt").read_text(encoding="utf-8").strip() == "ok"


def test_failing_worker_reports_worker_failed(tmp_path, no_dialogs):
    report = run_guarded(
        worker("import sys; sys.stderr.write('boom'); sys.exit(3)"),
        log_dir=tmp_path,
        poll_interval_s=0.01,
    )
    assert report.outcome == "worker_failed"
    assert report.exit_code == 3
    assert report.ok is False
    assert "boom" in (tmp_path / "worker-stderr.txt").read_text(encoding="utf-8")


def test_timeout_kills_the_worker_and_survives(tmp_path, no_dialogs):
    started = time.monotonic()
    report = run_guarded(
        worker("import time; time.sleep(60)"),
        log_dir=tmp_path,
        timeout_s=0.5,
        poll_interval_s=0.05,
    )
    assert report.outcome == "timeout"
    assert report.exit_code is not None, "worker must be reaped, not left running"
    assert time.monotonic() - started < 20
    assert report.ok is False


# -- unreadable modals -------------------------------------------------------


def unreadable(title: str = "CST MICROWAVE STUDIO - History Error") -> UnreadableModal:
    return UnreadableModal(
        main_window=460788,
        main_title="mmr2_180deg_a01 - CST Studio Suite 2026",
        hwnd=6099656,
        title=title,
        class_name="Qt683QWindow",
    )


def test_an_unreadable_modal_fingerprint_ignores_hwnd():
    """Handles are reused; the identity has to survive that."""
    a = unreadable()
    b = UnreadableModal(
        main_window=a.main_window,
        main_title=a.main_title,
        hwnd=999,
        title=a.title,
        class_name=a.class_name,
    )
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != unreadable("CST MICROWAVE STUDIO - Warning").fingerprint()


def test_a_persistent_unreadable_modal_escalates(tmp_path, monkeypatch):
    """A Qt modal has no readable controls, so the only honest response is to stop.

    Found for real: CST 2026 rejected a mesh command in a ``Qt683QWindow``, which
    ``enumerate_dialogs`` cannot see, and a history injection sat blocked for twelve
    minutes with nothing in any log to say why.
    """
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(supervisor, "enumerate_dialogs", lambda pid: [])
    monkeypatch.setattr(supervisor, "unreadable_modals", lambda pid: [unreadable()])
    monkeypatch.setattr(supervisor, "_UNREADABLE_MODAL_GRACE_S", 0.0)
    monkeypatch.setattr(supervisor, "capture_window", lambda hwnd, path: False)

    report = run_guarded(
        worker("import time; time.sleep(60)"), log_dir=tmp_path, poll_interval_s=0.01
    )
    assert report.outcome == "escalated"
    assert report.exit_code is not None, "worker must be reaped, not left running"
    escalations = report.escalations
    assert len(escalations) == 1
    assert escalations[0]["reason"] == "unreadable_modal"
    assert escalations[0]["modal"]["class_name"] == "Qt683QWindow"


def test_an_unreadable_modal_is_not_escalated_before_the_grace_period(tmp_path, monkeypatch):
    """CST disables its own main window during legitimate long operations too."""
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(supervisor, "enumerate_dialogs", lambda pid: [])
    monkeypatch.setattr(supervisor, "unreadable_modals", lambda pid: [unreadable()])
    monkeypatch.setattr(supervisor, "_UNREADABLE_MODAL_GRACE_S", 3600.0)

    report = run_guarded(worker("print('ok')"), log_dir=tmp_path, poll_interval_s=0.01)
    assert report.outcome == "completed"
    assert report.escalations == []


def test_a_modal_that_clears_itself_does_not_accumulate_dwell(tmp_path, monkeypatch):
    """A progress window that comes and goes must not add up to a stall."""
    state = {"calls": 0}

    def flicker(_pid):
        state["calls"] += 1
        return [unreadable()] if state["calls"] % 2 else []

    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(supervisor, "enumerate_dialogs", lambda pid: [])
    monkeypatch.setattr(supervisor, "unreadable_modals", flicker)
    monkeypatch.setattr(supervisor, "_UNREADABLE_MODAL_GRACE_S", 0.4)

    report = run_guarded(
        worker("import time; time.sleep(1.5)"), log_dir=tmp_path, poll_interval_s=0.05
    )
    assert report.outcome == "completed"
    assert report.escalations == []


def test_report_is_written_to_disk(tmp_path, no_dialogs):
    run_guarded(worker("print('x')"), log_dir=tmp_path, poll_interval_s=0.01)
    payload = json.loads((tmp_path / "guard-report.json").read_text(encoding="utf-8"))
    assert payload["outcome"] == "completed"
    assert payload["dialogs_answered"] == 0
    assert payload["escalations"] == 0


# -- clean start ------------------------------------------------------------


def test_a_preexisting_prompt_blocks_the_run(tmp_path, monkeypatch):
    """A stale prompt makes every later observation wrong, so refuse to start.

    Observed for real: a leftover prompt from a killed worker was attributed to
    the next scenario, which then "passed" for entirely the wrong reason.
    """
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(supervisor, "enumerate_dialogs", lambda pid: [dialog()])
    monkeypatch.setattr(
        supervisor.subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("the worker must not start behind a stale prompt"),
    )

    report = run_guarded(worker("print('x')"), log_dir=tmp_path, poll_interval_s=0.01)
    assert report.outcome == "blocked"
    assert report.ok is False
    assert report.exit_code is None
    assert report.events[0]["action"] == "blocked"
    assert "already on screen" in report.events[0]["detail"]


def test_the_guardian_does_not_dismiss_a_preexisting_prompt(tmp_path, monkeypatch):
    """It cannot tell an orphan from a dialog a human is currently reading."""
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(supervisor, "enumerate_dialogs", lambda pid: [dialog()])
    monkeypatch.setattr(
        supervisor,
        "release_dialog",
        lambda d: pytest.fail("must not touch a prompt it did not cause"),
    )
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **k: pytest.fail("no"))
    assert run_guarded(worker("print('x')"), log_dir=tmp_path).outcome == "blocked"


def test_clean_start_can_be_waived(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(supervisor, "enumerate_dialogs", lambda pid: [])
    report = run_guarded(
        worker("print('x')"),
        log_dir=tmp_path,
        poll_interval_s=0.01,
        require_clean_start=False,
    )
    assert report.outcome == "completed"


# -- dialog handling --------------------------------------------------------


def guarded(tmp_path, code: str, **kwargs):
    """Run a worker with the clean-start preflight waived.

    These tests inject a dialog from the first poll onward, which is what the
    preflight is designed to reject; clean-start behaviour has its own tests.
    """
    kwargs.setdefault("poll_interval_s", 0.02)
    kwargs.setdefault("stable_polls", 1)
    kwargs.setdefault("require_clean_start", False)
    return run_guarded(worker(code), log_dir=tmp_path, **kwargs)


def test_known_dialog_is_answered_and_worker_keeps_running(tmp_path, monkeypatch):
    pressed: list[tuple[str, int]] = []
    gone = {"value": False}

    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(
        supervisor, "enumerate_dialogs", lambda pid: [] if gone["value"] else [dialog()]
    )

    def fake_press(_dialog, button):
        pressed.append((button.text, button.control_id))
        gone["value"] = True

    monkeypatch.setattr(supervisor, "press_button", fake_press)
    monkeypatch.setattr(supervisor, "dialog_is_gone", lambda hwnd: gone["value"])

    report = guarded(tmp_path, "import time; time.sleep(0.6); print('done')")
    assert pressed == [("&Yes", 6)]
    assert report.outcome == "completed", "answering a known prompt must not kill the worker"
    assert len(report.dialogs_answered) == 1
    answered = report.dialogs_answered[0]
    assert answered["rule_id"] == "stale-results-discard"
    assert answered["effective"] is True
    assert answered["button_standard_name"] == "IDYES"


def test_unknown_dialog_escalates_and_kills_the_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(
        supervisor, "enumerate_dialogs", lambda pid: [dialog("A brand new question?")]
    )
    report = guarded(tmp_path, "import time; time.sleep(60)")
    assert report.outcome == "escalated"
    assert len(report.escalations) == 1
    assert report.escalations[0]["rule_id"] is None
    assert report.exit_code is not None, "worker must be killed on escalation"


def test_ineffective_press_becomes_an_escalation(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(supervisor, "enumerate_dialogs", lambda pid: [dialog()])
    monkeypatch.setattr(supervisor, "press_button", lambda *a: None)
    monkeypatch.setattr(supervisor, "dialog_is_gone", lambda hwnd: False)
    monkeypatch.setattr(supervisor, "_CLICK_SETTLE_S", 0.1)

    report = guarded(tmp_path, "import time; time.sleep(60)")
    assert report.outcome == "escalated"
    assert "still on screen" in report.escalations[0]["detail"]


def test_non_native_dialog_is_escalated_not_actuated(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(supervisor, "enumerate_dialogs", lambda pid: [dialog(native=False)])
    monkeypatch.setattr(
        supervisor,
        "press_button",
        lambda *a: pytest.fail("a Qt modal exposes no button controls to activate"),
    )
    report = guarded(tmp_path, "import time; time.sleep(60)")
    assert report.outcome == "escalated"
    assert "not a native" in report.escalations[0]["detail"]


def test_escalation_can_be_observed_without_killing(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(
        supervisor, "enumerate_dialogs", lambda pid: [dialog("Unrecognised prompt?")]
    )
    report = guarded(
        tmp_path, "import time; time.sleep(0.4)", kill_on_escalation=False
    )
    assert report.outcome == "completed"
    assert len(report.escalations) >= 1


# -- orphan release ---------------------------------------------------------


def test_killing_the_worker_releases_the_orphaned_prompt(tmp_path, monkeypatch):
    """An orphaned prompt keeps CST's modeller blocked for every later run.

    Verified live: a prompt whose VBA caller had been killed stayed on screen
    indefinitely and the next run inherited it.
    """
    released: list[int] = []
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(
        supervisor, "enumerate_dialogs", lambda pid: [dialog("Unrecognised prompt?")]
    )
    monkeypatch.setattr(supervisor, "dialog_is_gone", lambda hwnd: True)

    def fake_release(d):
        released.append(d.hwnd)
        return ButtonInfo(hwnd=1, text="&No", control_id=7, enabled=True)

    monkeypatch.setattr(supervisor, "release_dialog", fake_release)

    report = guarded(tmp_path, "import time; time.sleep(60)")
    assert report.outcome == "escalated"
    assert released, "the orphan must be released after the worker is killed"
    assert len(report.released) == 1
    assert report.released[0]["button_standard_name"] == "IDNO"
    assert report.released[0]["effective"] is True


def test_release_is_reported_when_no_standard_button_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(
        supervisor, "enumerate_dialogs", lambda pid: [dialog("Unrecognised prompt?")]
    )
    monkeypatch.setattr(supervisor, "release_dialog", lambda d: None)

    report = guarded(tmp_path, "import time; time.sleep(60)")
    failures = [e for e in report.events if e["action"] == "release_failed"]
    assert failures
    assert "dismissed by hand" in failures[0]["detail"]
    assert report.released == []


def test_screenshot_is_taken_before_the_orphan_is_released(tmp_path, monkeypatch):
    """Evidence must show the prompt as the engineer would have seen it."""
    order: list[str] = []
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(
        supervisor, "enumerate_dialogs", lambda pid: [dialog("Unrecognised prompt?")]
    )
    monkeypatch.setattr(
        supervisor,
        "_screenshot",
        lambda *a, **k: order.append("screenshot") or None,
    )
    monkeypatch.setattr(
        supervisor, "release_dialog", lambda d: order.append("release") or None
    )

    guarded(tmp_path, "import time; time.sleep(60)")
    assert order.index("screenshot") < order.index("release")


# -- timeout diagnostics ----------------------------------------------------


def test_timeout_without_a_readable_prompt_captures_cst_windows(tmp_path, monkeypatch):
    """A pure-Qt modal is invisible to enumeration; the window shot is the backstop."""
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: [777])
    monkeypatch.setattr(supervisor, "enumerate_dialogs", lambda pid: [])
    monkeypatch.setattr(supervisor, "main_windows_for_pid", lambda pid: [4242])
    monkeypatch.setattr(supervisor, "capture_window", lambda hwnd, path: True)

    report = run_guarded(
        worker("import time; time.sleep(60)"),
        log_dir=tmp_path,
        timeout_s=0.3,
        poll_interval_s=0.05,
    )
    assert report.outcome == "timeout"
    assert len(report.escalations) == 1
    assert report.escalations[0]["dialog"] is None
    assert "pure-Qt modal" in report.escalations[0]["detail"]


def test_explicit_pids_are_used_instead_of_discovery(tmp_path, monkeypatch):
    seen: list[int] = []
    monkeypatch.setattr(
        supervisor,
        "running_cst_pids",
        lambda: pytest.fail("discovery must not run when pids are given"),
    )

    def record(pid):
        seen.append(pid)
        return []

    monkeypatch.setattr(supervisor, "enumerate_dialogs", record)
    report = run_guarded(
        worker("import time; time.sleep(0.2)"),
        log_dir=tmp_path,
        cst_pids=[11, 22],
        poll_interval_s=0.02,
    )
    assert set(seen) == {11, 22}
    assert report.watched_pids == [11, 22]


def test_root_pid_scope_follows_only_that_cst_instance(tmp_path, monkeypatch):
    seen: list[int] = []
    monkeypatch.setattr(
        supervisor,
        "running_cst_pids",
        lambda: pytest.fail("installation-wide discovery must not run"),
    )
    monkeypatch.setattr(
        supervisor,
        "cst_instance_pids",
        lambda root: [root, root + 1],
    )

    def record(pid):
        seen.append(pid)
        return []

    monkeypatch.setattr(supervisor, "enumerate_dialogs", record)
    report = run_guarded(
        worker("import time; time.sleep(0.2)"),
        log_dir=tmp_path,
        cst_pid_roots=[100],
        poll_interval_s=0.02,
    )
    assert set(seen) == {100, 101}
    assert report.watched_pids == [100, 101]


def test_worker_scope_is_known_before_any_cst_connection(tmp_path, monkeypatch):
    seen, roots = [], []
    monkeypatch.setattr(supervisor, "running_cst_pids", lambda: pytest.fail("global discovery forbidden"))
    def descendants(root):
        roots.append(root)
        return [root]
    monkeypatch.setattr(supervisor, "cst_instance_pids", descendants)
    monkeypatch.setattr(supervisor, "enumerate_dialogs", lambda pid: seen.append(pid) or [])
    report = run_guarded(worker("import time; time.sleep(.2)"), log_dir=tmp_path,
                         scope_worker_descendants=True, poll_interval_s=.02)
    assert report.ok
    assert roots and len(set(roots)) == 1
    assert report.events[0]["worker_pid"] == roots[0]
    assert set(seen) == {roots[0]}


@pytest.mark.parametrize("scope", [{"cst_pids": [99]}, {"cst_pid_roots": [99]}])
def test_worker_scope_refuses_ambiguous_external_ownership(tmp_path, scope):
    with pytest.raises(ValueError, match="external CST PIDs"):
        run_guarded(worker("raise RuntimeError('must not run')"), log_dir=tmp_path,
                    scope_worker_descendants=True, **scope)
    assert not list(tmp_path.iterdir())

