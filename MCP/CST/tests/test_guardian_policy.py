from __future__ import annotations

import pytest

from cst_guardian.policy import (
    KNOWN_RULES,
    DialogRule,
    decide,
    normalize_button_text,
)
from cst_guardian.win32_dialogs import ButtonInfo, DialogInfo

NATIVE = "#32770"

#: Windows assigns these ids to standard dialog buttons.  The fixture must honour
#: them, or a button captioned "Cancel" ends up carrying IDOK and the control-id
#: preference picks exactly the button the rule was written to avoid.
_STANDARD_IDS = {"ok": 1, "cancel": 2, "yes": 6, "no": 7, "close": 8}


def make_dialog(
    title: str = "CST Studio Suite",
    child_text: tuple[str, ...] = (),
    buttons: tuple[str, ...] = ("&Yes", "&No"),
    class_name: str = NATIVE,
    button_enabled: bool = True,
) -> DialogInfo:
    return DialogInfo(
        hwnd=1234,
        title=title,
        class_name=class_name,
        enabled=True,
        child_text=child_text,
        buttons=tuple(
            ButtonInfo(
                hwnd=2000 + i,
                text=text,
                control_id=_STANDARD_IDS.get(
                    normalize_button_text(text).lower(), 1000 + i
                ),
                enabled=button_enabled,
            )
            for i, text in enumerate(buttons)
        ),
    )


def localized_dialog() -> DialogInfo:
    """The real prompt observed from ``modeler_AMD64.exe`` on a Chinese install.

    Captured live: class ``#32770``, title ``VBA``, message text in English but
    button captions localised, with standard control ids 6 (IDYES) and 7 (IDNO).
    """
    return DialogInfo(
        hwnd=200358,
        title="VBA",
        class_name=NATIVE,
        enabled=True,
        child_text=("\u662f(&Y)", "\u5426(&N)", "The results will be deleted."),
        buttons=(
            ButtonInfo(hwnd=1, text="\u662f(&Y)", control_id=6, enabled=True),
            ButtonInfo(hwnd=2, text="\u5426(&N)", control_id=7, enabled=True),
        ),
    )


def test_localized_buttons_are_matched_by_control_id():
    """An English caption pattern matches nothing here; the control id must win."""
    decision = decide(localized_dialog())
    assert decision.action == "click"
    assert decision.button.control_id == 6
    assert decision.button.standard_name == "IDYES"


def test_control_id_is_preferred_over_a_matching_caption():
    """Ordering matters: ids are locale-invariant, captions are not."""
    dialog = DialogInfo(
        hwnd=1,
        title="CST",
        class_name=NATIVE,
        enabled=True,
        child_text=("The results will be deleted.",),
        # A decoy whose caption matches the fallback pattern but is not IDYES/IDOK.
        buttons=(
            ButtonInfo(hwnd=10, text="OK to all", control_id=99, enabled=True),
            ButtonInfo(hwnd=11, text="\u662f(&Y)", control_id=6, enabled=True),
        ),
    )
    decision = decide(dialog)
    assert decision.action == "click"
    assert decision.button.control_id == 6


def test_caption_fallback_still_works_for_nonstandard_controls():
    dialog = DialogInfo(
        hwnd=1,
        title="CST",
        class_name=NATIVE,
        enabled=True,
        child_text=("The results will be deleted.",),
        buttons=(ButtonInfo(hwnd=10, text="&Delete", control_id=1234, enabled=True),),
    )
    decision = decide(dialog)
    assert decision.action == "click"
    assert decision.button.control_id == 1234


def test_a_disabled_standard_button_falls_through_to_the_next_candidate():
    dialog = DialogInfo(
        hwnd=1,
        title="CST",
        class_name=NATIVE,
        enabled=True,
        child_text=("The results will be deleted.",),
        buttons=(
            ButtonInfo(hwnd=10, text="\u662f(&Y)", control_id=6, enabled=False),
            ButtonInfo(hwnd=11, text="OK", control_id=1, enabled=True),
        ),
    )
    decision = decide(dialog)
    assert decision.action == "click"
    assert decision.button.control_id == 1


def test_decision_records_the_control_id_for_audit():
    payload = decide(localized_dialog()).to_json()
    assert payload["button_control_id"] == 6
    assert payload["button_standard_name"] == "IDYES"


def test_accelerator_markers_are_stripped_for_matching():
    assert normalize_button_text("&Yes") == "Yes"
    assert normalize_button_text("Save && Close") == "Save && Close"
    assert normalize_button_text("  &OK  ") == "OK"


