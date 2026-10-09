"""Guards against the calls CST accepts without complaint.

Every test here names the measured CST behaviour it exists to prevent.  The
measurements are in ``cst_runs/guardian-conflict-matrix_20260910/matrix.json``:
of nineteen deliberately wrong calls made with quiet mode on, only five raised.

The fake below reproduces the parts of that behaviour that matter, in particular
the split between the two accessors -- ``GetParameterSValue`` returns the stored
*expression* and ``GetParameterNValue`` the evaluated number -- because a
read-back check that consults only the first one passes for a garbage value.
"""

from __future__ import annotations

import pytest

from cst_guardian import preconditions as pre
from cst_guardian.preconditions import GuardViolation


class FakeModel3D:
    """A parameter table that behaves the way CST measurably does."""

    def __init__(self, parameters: dict[str, str] | None = None) -> None:
        self.parameters: dict[str, str] = dict(parameters or {})
        self.history: list[tuple[str, str]] = []
        self.rebuilds = 0
        self.deleted: list[str] = []
        self.dependencies: set[str] = set(self.parameters)

    # -- accessors CST provides ------------------------------------------
    def GetNumberOfParameters(self) -> int:
        return len(self.parameters)

    def GetParameterName(self, index: int) -> str:
        return list(self.parameters)[index]

    def GetParameterSValue(self, index: int) -> str:
        return self.parameters[list(self.parameters)[index]]

    def GetParameterNValue(self, index: int) -> float:
        return self._evaluate(self.parameters[list(self.parameters)[index]])

    def RestoreParameterExpression(self, name: str) -> str:
        return self.parameters.get(name, "")

    def DoesParameterExist(self, name: str) -> bool:
        return name in self.parameters

    def DoesProjectDependOnParameter(self, name: str) -> bool:
        return name in self.dependencies

    # -- mutators --------------------------------------------------------
    def StoreParameter(self, name: str, value: str) -> None:
        """Accept anything, exactly as CST does, including unknown names."""
        self.parameters[name] = str(value)

    def DeleteParameter(self, name: str) -> None:
        self.parameters.pop(name, None)
        self.deleted.append(name)

    def RebuildOnParametricChange(self, *_args) -> None:
        self.rebuilds += 1

    def add_to_history(self, title: str, code: str) -> None:
        self.history.append((title, code))

    def _evaluate(self, expression: str) -> float:
        """Evaluate the way CST does: arithmetic over the parameter table.

        A fake that only accepted bare numbers would make ``wl*2`` look like a
        value CST cannot evaluate, and the tests would then be asserting the
        fake's limitation rather than the guard's behaviour.
        """
        import math as _math

        text = str(expression).strip()
        if _is_number(text):
            return float(text)
        environment = {
            key: float(value)
            for key, value in self.parameters.items()
            if _is_number(value)
        }
        environment.update(
            sqrt=_math.sqrt, sqr=lambda x: x * x, sin=_math.sin, cos=_math.cos
        )
        try:
            return float(eval(expression, {"__builtins__": {}}, environment))  # noqa: S307
        except Exception:
            return float("nan")  # CST cannot evaluate it either


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


@pytest.fixture
def model() -> FakeModel3D:
    return FakeModel3D({"l3": "13.9312", "wh": "0.3543", "wl": "5.1049"})


# -- parameter names ---------------------------------------------------------


def test_an_unknown_parameter_name_is_refused(model):
    """Measured: StoreParameter on an unknown name creates a parameter (12 -> 13).

    A typo in a param_delta key would therefore leave the geometry untouched and
    report success, which is the one outcome an iteration loop cannot detect.
    """
    with pytest.raises(GuardViolation, match="silently create"):
        pre.set_parameter(model, "l3_typo", 14.0)
    assert "l3_typo" not in model.parameters
    assert model.rebuilds == 0, "CST must not be touched at all"


