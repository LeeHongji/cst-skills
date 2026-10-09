"""Decision table mapping observed CST dialogs to a deterministic response.

The table is deliberately small.  Auto-answering a prompt means choosing on the
engineer's behalf, so a rule only earns a ``click`` action when the safe answer
is knowable from the dialog text alone, without knowing what the caller intended.

Applying that test to the five categories originally proposed:

``stale results``
    Safe to answer.  ``cst_iterate`` always re-solves after a parameter or
    geometry change, so results computed from the previous geometry have no
    value, and a ``Result/`` cache is not evidence in the first place.

``save changes``
    Not safe.  The right answer depends on whether the caller meant to keep the
    edit.  Prevented instead: callers save explicitly before closing, so this
    prompt means the session is in an unexpected state.

``overwrite file``
    Not safe.  Wanted for a re-exported curve, forbidden for a project file.
    Needs caller intent.

``project in use``
    Must stop.  Answering it would drive a second writer into a project another
    process holds, which the concurrency rule forbids outright.

``mesh / boundary warning``
    Must stop.  Dismissing it would produce results whose validity the solver
    itself just questioned.

So exactly one category auto-answers.  The remaining four are encoded as
``escalate`` rules rather than left unknown: recognising them yields a precise
reason and a specific remedy instead of a generic "unknown dialog" report.
Unrecognised dialogs still escalate, and the escalation record is what promotes
a new entry into this table after a human confirms the correct answer once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .win32_dialogs import IDOK, IDYES, ButtonInfo, DialogInfo

Action = Literal["click", "escalate"]

#: Win32 button captions carry ``&`` accelerator markers ("&Yes").
_ACCELERATOR = re.compile(r"&(?=\w)")


def normalize_button_text(text: str) -> str:
    return _ACCELERATOR.sub("", text).strip()


@dataclass(frozen=True)
class DialogRule:
    rule_id: str
    action: Action
    reason: str
    title_pattern: str | None = None
    text_pattern: str | None = None
    button_ids: tuple[int, ...] = ()
    button_pattern: str | None = None
    remedy: str | None = None

    def __post_init__(self) -> None:
        if self.title_pattern is None and self.text_pattern is None:
            raise ValueError(f"rule {self.rule_id!r} must constrain title or text")
        if self.action == "click" and not (self.button_ids or self.button_pattern):
            raise ValueError(
                f"rule {self.rule_id!r} has action 'click' but names no button; "
                "give button_ids (preferred) or button_pattern"
            )

    def matches(self, dialog: DialogInfo) -> bool:
        if self.title_pattern is not None:
            if not re.search(self.title_pattern, dialog.title, re.IGNORECASE):
                return False
        if self.text_pattern is not None:
            haystack = "\n".join((dialog.title, dialog.body_text))
            if not re.search(self.text_pattern, haystack, re.IGNORECASE):
                return False
        return True

    def choose_button(self, dialog: DialogInfo) -> ButtonInfo | None:
        """Pick the button to press, preferring the locale-invariant control id.

        Caption matching is a fallback for dialogs with non-standard controls.  It
        cannot be the primary mechanism: a Chinese CST install labels the same
        buttons "\u662f(&Y)" and "\u5426(&N)", so an English caption pattern would match
        nothing and the guardian would escalate every prompt it actually knows.
        """
        enabled = [button for button in dialog.buttons if button.enabled]
        for control_id in self.button_ids:
            for button in enabled:
                if button.control_id == control_id:
                    return button
        if not self.button_pattern:
            return None
        for button in enabled:
            if re.fullmatch(
                self.button_pattern, normalize_button_text(button.text), re.IGNORECASE
            ):
                return button
        return None


KNOWN_RULES: tuple[DialogRule, ...] = (
    DialogRule(
        rule_id="stale-results-discard",
        action="click",
        button_ids=(IDYES, IDOK),
        button_pattern=r"yes|ok|delete",
        reason=(
            "The change invalidates results computed from the previous geometry. "
            "cst_iterate always re-solves, and a Result/ cache is regenerable "
            "rather than evidence, so discarding it loses nothing."
        ),
        text_pattern=(
            r"results?\s+will\s+be\s+deleted"
            r"|delete\s+(the\s+|all\s+)?results?"
            r"|results?\s+(are|is)\s+(no\s+longer|not)\s+valid"
            r"|invalidat\w*\s+.*results?"
            r"|results?\s+.*invalidat"
        ),
    ),
    DialogRule(
        rule_id="project-in-use",
        action="escalate",
        reason=(
            "Another process holds this project. Answering would create a second "
            "writer, which the no-concurrent-write rule forbids."
        ),
        remedy=(
            "Identify the holding CST process and let it finish. Do not delete the "
            ".lok file to unblock; confirm no process holds the companion directory "
            "first, then remove the lock as a separate step."
        ),
        text_pattern=(
            r"already\s+(open|in\s+use)"
            r"|locked\s+by"
            r"|being\s+used\s+by\s+another"
            r"|cannot\s+.*because\s+it\s+is\s+open"
        ),
    ),
    DialogRule(
        rule_id="unsaved-changes",
        action="escalate",
        reason=(
            "Whether to keep the edit depends on caller intent, which the dialog "
            "text cannot supply. Callers are expected to save explicitly, so this "
            "prompt means the session reached an unexpected state."
        ),
        remedy="Save or discard deliberately in the calling code, then retry.",
        text_pattern=(
            r"save\s+(the\s+)?changes"
            r"|do\s+you\s+want\s+to\s+save"
            r"|unsaved\s+changes"
        ),
    ),
    DialogRule(
        rule_id="overwrite-existing-file",
        action="escalate",
        reason=(
            "Overwriting is wanted for a re-exported curve and forbidden for a "
            "project file. The dialog alone cannot distinguish the two."
        ),
        remedy="Pass an explicit overwrite decision from the caller, then retry.",
        text_pattern=(
            r"already\s+exists.*(replace|overwrite)"
            r"|(replace|overwrite)\s+(the\s+)?existing"
            r"|do\s+you\s+want\s+to\s+replace"
        ),
    ),
    DialogRule(
        rule_id="solver-quality-warning",
        action="escalate",
        reason=(
            "The solver is questioning mesh or boundary validity. Dismissing it "
            "would yield numbers whose validity the solver itself just doubted."
        ),
        remedy=(
            "Inspect the warning text, fix the mesh or boundary setup (or widen the "
            "DRC rule that should have caught it), then retry."
        ),
        text_pattern=(
            r"mesh\s+.*(warning|problem|too\s+coarse|failed)"
            r"|boundary\s+.*(warning|invalid|conflict)"
            r"|continue\s+anyway"
            r"|may\s+lead\s+to\s+(inaccurate|wrong)"
        ),
    ),
)


@dataclass(frozen=True)
class Decision:
    action: Action
    dialog: DialogInfo
    rule: DialogRule | None = None
    button: ButtonInfo | None = None
    detail: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "action": self.action,
            "rule_id": self.rule.rule_id if self.rule else None,
            "reason": self.rule.reason if self.rule else None,
            "remedy": self.rule.remedy if self.rule else None,
            "button": normalize_button_text(self.button.text) if self.button else None,
            "button_control_id": self.button.control_id if self.button else None,
            "button_standard_name": self.button.standard_name if self.button else None,
            "detail": self.detail,
            "dialog": self.dialog.to_json(),
        }


def decide(dialog: DialogInfo, rules: tuple[DialogRule, ...] = KNOWN_RULES) -> Decision:
    """Classify ``dialog`` into a click or an escalation.

    Escalates when several rules match: overlapping patterns mean the table is
    ambiguous about this prompt, and guessing between them is exactly the failure
    mode the table exists to prevent.
    """
    matched = [rule for rule in rules if rule.matches(dialog)]
    if not matched:
        return Decision(
            action="escalate",
            dialog=dialog,
            detail="no rule matched this dialog",
        )
    if len(matched) > 1:
        return Decision(
            action="escalate",
            dialog=dialog,
            detail=(
                "ambiguous: rules "
                + ", ".join(rule.rule_id for rule in matched)
                + " all matched"
            ),
        )
    rule = matched[0]
    if rule.action == "escalate":
        return Decision(action="escalate", dialog=dialog, rule=rule, detail=rule.reason)
    if not dialog.is_native:
        return Decision(
            action="escalate",
            dialog=dialog,
            rule=rule,
            detail=(
                f"rule {rule.rule_id!r} would answer this, but dialog class "
                f"{dialog.class_name!r} is not a native #32770 dialog and exposes "
                "no Win32 button controls to activate"
            ),
        )
    button = rule.choose_button(dialog)
    if button is None:
        offered = (
            ", ".join(
                f"{normalize_button_text(b.text)}(id={b.control_id})" for b in dialog.buttons
            )
            or "none"
        )
        return Decision(
            action="escalate",
            dialog=dialog,
            rule=rule,
            detail=(
                f"rule {rule.rule_id!r} matched but no enabled button matched "
                f"ids {list(rule.button_ids)} or caption {rule.button_pattern!r}; "
                f"offered: {offered}"
            ),
        )
    return Decision(action="click", dialog=dialog, rule=rule, button=button)
