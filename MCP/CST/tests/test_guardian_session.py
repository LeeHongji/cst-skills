from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from cst_guardian import paths, session
from cst_guardian.session import GuardedSession


class FakeProject:
    def __init__(self) -> None:
        self.saved_to: str | None = None

    def save(self, path: str) -> None:
        self.saved_to = path
        Path(path).write_text("fake cst", encoding="utf-8")


class FakeDesignEnvironment:
    def __init__(self, pid: int = 4242, quiet: bool = False) -> None:
        self._pid = pid
        self._quiet = quiet
        self.quiet_calls: list[bool] = []
        self.launch_options: list[str] | None = None
        self.opened: list[str] = []
        self.project = FakeProject()
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1

    def pid(self) -> int:
        return self._pid

    def in_quiet_mode(self) -> bool:
        return self._quiet

    def set_quiet_mode(self, value: bool) -> None:
        self.quiet_calls.append(value)
        self._quiet = value

    def list_open_projects(self) -> list[str]:
        return list(self.opened)

    def open_project(self, path: str) -> FakeProject:
        self.opened.append(path)
        return self.project

    def new_mws(self) -> FakeProject:
        return self.project


@pytest.fixture
def fake_cst(monkeypatch, tmp_path):
    """Install a fake ``cst.interface`` and a plausible install root."""
    root = tmp_path / "CST"
    (root / "AMD64" / "python_cst_libraries").mkdir(parents=True)
    monkeypatch.setenv("CST_INSTALL_ROOT", str(root))
    import os
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(paths, "_paths_ready", False)

    environments: dict[str, FakeDesignEnvironment] = {}

    class DesignEnvironment:
        @staticmethod
        def connect(pid):
            environments["current"] = FakeDesignEnvironment(pid=pid)
            return environments["current"]

        @staticmethod
        def connect_to_any():
            environments["current"] = FakeDesignEnvironment()
            return environments["current"]

        @staticmethod
        def connect_to_any_or_new():
            environments["current"] = FakeDesignEnvironment()
            return environments["current"]

        @staticmethod
        def new(options=None):
            env = FakeDesignEnvironment()
            env.launch_options = list(options or [])
            environments["current"] = env
            return env

    interface = types.ModuleType("cst.interface")
    interface.DesignEnvironment = DesignEnvironment
    interface.running_design_environments = lambda: [1]
    package = types.ModuleType("cst")
    package.interface = interface
    monkeypatch.setitem(sys.modules, "cst", package)
    monkeypatch.setitem(sys.modules, "cst.interface", interface)
    return environments


def test_quiet_mode_is_enforced_on_connect(fake_cst):
    with GuardedSession() as guard:
        assert guard.de.quiet_calls == [True]
        assert guard.info.quiet_mode is True
        assert guard.info.quiet_mode_enforced is True
        assert guard.info.quiet_mode_was_already_on is False


def test_quiet_mode_is_restored_on_exit(fake_cst):
    with GuardedSession() as guard:
        de = guard.de
    assert de.quiet_calls == [True, False], "must not leave prompts suppressed"
    assert de.in_quiet_mode() is False


def test_an_already_quiet_session_is_left_alone(fake_cst, monkeypatch):
    original = fake_cst
    monkeypatch.setattr(
        sys.modules["cst.interface"].DesignEnvironment,
        "connect_to_any",
        staticmethod(lambda: original.setdefault("current", FakeDesignEnvironment(quiet=True))),
    )
    with GuardedSession() as guard:
        de = guard.de
        assert guard.info.quiet_mode_was_already_on is True
        assert guard.info.quiet_mode_enforced is False
    assert de.quiet_calls == [], "an engineer's own quiet session must not be toggled"


def test_restore_can_be_disabled_for_a_dedicated_worker(fake_cst):
    with GuardedSession(restore_on_exit=False) as guard:
        de = guard.de
    assert de.quiet_calls == [True]


def test_launching_a_new_environment_passes_quiet_flag(fake_cst):
    with GuardedSession(force_new=True) as guard:
        assert guard.de.launch_options == ["--quiet"]
        assert guard.info.launched is True


def test_a_launched_environment_is_shut_down_on_exit(fake_cst):
    """Observed live: three stranded instances after three failed runs.

    Each held the project lock, so the next run failed with "Project is already
    open in another instance of CST Studio Suite" -- a failure that looks like a
    defect in the run rather than leaked state from the previous one.
    """
    with GuardedSession(force_new=True) as guard:
        de = guard.de
        assert de.close_calls == 0
    assert de.close_calls == 1
    assert guard.info.closed is True


def test_an_attached_environment_is_never_shut_down(fake_cst):
    """It belongs to the engineer, not to us."""
    with GuardedSession(pid=1234) as guard:
        de = guard.de
    assert de.close_calls == 0
    assert guard.info.closed is False


def test_shutting_down_a_launched_environment_can_be_waived(fake_cst):
    with GuardedSession(force_new=True, close_launched=False) as guard:
        de = guard.de
    assert de.close_calls == 0


def test_session_info_is_json_serialisable(fake_cst):
    with GuardedSession(pid=99) as guard:
        payload = guard.info.to_json()
    assert payload["pid"] == 99
    assert payload["quiet_mode"] is True
    assert set(payload) >= {
        "pid",
        "quiet_mode",
        "quiet_mode_was_already_on",
        "quiet_mode_enforced",
        "launched",
        "closed",
        "install_root",
        "open_projects",
    }


def test_open_project_rejects_a_missing_path(fake_cst, tmp_path):
    with GuardedSession() as guard:
        with pytest.raises(FileNotFoundError):
            guard.open_project(tmp_path / "nope.cst")


def test_open_project_hands_cst_an_absolute_path(fake_cst, tmp_path, monkeypatch):
    """CST's working directory is not ours, and a relative path hangs it.

    Observed live: passing a repo-relative path produced no error at all, just a
    120 s block until the watchdog killed the worker.
    """
    project = tmp_path / "runs" / "working.cst"
    project.parent.mkdir(parents=True)
    project.write_text("fake cst", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with GuardedSession() as guard:
        guard.open_project(Path("runs") / "working.cst")
        passed = guard.de.opened[-1]

    assert Path(passed).is_absolute()
    assert Path(passed) == project.resolve()


def test_new_project_saves_through_an_absolute_path(fake_cst, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with GuardedSession() as guard:
        guard.new_project(save_as=Path("runs") / "fresh.cst")
        saved = guard.de.project.saved_to
    assert Path(saved).is_absolute()
    assert Path(saved) == (tmp_path / "runs" / "fresh.cst").resolve()


def test_new_project_refuses_to_overwrite(fake_cst, tmp_path):
    existing = tmp_path / "already.cst"
    existing.write_text("do not clobber", encoding="utf-8")
    with GuardedSession() as guard:
        with pytest.raises(FileExistsError, match="already exists"):
            guard.new_project(save_as=existing)
    assert existing.read_text(encoding="utf-8") == "do not clobber"


def test_new_project_saves_to_a_fresh_path(fake_cst, tmp_path):
    target = tmp_path / "runs" / "working.cst"
    with GuardedSession() as guard:
        guard.new_project(save_as=target)
    assert target.is_file()


def test_using_the_session_before_entering_is_an_error(fake_cst, tmp_path):
    guard = GuardedSession()
    with pytest.raises(RuntimeError, match="must be entered"):
        guard.new_project()