def test_creating_a_parameter_requires_saying_so(model):
    result = pre.set_parameter(model, "new_gap", 0.2, create=True)
    assert result["created"] is True
    assert model.parameters["new_gap"] == "0.2"


def test_create_is_refused_when_the_parameter_already_exists(model):
    with pytest.raises(GuardViolation, match="already exists"):
        pre.set_parameter(model, "l3", 14.0, create=True)


# -- parameter values --------------------------------------------------------


def test_a_non_numeric_value_is_refused(model):
    """Measured: l3 becomes the literal string 'not_a_number', no message."""
    with pytest.raises(GuardViolation, match="unknown name"):
        pre.set_parameter(model, "l3", "not_a_number")
    assert model.parameters["l3"] == "13.9312"


def test_an_expression_referring_to_nothing_is_refused(model):
    """Measured: 'zz_undefined*2' is stored verbatim with zero messages."""
    with pytest.raises(GuardViolation, match=r"zz_undefined"):
        pre.set_parameter(model, "l3", "zz_undefined*2")


def test_a_self_referring_expression_is_refused(model):
    """Measured: CST accepts 'l3+1' and logs only an INFO-level notice."""
    with pytest.raises(GuardViolation, match="refers to l3 itself"):
        pre.set_parameter(model, "l3", "l3+1")


def test_an_empty_value_is_refused(model):
    """Measured: silently ignored -- no change, no message, call looks fine."""
    with pytest.raises(GuardViolation, match="empty value"):
        pre.set_parameter(model, "l3", "")


def test_an_expression_over_existing_parameters_is_allowed(model):
    result = pre.set_parameter(model, "l3", "wl*2")
    assert model.parameters["l3"] == "wl*2"
    assert result["expression"] == "wl*2"


def test_expression_functions_are_not_mistaken_for_parameters(model):
    pre.set_parameter(model, "l3", "sqrt(wl)*2")
    assert model.parameters["l3"] == "sqrt(wl)*2"


def test_a_non_finite_number_is_refused(model):
    with pytest.raises(GuardViolation, match="not finite"):
        pre.set_parameter(model, "l3", float("inf"))


def test_a_boolean_is_refused(model):
    with pytest.raises(GuardViolation, match="boolean"):
        pre.set_parameter(model, "l3", True)


# -- read-back ---------------------------------------------------------------


def test_a_change_that_does_not_take_effect_is_raised(model, monkeypatch):
    """CST's way of refusing a parameter change is to keep the old value."""
    monkeypatch.setattr(model, "StoreParameter", lambda name, value: None)
    with pytest.raises(GuardViolation, match="did not take effect"):
        pre.set_parameter(model, "l3", 14.0)


def test_a_value_cst_cannot_evaluate_is_raised_even_if_stored(model, monkeypatch):
    """The numeric accessor is the only one that reveals an unevaluable value."""
    monkeypatch.setattr(pre, "check_value_syntax", lambda *a, **k: None)
    with pytest.raises(GuardViolation, match="finite number"):
        pre.set_parameter(model, "l3", "not_a_number")


def test_a_successful_change_reports_before_and_after(model):
    result = pre.set_parameter(model, "l3", 14.5)
    assert result["before"] == pytest.approx(13.9312)
    assert result["after"] == pytest.approx(14.5)
    assert model.rebuilds == 1


def test_the_rebuild_can_be_deferred(model):
    pre.set_parameter(model, "l3", 14.5, rebuild=False)
    assert model.rebuilds == 0


# -- approved ranges ---------------------------------------------------------


def test_a_value_outside_the_approved_range_is_refused(model):
    """CST measurably builds a zero-width conductor without complaint, so the
    only thing that can refuse it is the range approved at audit time."""
    with pytest.raises(GuardViolation, match="outside the approved range"):
        pre.set_parameter(model, "wh", 0.0, allowed_range=(0.28, 0.43))
    assert model.parameters["wh"] == "0.3543", "the value must never reach the model"
    assert model.rebuilds == 0, "CST must not be touched for a number we can check"


