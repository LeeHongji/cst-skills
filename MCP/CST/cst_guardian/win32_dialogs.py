"""Win32 inspection and deterministic actuation of CST modal dialogs.

The functions here are the only place in the guardian that talks to user32/gdi32.
Everything above this layer works with :class:`DialogInfo` and :class:`ButtonInfo`
values so it can be unit tested without a live CST process.

Only native dialogs (window class ``#32770``) can be actuated.  Qt-owned modals
report a ``Qt...`` class and expose no Win32 ``Button`` child controls at all, so
:func:`press_button` refuses to touch them; the caller must escalate instead of
guessing.
"""

from __future__ import annotations

import ctypes
import hashlib
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindowEnabled.argtypes = [wintypes.HWND]
user32.IsWindowEnabled.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetWindow.restype = wintypes.HWND
user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
user32.GetDlgCtrlID.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [
    wintypes.HWND,
    ctypes.c_uint,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.PostMessageW.argtypes = [
    wintypes.HWND,
    ctypes.c_uint,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
]
user32.PostMessageW.restype = wintypes.BOOL

GW_OWNER = 4
WM_COMMAND = 0x0111
WM_CLOSE = 0x0010
BN_CLICKED = 0
PW_RENDERFULLCONTENT = 0x00000002

NATIVE_DIALOG_CLASS = "#32770"
BUTTON_CLASSES = ("Button",)

# Standard Win32 dialog control identifiers.  These are the only locale-invariant
# handle on a dialog's buttons: a Chinese CST install labels the same buttons
# "\u662f(&Y)" and "\u5426(&N)", so matching on caption text alone silently fails.
IDOK = 1
IDCANCEL = 2
IDABORT = 3
IDRETRY = 4
IDIGNORE = 5
IDYES = 6
IDNO = 7
IDCLOSE = 8
IDTRYAGAIN = 10
IDCONTINUE = 11

STANDARD_CONTROL_NAMES = {
    IDOK: "IDOK",
    IDCANCEL: "IDCANCEL",
    IDABORT: "IDABORT",
    IDRETRY: "IDRETRY",
    IDIGNORE: "IDIGNORE",
    IDYES: "IDYES",
    IDNO: "IDNO",
    IDCLOSE: "IDCLOSE",
    IDTRYAGAIN: "IDTRYAGAIN",
    IDCONTINUE: "IDCONTINUE",
}

#: Child text that identifies CST's own "quiet mode is on" banner.  It is a
#: visible owned window but not a prompt, so it must never be treated as one.
QUIET_MODE_NOTICE = "Quiet/Scripting mode is active"


@dataclass(frozen=True)
class ButtonInfo:
    hwnd: int
    text: str
    control_id: int
    enabled: bool

    @property
    def standard_name(self) -> str | None:
        return STANDARD_CONTROL_NAMES.get(self.control_id)


@dataclass(frozen=True)
class DialogInfo:
    hwnd: int
    title: str
    class_name: str
    enabled: bool
    child_text: tuple[str, ...] = ()
    buttons: tuple[ButtonInfo, ...] = field(default=())

    @property
    def is_native(self) -> bool:
        """True when the dialog is a classic Win32 dialog we can read and actuate."""
        return self.class_name == NATIVE_DIALOG_CLASS

    @property
    def body_text(self) -> str:
        return "\n".join(self.child_text)

    def fingerprint(self) -> str:
        """Stable identity across polls and across hwnd reuse.

        Deliberately excludes ``hwnd`` so the same prompt reappearing with a new
        handle is recognised as the same dialog, and includes button labels so
        two prompts sharing a title but offering different choices stay distinct.
        """
        parts = [self.title, self.class_name, *self.child_text]
        parts.extend(button.text for button in self.buttons)
        digest = hashlib.sha256("\u0000".join(parts).encode("utf-8")).hexdigest()
        return digest[:16]

    def to_json(self) -> dict[str, object]:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "class_name": self.class_name,
            "enabled": self.enabled,
            "is_native": self.is_native,
            "child_text": list(self.child_text),
            "buttons": [
                {
                    "text": button.text,
                    "control_id": button.control_id,
                    "standard_name": button.standard_name,
                    "enabled": button.enabled,
                }
                for button in self.buttons
            ],
            "fingerprint": self.fingerprint(),
        }


def window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value.strip()


def class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value


def _enum_children(hwnd: int):
    handles: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(child: int, _lparam: int) -> bool:
        handles.append(int(child))
        return True

    user32.EnumChildWindows(hwnd, callback, 0)
    return handles


def child_text(hwnd: int) -> tuple[str, ...]:
    values: list[str] = []
    for child in _enum_children(hwnd):
        text = window_text(child)
        if text and text not in values:
            values.append(text)
    return tuple(values)


