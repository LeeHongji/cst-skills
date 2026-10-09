from __future__ import annotations

import sys
import os

import pytest

from cst_guardian import paths
from cst_guardian.paths import (
    CSTNotFound,
    cst_instance_pids,
    discover_cst_root,
    ensure_cst_paths,
)


def make_root(tmp_path, name="CST"):
    root = tmp_path / name
    (root / "AMD64" / "python_cst_libraries").mkdir(parents=True)
    return root


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    # ensure_cst_paths writes setdefault even if the variable was initially absent.
    # Record that absence before deleting it, otherwise a fake install leaks to
    # subsequent runtime subprocess tests. PATH and sys.path are mutated too.
    monkeypatch.setenv("CST_INSTALL_ROOT", os.environ.get("CST_INSTALL_ROOT", ""))
    monkeypatch.delenv("CST_INSTALL_ROOT", raising=False)
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delenv("CST_DESIGN_ENVIRONMENT_EXE", raising=False)
    monkeypatch.setattr(paths, "_paths_ready", False)
    monkeypatch.setattr(paths, "_FALLBACK_ROOTS", ())
    monkeypatch.setattr(paths, "_all_processes", lambda: [])


def test_env_root_wins(monkeypatch, tmp_path):
    root = make_root(tmp_path)
    monkeypatch.setenv("CST_INSTALL_ROOT", str(root))
    assert discover_cst_root() == root


def test_env_root_is_ignored_when_it_does_not_look_like_an_install(monkeypatch, tmp_path):
    monkeypatch.setenv("CST_INSTALL_ROOT", str(tmp_path / "empty"))
    assert discover_cst_root() is None


def test_executable_env_var_is_walked_up_two_levels(monkeypatch, tmp_path):
    root = make_root(tmp_path)
    exe = root / "AMD64" / "CST DESIGN ENVIRONMENT_AMD64.exe"
    monkeypatch.setenv("CST_DESIGN_ENVIRONMENT_EXE", str(exe))
    assert discover_cst_root() == root


def test_a_running_process_locates_the_install(monkeypatch, tmp_path):
    """A live process cannot be wrong about where it was launched from."""
    root = make_root(tmp_path, name="CST-elsewhere")
    exe = root / "AMD64" / "CST DESIGN ENVIRONMENT_AMD64.exe"
    monkeypatch.setattr(paths, "_all_processes", lambda: [(2400, exe)])
    assert discover_cst_root() == root


def test_running_process_outranks_a_fallback(monkeypatch, tmp_path):
    live = make_root(tmp_path, name="live")
    fallback = make_root(tmp_path, name="fallback")
    monkeypatch.setattr(
        paths,
        "_all_processes",
        lambda: [(1, live / "AMD64" / "CST DESIGN ENVIRONMENT_AMD64.exe")],
    )
    monkeypatch.setattr(paths, "_FALLBACK_ROOTS", (str(fallback),))
    assert discover_cst_root() == live


def test_fallback_is_used_last(monkeypatch, tmp_path):
    fallback = make_root(tmp_path, name="fallback")
    monkeypatch.setattr(paths, "_FALLBACK_ROOTS", (str(tmp_path / "missing"), str(fallback)))
    assert discover_cst_root() == fallback


def test_ensure_paths_raises_a_actionable_error_when_absent():
    with pytest.raises(CSTNotFound, match="CST_INSTALL_ROOT"):
        ensure_cst_paths()


def test_ensure_paths_publishes_the_python_libraries(monkeypatch, tmp_path):
    root = make_root(tmp_path)
    monkeypatch.setenv("CST_INSTALL_ROOT", str(root))
    monkeypatch.setattr(sys, "path", list(sys.path))
    resolved = ensure_cst_paths()
    assert resolved == root
    assert str(root / "AMD64" / "python_cst_libraries") in sys.path


def test_ensure_paths_exports_the_install_root(monkeypatch, tmp_path):
    root = make_root(tmp_path)
    monkeypatch.setattr(paths, "_FALLBACK_ROOTS", (str(root),))
    monkeypatch.setattr(sys, "path", list(sys.path))
    ensure_cst_paths()
    import os

    assert os.environ["CST_INSTALL_ROOT"] == str(root)