def test_an_out_of_range_expression_is_undone_before_raising(model):
    """An expression's number is only known once CST has evaluated it, so the
    change has to be made and then undone; leaving it in place would mean the
    next call reads a model that already accepted what we refused."""
    with pytest.raises(GuardViolation, match="outside the approved range"):
        pre.set_parameter(model, "wh", "wl*2", allowed_range=(0.28, 0.43))
    assert model.parameters["wh"] == "0.3543"
    assert pre.parameter_number(model, "wh") == pytest.approx(0.3543)


def test_a_newly_created_parameter_is_removed_again_if_it_is_refused(model):
    with pytest.raises(GuardViolation, match="outside the approved range"):
        pre.set_parameter(
            model, "new_gap", "wl*2", allowed_range=(0.1, 0.3), create=True
        )
    assert "new_gap" not in model.parameters


def test_a_value_inside_the_approved_range_is_allowed(model):
    pre.set_parameter(model, "wh", 0.40, allowed_range=(0.28, 0.43))
    assert model.parameters["wh"] == "0.4"


def test_a_range_given_in_either_order_behaves_the_same(model):
    pre.set_parameter(model, "wh", 0.40, allowed_range=(0.43, 0.28))


# -- parameter deletion ------------------------------------------------------


def test_deleting_a_parameter_in_use_is_refused(model):
    """Measured: CST deletes it anyway, with no message, orphaning the geometry."""
    with pytest.raises(GuardViolation, match="still depends on"):
        pre.delete_parameter(model, "l3")
    assert "l3" in model.parameters


def test_deleting_an_unused_parameter_is_allowed(model):
    model.dependencies.discard("wl")
    pre.delete_parameter(model, "wl")
    assert "wl" not in model.parameters


def test_deleting_a_parameter_in_use_can_be_forced(model):
    pre.delete_parameter(model, "l3", force=True)
    assert model.deleted == ["l3"]


def test_deleting_a_missing_parameter_is_refused(model):
    with pytest.raises(GuardViolation, match="does not exist"):
        pre.delete_parameter(model, "zz_missing")


# -- history blocks ----------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    ["Rebuild", "RebuildOnParametricChange", "StoreParameter", "DeleteParameter", "MsgBox"],
)
def test_forbidden_history_commands_are_refused(model, command):
    code = f'{command} "l3", "13.0"\n'
    with pytest.raises(GuardViolation, match=command):
        pre.add_to_history(model, "probe", code)
    assert model.history == []


def test_every_forbidden_command_explains_the_alternative():
    """A refusal that does not say what to do instead just gets retried."""
    for command, reason in pre.FORBIDDEN_IN_HISTORY.items():
        assert len(reason) > 30, command
        assert reason == reason.strip()


def test_a_legitimate_history_block_is_passed_through(model):
    code = 'With Brick\n.Reset\n.Name "trace"\n.Create\nEnd With\n'
    pre.add_to_history(model, "add trace", code)
    assert model.history == [("add trace", code)]


def test_make_sure_parameter_exists_is_allowed_in_history(model):
    """CST's own diagnostics recommend it as the in-history alternative."""
    pre.add_to_history(model, "declare", 'MakeSureParameterExists("gap", "0.2")\n')
    assert model.history


def test_a_history_block_must_be_named(model):
    with pytest.raises(GuardViolation, match="must have a name"):
        pre.add_to_history(model, "  ", "Solid.Delete \"a:b\"\n")


def test_a_word_containing_a_forbidden_command_is_not_refused(model):
    """``PreRebuildHelper`` is not ``Rebuild``; substring matching would break
    legitimate blocks and teach the caller to bypass the guard."""
    pre.add_to_history(model, "ok", "PreRebuildHelper 1\nMyStoreParameterLog 2\n")
    assert model.history
