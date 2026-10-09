"""CST session guardian: quiet automation with auditable dialog handling.

Four layers, from cheapest to most expensive:

``L0`` prevention
    DRC runs before CST is touched at all.  Most blocking prompts come from
    modelling conflicts, and a conflict caught in the IR never reaches the
    solver.  Implemented in ``cst_cad.drc``; the guardian only requires that the
    caller ran it.

``L1`` suppression
    :class:`~cst_guardian.session.GuardedSession` turns quiet mode on for the
    life of the session and restores the previous state on exit.

``L2`` watchdog
    :func:`~cst_guardian.supervisor.run_guarded` runs the CST work in a killable
    subprocess under a timeout, so a blocked COM call cannot freeze the caller.

``L3`` known-dialog response
    :mod:`cst_guardian.policy` maps a recognised prompt to one deterministic
    button, selected by its locale-invariant Win32 control id and activated by
    notifying the dialog procedure with ``WM_COMMAND``.

``L4`` escalation
    Anything unrecognised, ambiguous, or not reliably actuable is screenshotted
    and handed to a human.  That record is how a new entry enters the L3 table.

Quiet mode and DRC ship together on purpose: suppression alone converts a visible
hang into a silent default, which is worse than the hang.

``L-1`` refusal
    :mod:`cst_guardian.preconditions` sits below all of it.  A quiet-mode conflict
    matrix over nineteen deliberately wrong calls found that only five raise: CST
    accepts a garbage parameter value, an expression referring to nothing, a
    conductor width of zero, and the deletion of a parameter the geometry still
    uses, all without a single message.  Those calls never reach CST.
"""

from __future__ import annotations

from .paths import (
    CSTNotFound,
    cst_instance_pids,
    cst_process_family_pids,
    discover_cst_root,
    ensure_cst_paths,
    running_cst_pids,
    running_design_environment_pids,
)
from .policy import KNOWN_RULES, Decision, DialogRule, decide, normalize_button_text
from .preconditions import (
    FORBIDDEN_IN_HISTORY,
    GuardViolation,
    add_to_history,
    check_history_code,
    check_range,
    check_value_syntax,
    delete_parameter,
    parameter_names,
    parameter_number,
    set_parameter,
)
from .session import GuardedSession, SessionInfo
from .supervisor import GuardReport, run_guarded
from .win32_dialogs import (
    IDCANCEL,
    IDNO,
    IDOK,
    IDYES,
    ButtonInfo,
    ClickRefused,
    DialogInfo,
    capture_window,
    enumerate_dialogs,
    main_windows_for_pid,
    press_button,
    release_dialog,
)

__all__ = [
    "ButtonInfo",
    "CSTNotFound",
    "ClickRefused",
    "Decision",
    "DialogInfo",
    "DialogRule",
    "FORBIDDEN_IN_HISTORY",
    "GuardReport",
    "GuardViolation",
    "GuardedSession",
    "IDCANCEL",
    "IDNO",
    "IDOK",
    "IDYES",
    "KNOWN_RULES",
    "SessionInfo",
    "add_to_history",
    "capture_window",
    "check_history_code",
    "check_range",
    "check_value_syntax",
    "cst_instance_pids",
    "cst_process_family_pids",
    "decide",
    "delete_parameter",
    "discover_cst_root",
    "ensure_cst_paths",
    "enumerate_dialogs",
    "main_windows_for_pid",
    "normalize_button_text",
    "parameter_names",
    "parameter_number",
    "press_button",
    "release_dialog",
    "run_guarded",
    "running_cst_pids",
    "running_design_environment_pids",
    "set_parameter",
]