def test_running_pids_never_raises(monkeypatch):
    monkeypatch.setattr(
        paths,
        "cst_process_family_pids",
        lambda: (_ for _ in ()).throw(OSError("access denied")),
    )
    assert paths.running_cst_pids() == []


def test_process_family_includes_helpers_outside_the_design_environment(
    monkeypatch, tmp_path
):
    """A VBA prompt comes from modeler_AMD64.exe, not the Design Environment.

    Watching only the Design Environment pid misses the most common hang, so
    membership is decided by executable location.
    """
    root = make_root(tmp_path)
    monkeypatch.setenv("CST_INSTALL_ROOT", str(root))
    amd64 = root / "AMD64"
    design_env = amd64 / "CST DESIGN ENVIRONMENT_AMD64.exe"
    modeler = amd64 / "modeler_AMD64.exe"
    unrelated = tmp_path / "elsewhere" / "notepad.exe"
    monkeypatch.setattr(
        paths,
        "_all_processes",
        lambda: [(2400, design_env), (14012, modeler), (999, unrelated)],
    )
    assert paths.cst_process_family_pids() == [2400, 14012]


def test_design_environment_pids_stay_narrow(monkeypatch, tmp_path):
    """Attaching a COM session must target a Design Environment, not a helper."""
    root = make_root(tmp_path)
    monkeypatch.setenv("CST_INSTALL_ROOT", str(root))
    amd64 = root / "AMD64"
    monkeypatch.setattr(
        paths,
        "_all_processes",
        lambda: [
            (2400, amd64 / "CST DESIGN ENVIRONMENT_AMD64.exe"),
            (14012, amd64 / "modeler_AMD64.exe"),
        ],
    )
    assert paths.running_design_environment_pids() == [2400]
    assert paths.cst_process_family_pids() == [2400, 14012]


def test_instance_pids_include_only_one_design_environment_tree(monkeypatch, tmp_path):
    root = make_root(tmp_path)
    monkeypatch.setenv("CST_INSTALL_ROOT", str(root))
    amd64 = root / "AMD64"
    monkeypatch.setattr(
        paths,
        "_all_processes",
        lambda: [
            (100, amd64 / "CST DESIGN ENVIRONMENT_AMD64.exe"),
            (101, amd64 / "modeler_AMD64.exe"),
            (102, amd64 / "solver_AMD64.exe"),
            (200, amd64 / "CST DESIGN ENVIRONMENT_AMD64.exe"),
            (201, amd64 / "modeler_AMD64.exe"),
        ],
    )
    monkeypatch.setattr(
        paths,
        "_process_parent_map",
        lambda: {101: 100, 102: 101, 201: 200},
    )
    assert cst_instance_pids(100) == [100, 101, 102]
    assert cst_instance_pids(200) == [200, 201]


def test_family_falls_back_to_design_environments_when_root_is_unknown(monkeypatch):
    from pathlib import Path as P

    monkeypatch.setattr(paths, "discover_cst_root", lambda: None)
    monkeypatch.setattr(
        paths,
        "_all_processes",
        lambda: [(2400, P(r"X:\CST\AMD64\CST DESIGN ENVIRONMENT_AMD64.exe"))],
    )
    assert paths.cst_process_family_pids() == [2400]


def test_instance_scope_crosses_non_cst_launcher_without_watching_it(monkeypatch, tmp_path):
    root = make_root(tmp_path)
    monkeypatch.setenv("CST_INSTALL_ROOT", str(root))
    monkeypatch.setattr(paths, "_all_processes", lambda: [
        (10, tmp_path / "python.exe"), (11, tmp_path / "launcher.exe"),
        (12, root / "AMD64" / "CST DESIGN ENVIRONMENT_AMD64.exe"),
        (13, root / "AMD64" / "modeler_AMD64.exe"),
        (20, root / "AMD64" / "CST DESIGN ENVIRONMENT_AMD64.exe"),
    ])
    monkeypatch.setattr(paths, "_process_parent_map", lambda: {11: 10, 12: 11, 13: 12, 20: 1})
    assert cst_instance_pids(10) == [10, 12, 13]
