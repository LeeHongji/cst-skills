#!/usr/bin/env python3
"""Dump every visible window of each CST process, unfiltered.

Used to design the dialog filter from evidence instead of heuristics: the
quiescent dump is the baseline, and the diff after a prompt appears is the set of
windows that actually constitute a dialog.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cst_guardian.paths import running_cst_pids  # noqa: E402
from cst_guardian.win32_dialogs import (  # noqa: E402
    GW_OWNER,
    buttons_for,
    child_text,
    class_name,
    user32,
    window_text,
)


def dump(pid: int, include_invisible: bool = False) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value != pid:
            return True
        visible = bool(user32.IsWindowVisible(hwnd))
        if not visible and not include_invisible:
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        owner = user32.GetWindow(hwnd, GW_OWNER)
        rows.append(
            {
                "hwnd": int(hwnd),
                "title": window_text(hwnd),
                "class_name": class_name(hwnd),
                "visible": visible,
                "enabled": bool(user32.IsWindowEnabled(hwnd)),
                "owner_hwnd": int(owner) if owner else 0,
                "rect": [rect.left, rect.top, rect.right, rect.bottom],
                "size": [rect.right - rect.left, rect.bottom - rect.top],
                "child_text": list(child_text(hwnd)),
                "buttons": [
                    {"text": b.text, "control_id": b.control_id, "enabled": b.enabled}
                    for b in buttons_for(hwnd)
                ],
            }
        )
        return True

    user32.EnumWindows(callback, 0)
    return rows


def _process_name(pid: int) -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return "?"
    try:
        query = kernel32.QueryFullProcessImageNameW
        query.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        query.restype = wintypes.BOOL
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(32768)
        if query(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name
        return "?"
    finally:
        kernel32.CloseHandle(handle)


def dump_all(include_invisible: bool = False) -> list[dict[str, object]]:
    """Every visible top-level window on the desktop, with its owning process.

    A CST prompt is not guaranteed to belong to the Design Environment process;
    scoping the search to one pid can miss it entirely.
    """
    rows: list[dict[str, object]] = []
    names: dict[int, str] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        visible = bool(user32.IsWindowVisible(hwnd))
        if not visible and not include_invisible:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        owning = int(pid.value)
        if owning not in names:
            names[owning] = _process_name(owning)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        owner = user32.GetWindow(hwnd, GW_OWNER)
        rows.append(
            {
                "hwnd": int(hwnd),
                "pid": owning,
                "process": names[owning],
                "title": window_text(hwnd),
                "class_name": class_name(hwnd),
                "visible": visible,
                "enabled": bool(user32.IsWindowEnabled(hwnd)),
                "owner_hwnd": int(owner) if owner else 0,
                "size": [rect.right - rect.left, rect.bottom - rect.top],
                "child_text": list(child_text(hwnd)),
                "buttons": [
                    {"text": b.text, "control_id": b.control_id, "enabled": b.enabled}
                    for b in buttons_for(hwnd)
                ],
            }
        )
        return True

    user32.EnumWindows(callback, 0)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--include-invisible", action="store_true")
    parser.add_argument("--all-processes", action="store_true")
    args = parser.parse_args()

    if args.all_processes:
        payload: dict[str, object] = {"all": dump_all(args.include_invisible)}
    else:
        payload = {
            str(pid): dump(pid, args.include_invisible) for pid in running_cst_pids()
        }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