@pytest.mark.parametrize(
    "text",
    [
        "The results will be deleted.",
        "Do you want to delete all results?",
        "Existing results are no longer valid.",
        "This change will invalidate the existing results.",
    ],
)
def test_stale_results_variants_are_answered(text):
    decision = decide(make_dialog(child_text=(text,)))
    assert decision.action == "click"
    assert decision.rule is not None
    assert decision.rule.rule_id == "stale-results-discard"
    assert normalize_button_text(decision.button.text) == "Yes"


def test_stale_results_prefers_an_affirmative_button_over_position():
    decision = decide(
        make_dialog(child_text=("The results will be deleted.",), buttons=("Cancel", "&OK"))
    )
    assert decision.action == "click"
    assert normalize_button_text(decision.button.text) == "OK"


def test_unknown_dialog_escalates():
    decision = decide(make_dialog(child_text=("Something entirely new happened.",)))
    assert decision.action == "escalate"
    assert decision.rule is None
    assert "no rule matched" in decision.detail


@pytest.mark.parametrize(
    ("text", "rule_id"),
    [
        ("The project is already open in another session.", "project-in-use"),
        ("Do you want to save the changes?", "unsaved-changes"),
        ("File already exists. Replace it?", "overwrite-existing-file"),
        ("Mesh warning detected. Continue anyway?", "solver-quality-warning"),
    ],
)
def test_known_but_unsafe_dialogs_escalate_with_a_named_rule(text, rule_id):
    """These are recognised so the report names a remedy instead of 'unknown'."""
    decision = decide(make_dialog(child_text=(text,)))
    assert decision.action == "escalate"
    assert decision.rule is not None
    assert decision.rule.rule_id == rule_id
    assert decision.rule.remedy


def test_ambiguous_match_escalates_rather_than_picking_one():
    rules = (
        DialogRule(
            rule_id="first",
            action="click",
            button_pattern="yes",
            reason="r",
            text_pattern="overlap",
        ),
        DialogRule(
            rule_id="second",
            action="click",
            button_pattern="no",
            reason="r",
            text_pattern="overlap",
        ),
    )
    decision = decide(make_dialog(child_text=("overlap",)), rules)
    assert decision.action == "escalate"
    assert "ambiguous" in decision.detail
    assert "first" in decision.detail and "second" in decision.detail


def test_non_native_dialog_is_never_clicked():
    decision = decide(
        make_dialog(child_text=("The results will be deleted.",), class_name="QWidget")
    )
    assert decision.action == "escalate"
    assert decision.rule is not None
    assert "not a native" in decision.detail


def test_matching_rule_without_a_usable_button_escalates():
    decision = decide(
        make_dialog(child_text=("The results will be deleted.",), buttons=("Cancel",))
    )
    assert decision.action == "escalate"
    assert "no enabled button matched" in decision.detail
    assert "Cancel" in decision.detail


def test_disabled_buttons_are_not_selected():
    decision = decide(
        make_dialog(
            child_text=("The results will be deleted.",),
            buttons=("&Yes",),
            button_enabled=False,
        )
    )
    assert decision.action == "escalate"


def test_title_is_searched_as_well_as_child_text():
    decision = decide(make_dialog(title="Delete results", child_text=()))
    assert decision.action == "click"


def test_rule_requires_a_pattern():
    with pytest.raises(ValueError, match="must constrain title or text"):
        DialogRule(rule_id="bad", action="escalate", reason="r")


def test_click_rule_must_name_a_button():
    with pytest.raises(ValueError, match="names no button"):
        DialogRule(rule_id="bad", action="click", reason="r", text_pattern="x")


def test_exactly_one_shipped_rule_auto_answers():
    """Guards the deliberate decision that only stale results is safe a priori."""
    clickable = [rule.rule_id for rule in KNOWN_RULES if rule.action == "click"]
    assert clickable == ["stale-results-discard"]


def test_every_escalating_rule_states_a_remedy():
    for rule in KNOWN_RULES:
        if rule.action == "escalate":
            assert rule.remedy, f"rule {rule.rule_id} escalates without a remedy"


def test_quiet_mode_banner_text_is_not_a_known_rule():
    from cst_guardian.win32_dialogs import QUIET_MODE_NOTICE

    decision = decide(make_dialog(child_text=(QUIET_MODE_NOTICE,)))
    assert decision.action == "escalate"
    assert decision.rule is None