def buttons_for(hwnd: int) -> tuple[ButtonInfo, ...]:
    found: list[ButtonInfo] = []
    for child in _enum_children(hwnd):
        if class_name(child) not in BUTTON_CLASSES:
            continue
        text = window_text(child)
        if not text:
            continue
        found.append(
            ButtonInfo(
                hwnd=child,
                text=text,
                control_id=int(user32.GetDlgCtrlID(child)),
                enabled=bool(user32.IsWindowEnabled(child)),
            )
        )
    return tuple(found)


def _window_area(hwnd: int) -> int:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return 0
    return max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)


def _is_main_window(title: str, cls: str, area: int) -> bool:
    return cls.startswith("Qt") and area > 500_000 and (
        "CST Studio Suite" in title or title.startswith("CST DESIGN ENVIRONMENT")
    )


def enumerate_dialogs(pid: int) -> list[DialogInfo]:
    """Return visible, actionable prompt windows belonging to ``pid``.

    A window qualifies only if it offers something to read or something to press.
    That single condition removes the whole class of false positives CST presents
    in its idle state -- a 520x173 owned Qt helper window carrying the main
    window's own title, four decorative border windows, and the transient
    "Initializing application" progress bar -- none of which have child controls.
    Size heuristics were tried first and were unreliable.

    Ownership is *not* required to be in-process.  A VBA modelling prompt is
    raised by ``modeler_AMD64.exe`` yet owned by a Design Environment window, so
    demanding a same-process owner would reject the most common real prompt.

    A consequence worth stating: a pure-Qt modal has no child ``HWND``s at all,
    so it is invisible here and cannot be read or clicked.  The timeout watchdog
    is the backstop for that case.
    """
    found: list[DialogInfo] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        children = child_text(hwnd)
        buttons = buttons_for(hwnd)
        if not children and not buttons:
            return True
        if any(QUIET_MODE_NOTICE in item for item in children):
            return True
        title = window_text(hwnd)
        cls = class_name(hwnd)
        if cls != NATIVE_DIALOG_CLASS:
            owner = user32.GetWindow(hwnd, GW_OWNER)
            if not owner:
                return True  # top-level window: the application itself, not a prompt
            if _is_main_window(title, cls, _window_area(hwnd)):
                return True
        found.append(
            DialogInfo(
                hwnd=int(hwnd),
                title=title,
                class_name=cls,
                enabled=bool(user32.IsWindowEnabled(hwnd)),
                child_text=children,
                buttons=buttons,
            )
        )
        return True

    user32.EnumWindows(callback, 0)
    return found


@dataclass(frozen=True)
class UnreadableModal:
    """A modal that :func:`enumerate_dialogs` cannot read, inferred from its owner.

    CST 2026 raises history errors in a pure-Qt window with no child ``HWND``s, so
    there is nothing to read and nothing to press. It does leave one trace that is
    independent of window class and of locale: a modal disables its owner, so CST's
    own main window starts reporting ``IsWindowEnabled() == False``.

    That is a *detection*, not an answer. The window cannot be read, so no policy
    can defend clicking it; what this buys is that a stalled run says so, with a
    screenshot, instead of sitting silent until the timeout.
    """

    main_window: int
    main_title: str
    hwnd: int
    title: str
    class_name: str

    def fingerprint(self) -> str:
        parts = [self.main_title, self.title, self.class_name]
        return hashlib.sha256("\u0000".join(parts).encode("utf-8")).hexdigest()[:16]

    def to_json(self) -> dict[str, object]:
        return {
            "main_window": self.main_window,
            "main_title": self.main_title,
            "hwnd": self.hwnd,
            "title": self.title,
            "class_name": self.class_name,
            "fingerprint": self.fingerprint(),
        }


