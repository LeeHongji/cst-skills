"""Locate the CST installation and expose its Python packages to any runtime.

The previous default (``C:\\Program Files\\CST Studio Suite 2026``) is only one
of several valid install locations, so every caller had to set
``CST_INSTALL_ROOT`` or fail with an import error that named the wrong path.
:func:`discover_cst_root` removes that dependency by asking a running CST
process where it lives before falling back to guesses.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

_FALLBACK_ROOTS = (
    r"C:\Program Files\CST Studio Suite 2026",
    r"C:\Program Files (x86)\CST Studio Suite 2026",
    r"C:\CST",
)

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_MAX_PATH = 32768
_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_paths_ready = False


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _process_parent_map() -> dict[int, int]:
    """Return live process parentage without requiring psutil or WMI."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
        return {}
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    parents: dict[int, int] = {}
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


def _all_processes() -> list[tuple[int, Path]]:
    """Return ``(pid, image_path)`` for every process we are allowed to inspect."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    enum_processes = None
    for name in ("K32EnumProcesses", "EnumProcesses"):
        enum_processes = getattr(kernel32, name, None)
        if enum_processes is not None:
            break
    if enum_processes is None:  # pragma: no cover - all supported Windows have it
        return []

    count = 4096
    array = (wintypes.DWORD * count)()
    needed = wintypes.DWORD()
    if not enum_processes(ctypes.byref(array), ctypes.sizeof(array), ctypes.byref(needed)):
        return []
    pids = list(array[: needed.value // ctypes.sizeof(wintypes.DWORD)])

    query_image = kernel32.QueryFullProcessImageNameW
    query_image.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    query_image.restype = wintypes.BOOL

    found: list[tuple[int, Path]] = []
    for pid in pids:
        if not pid:
            continue
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            continue
        try:
            buffer = ctypes.create_unicode_buffer(_MAX_PATH)
            size = wintypes.DWORD(_MAX_PATH)
            if query_image(handle, 0, buffer, ctypes.byref(size)):
                found.append((int(pid), Path(buffer.value)))
        finally:
            kernel32.CloseHandle(handle)
    return found


def _enumerate_cst_processes() -> list[tuple[int, Path]]:
    """Live CST Design Environment processes only."""
    return [
        (pid, path)
        for pid, path in _all_processes()
        if "CST DESIGN ENVIRONMENT" in path.name.upper()
    ]


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def cst_process_family_pids(root: Path | None = None) -> list[int]:
    """PIDs of every process running from the CST installation.

    A blocking prompt does not necessarily belong to the Design Environment: a
    VBA modelling prompt is raised by ``modeler_AMD64.exe``, a separate process
    whose dialog is merely *owned* by a Design Environment window.  Watching only
    the Design Environment pid therefore misses the most common hang outright.

    Membership is decided by executable location rather than a name list, so
    solver and post-processing helpers are covered without enumerating them.
    """
    resolved = root or discover_cst_root()
    if resolved is None:
        return sorted({pid for pid, _ in _enumerate_cst_processes()})
    resolved = resolved.resolve()
    pids = {
        pid
        for pid, path in _all_processes()
        if _is_under(path.resolve(), resolved)
    }
    pids.update(pid for pid, _ in _enumerate_cst_processes())
    return sorted(pids)


def cst_instance_pids(
    design_environment_pid: int, root: Path | None = None
) -> list[int]:
    """CST processes descended from one Design Environment instance.

    A machine may have several independent CST sessions. Dialog supervision must
    follow only the task-owned Design Environment and its modeler/solver helpers;
    watching the installation-wide process family could answer a prompt belonging
    to an engineer's unrelated project.
    """
    resolved = root or discover_cst_root()
    processes = _all_processes()
    if resolved is not None:
        resolved = resolved.resolve()
        candidates = {
            pid
            for pid, path in processes
            if _is_under(path.resolve(), resolved)
        }
    else:
        candidates = {pid for pid, _ in processes}
    parents = _process_parent_map()
    selected = {design_environment_pid}
    changed = True
    while changed:
        changed = False
        # Traverse *all* intermediates (e.g. a launcher outside the installation)
        # before selecting CST executables. Filtering intermediates early loses
        # the very child whose launch call the Guardian is supposed to protect.
        for pid in parents.keys() - selected:
            if parents.get(pid) in selected:
                selected.add(pid)
                changed = True
    return sorted(selected & (candidates | {design_environment_pid}))


def running_cst_pids() -> list[int]:
    """PIDs the guardian should watch for dialogs.

    Deliberately the whole CST process family rather than the Design Environment
    alone; see :func:`cst_process_family_pids`.  Never imports ``cst.interface``,
    because the supervisor must work before any COM connection exists.
    """
    with contextlib.suppress(Exception):
        return cst_process_family_pids()
    return []


def running_design_environment_pids() -> list[int]:
    """PIDs of Design Environment processes only, for attaching a session."""
    with contextlib.suppress(Exception):
        return [pid for pid, _ in _enumerate_cst_processes()]
    return []


def _running_cst_executables() -> list[Path]:
    return [path for _, path in _enumerate_cst_processes()]


def _looks_like_root(candidate: Path) -> bool:
    return (candidate / "AMD64" / "python_cst_libraries").is_dir()


def discover_cst_root() -> Path | None:
    """Best-effort CST install root.

    Order matters: explicit configuration wins, then a live process (which cannot
    be wrong about where it was launched from), then well-known locations.
    """
    configured = os.environ.get("CST_INSTALL_ROOT")
    if configured:
        root = Path(configured)
        if _looks_like_root(root):
            return root

    configured_exe = os.environ.get("CST_DESIGN_ENVIRONMENT_EXE")
    if configured_exe:
        root = Path(configured_exe).parent.parent
        if _looks_like_root(root):
            return root

    with contextlib.suppress(Exception):
        for executable in _running_cst_executables():
            root = executable.parent.parent
            if _looks_like_root(root):
                return root

    for fallback in _FALLBACK_ROOTS:
        root = Path(fallback)
        if _looks_like_root(root):
            return root
    return None


class CSTNotFound(RuntimeError):
    """Raised when no CST installation can be located."""


def ensure_cst_paths(root: Path | None = None) -> Path:
    """Put CST's Python packages on ``sys.path`` and its DLLs on the loader path."""
    global _paths_ready
    resolved = root or discover_cst_root()
    if resolved is None:
        raise CSTNotFound(
            "Cannot locate a CST installation. Set CST_INSTALL_ROOT to the "
            "directory containing AMD64\\python_cst_libraries."
        )
    if _paths_ready:
        return resolved

    python_lib = resolved / "AMD64" / "python_cst_libraries"
    amd64_dir = resolved / "AMD64"
    if python_lib.is_dir() and str(python_lib) not in sys.path:
        sys.path.insert(0, str(python_lib))
    if amd64_dir.is_dir():
        amd64 = str(amd64_dir)
        if amd64 not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = amd64 + os.pathsep + os.environ.get("PATH", "")
        add_dll_directory = getattr(os, "add_dll_directory", None)
        if add_dll_directory is not None:
            with contextlib.suppress(Exception):
                add_dll_directory(amd64)
    os.environ.setdefault("CST_INSTALL_ROOT", str(resolved))
    _paths_ready = True
    return resolved