def unreadable_modals(pid: int) -> list[UnreadableModal]:
    """Modals blocking ``pid``'s main window that carry no readable controls.

    Returns nothing while the main window is enabled, which is the normal state
    even during long solver work, and nothing for prompts that
    :func:`enumerate_dialogs` can already read and answer.
    """
    blocked = [hwnd for hwnd in main_windows_for_pid(pid) if not user32.IsWindowEnabled(hwnd)]
    if not blocked:
        return []
    readable = {dialog.hwnd for dialog in enumerate_dialogs(pid)}

    owned: list[tuple[int, str, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        if int(hwnd) in readable or not user32.GetWindow(hwnd, GW_OWNER):
            return True
        title = window_text(hwnd)
        cls = class_name(hwnd)
        # Untitled owned windows are CST's decorative title-bar glow frames, and a
        # titled one the size of the application is the main window's own helper.
        if not title or _is_main_window(title, cls, _window_area(hwnd)):
            return True
        owned.append((int(hwnd), title, cls))
        return True

    user32.EnumWindows(callback, 0)

    main = blocked[0]
    main_title = window_text(main)
    return [
        UnreadableModal(
            main_window=main, main_title=main_title, hwnd=hwnd, title=title, class_name=cls
        )
        for hwnd, title, cls in owned
    ]


def main_windows_for_pid(pid: int) -> list[int]:
    """Top-level titled windows of ``pid``: the application's own windows.

    Used when a timeout fires with no actionable prompt in sight, so the human
    still gets a picture of whatever CST is showing -- including a pure-Qt modal
    that :func:`enumerate_dialogs` cannot see.
    """
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        if window_text(hwnd):
            found.append(int(hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return found


class ClickRefused(RuntimeError):
    """Raised when a dialog cannot be actuated deterministically."""


def press_button(dialog: DialogInfo, button: ButtonInfo) -> None:
    """Activate ``button`` by notifying the dialog procedure directly.

    ``WM_COMMAND`` to the dialog is used rather than ``BM_CLICK`` to the button.
    Both were tried against a real CST prompt: ``BM_CLICK`` left the dialog on
    screen indefinitely, while ``WM_COMMAND`` dismissed it immediately.
    ``BM_CLICK`` synthesises mouse messages on the control and depends on
    activation state, whereas ``WM_COMMAND`` reaches the handler that calls
    ``EndDialog``.  ``WM_CLOSE`` was also tried and had no effect at all.

    Refuses non-native dialogs: a Qt modal exposes no ``Button`` child controls,
    so there is nothing to notify and a silent no-op would look like a successful
    answer while CST stays blocked.
    """
    if not dialog.is_native:
        raise ClickRefused(
            f"dialog class {dialog.class_name!r} is not a native #32770 dialog; "
            "it has no Win32 button controls to activate"
        )
    if not button.enabled:
        raise ClickRefused(f"button {button.text!r} is disabled")
    if not user32.IsWindow(button.hwnd):
        raise ClickRefused(f"button {button.text!r} no longer exists")
    user32.SendMessageW(
        dialog.hwnd,
        WM_COMMAND,
        (button.control_id & 0xFFFF) | (BN_CLICKED << 16),
        button.hwnd,
    )


#: Buttons that abandon rather than commit, most declining first.  Used to release
#: a dialog whose operation has already been abandoned.
DECLINING_CONTROL_IDS = (IDCANCEL, IDNO, IDCLOSE, IDOK, IDYES)


def release_dialog(dialog: DialogInfo) -> ButtonInfo | None:
    """Dismiss a dialog whose caller is gone, preferring the least committal button.

    Killing a worker mid-prompt does not remove the prompt: it becomes an orphan
    that blocks CST's modeller for every later run.  Once the operation has been
    abandoned the answer cannot affect it, so releasing the GUI is safe -- but the
    declining button is chosen first, and the screenshot is always taken before
    this runs so the evidence shows the prompt as the engineer would have seen it.
    """
    if not dialog.is_native:
        return None
    enabled = [button for button in dialog.buttons if button.enabled]
    for control_id in DECLINING_CONTROL_IDS:
        for button in enabled:
            if button.control_id == control_id:
                press_button(dialog, button)
                return button
    return None


def dialog_is_gone(hwnd: int) -> bool:
    return not bool(user32.IsWindow(hwnd)) or not bool(user32.IsWindowVisible(hwnd))


def request_close(hwnd: int) -> None:
    """Post ``WM_CLOSE``.  Used only for windows we created ourselves in tests."""
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def capture_window(hwnd: int, path: Path) -> bool:
    from PIL import Image

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    width = max(1, rect.right - rect.left)
    height = max(1, rect.bottom - rect.top)
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old = gdi32.SelectObject(memory_dc, bitmap)
    try:
        user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT)
        info = ctypes.create_string_buffer(40)
        ctypes.memset(info, 0, 40)
        ctypes.cast(info, ctypes.POINTER(wintypes.DWORD))[0] = 40
        ctypes.cast(info, ctypes.POINTER(wintypes.LONG))[1] = width
        ctypes.cast(info, ctypes.POINTER(wintypes.LONG))[2] = -height
        ctypes.cast(info, ctypes.POINTER(wintypes.WORD))[6] = 1
        ctypes.cast(info, ctypes.POINTER(wintypes.WORD))[7] = 32
        ctypes.cast(info, ctypes.POINTER(wintypes.DWORD))[4] = 0
        pixels = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, info, 0):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.frombuffer("RGBA", (width, height), pixels, "raw", "BGRA", 0, 1).save(path)
        return True
    finally:
        gdi32.SelectObject(memory_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)
