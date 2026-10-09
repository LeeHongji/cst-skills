"""Refusals that stop a call from reaching CST at all.

L0-L4 deal with CST misbehaving.  This module deals with the opposite and more
common problem: CST behaving *agreeably*.  A quiet-mode conflict matrix over
nineteen deliberately wrong calls (evidence in
``cst_runs/guardian-conflict-matrix_20260910/matrix.json``) found that only five
of them raise.  The rest are accepted without a single message, which means the
caller has no way to distinguish them from success:

* ``StoreParameter`` on a name no parameter has **creates a new parameter**.  A
  typo in a parameter name therefore does nothing to the geometry and reports
  success, which is the worst possible outcome for an automated iteration loop.
* ``StoreParameter('l3', 'not_a_number')`` is accepted verbatim, and
  ``GetParameterSValue`` reads the garbage back, so a read-back check that only
  compares strings also passes.
* ``StoreParameter('l3', 'zz_undefined*2')`` is accepted with no message at all.
* ``StoreParameter('l3', 'l3+1')`` is accepted with an ``INFO`` message about a
  circular dependency -- not a warning, not an error.
* ``StoreParameter('l3', '')`` is silently ignored: no change, no message.
* ``DeleteParameter`` succeeds while ``DoesProjectDependOnParameter`` is true,
  leaving the geometry referring to a parameter that no longer exists.
* A conductor width driven to ``0`` rebuilds without complaint.  That is the
  ``topology_hash`` blind spot, and CST is measurably not going to catch it --
  which is why DRC is a structural requirement rather than a convention.

The guards here are deliberately conservative and explicit: each one refuses with
a message naming the alternative, so an agent that hits one is told what to do
instead rather than being left to retry the same call.  Anything a guard cannot
decide (whether ``0.2`` is a sensible gap) belongs to DRC and to the approved
parameter ranges, not here.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

#: Identifiers appearing in a CST parameter expression.
_IDENTIFIER = re.compile(r"(?<![\w.])([A-Za-z_]\w*)")

#: Functions CST evaluates inside expressions.  An identifier that is one of
#: these is not expected to be a parameter name.
EXPRESSION_FUNCTIONS = frozenset(
    {
        "abs",
        "acos",
        "asin",
        "atan",
        "atan2",
        "cos",
        "cosh",
        "exp",
        "log",
        "log10",
        "max",
        "min",
        "mod",
        "pi",
        "sin",
        "sinh",
        "sqr",
        "sqrt",
        "tan",
        "tanh",
    }
)

#: History commands that must never appear inside an ``add_to_history`` block.
#: ``Rebuild`` asks CST to rebuild from inside a rebuild; the parameter commands
#: fight the Parameter List, and when the block is replayed during a history
#: rebuild CST refuses them with "Prevented attempt to change the value for
#: parameter ... inside history rebuild" and keeps the old value.
FORBIDDEN_IN_HISTORY = {
    "Rebuild": (
        "a history block must not ask for a rebuild; add_to_history already "
        "triggers one, and nesting them fails with 'The rebuild operation cannot "
        "be used inside a structure macro'"
    ),
    "RebuildOnParametricChange": (
        "parametric rebuilds are driven from outside the history tree; call "
        "set_parameter() instead"
    ),
    "StoreParameter": (
        "change parameters through the Parameter List (set_parameter), not the "
        "history tree: a history block re-applies the value on every rebuild, and "
        "during a rebuild CST refuses it with a warning and keeps the old value"
    ),
    "DeleteParameter": "delete parameters outside the history tree",
    "RenameParameter": "rename parameters outside the history tree",
    "MsgBox": (
        "a modal prompt inside a history block blocks every future rebuild of "
        "this project, including unattended ones"
    ),
    "InputBox": "a history block must not ask the user for input",
}

#: Matches a forbidden command as a statement, not as part of a longer name.
_COMMAND = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*(?:\(|\b)")


class GuardViolation(ValueError):
    """Raised instead of letting a known-dangerous call reach CST."""


# -- parameter table access --------------------------------------------------


def parameter_names(model3d: Any) -> list[str]:
    count = int(model3d.GetNumberOfParameters())
    return [str(model3d.GetParameterName(index)) for index in range(count)]


def parameter_index(model3d: Any, name: str) -> int:
    for index in range(int(model3d.GetNumberOfParameters())):
        if str(model3d.GetParameterName(index)) == name:
            return index
    raise GuardViolation(f"parameter {name!r} does not exist in this project")


def parameter_expression(model3d: Any, name: str) -> str:
    return str(model3d.RestoreParameterExpression(name))


def parameter_number(model3d: Any, name: str) -> float:
    """The evaluated numeric value, which is what the geometry actually uses.

    ``GetParameterSValue`` returns the *expression*, so it reports
    ``'not_a_number'`` back happily.  Only the numeric accessor can tell whether
    CST could evaluate what it was given.
    """
    return float(model3d.GetParameterNValue(parameter_index(model3d, name)))


# -- checks ------------------------------------------------------------------


def check_value_syntax(
    name: str, value: str | float | int, known: Iterable[str]
) -> None:
    """Refuse a value CST would accept but could not evaluate to a number.

    Every identifier in the expression must already be a parameter or a known
    function.  That single rule catches three of the measured silent failures at
    once: a bare word like ``not_a_number`` is an unknown identifier, so is
    ``zz_undefined``, and a self-reference is caught separately below.
    """
    if isinstance(value, bool):
        raise GuardViolation(f"{name}: a boolean is not a CST parameter value")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise GuardViolation(f"{name}: {value!r} is not finite")
        return

    text = str(value).strip()
    if not text:
        raise GuardViolation(
            f"{name}: an empty value is silently ignored by CST, so the call "
            "would report success while changing nothing"
        )

    known_names = {str(item) for item in known}
    identifiers = set(_IDENTIFIER.findall(text))
    if name in identifiers:
        raise GuardViolation(
            f"{name}: the expression {text!r} refers to {name} itself; CST accepts "
            "this and only logs an INFO-level circular dependency notice"
        )
    unknown = sorted(
        item
        for item in identifiers
        if item not in known_names and item.lower() not in EXPRESSION_FUNCTIONS
    )
    if unknown:
        raise GuardViolation(
            f"{name}: expression {text!r} refers to unknown name(s) "
            f"{unknown}; CST would store it verbatim without complaint"
        )


def check_range(name: str, value: float, allowed: tuple[float, float] | None) -> None:
    """Refuse a value outside its approved range.

    Whether ``0`` is a valid conductor width is not something this module can
    know, and CST measurably will not object, so the decision has to come from
    the approved parameter ranges recorded at audit time.
    """
    if allowed is None:
        return
    low, high = min(allowed), max(allowed)
    if not low <= value <= high:
        raise GuardViolation(
            f"{name}: {value} is outside the approved range [{low}, {high}]; "
            "re-run the audit and re-approve before continuing"
        )


def check_history_code(code: str) -> None:
    """Refuse a history block containing a command that must not be there."""
    for match in _COMMAND.finditer(code):
        command = match.group(1)
        reason = FORBIDDEN_IN_HISTORY.get(command)
        if reason is not None:
            raise GuardViolation(f"{command} must not appear in a history block: {reason}")


# -- guarded operations ------------------------------------------------------


def set_parameter(
    model3d: Any,
    name: str,
    value: str | float | int,
    *,
    allowed_range: tuple[float, float] | None = None,
    create: bool = False,
    rebuild: bool = True,
) -> dict[str, object]:
    """Change a parameter, refusing every silent failure mode measured so far.

    ``create`` must be given explicitly to add a parameter.  Without it, a name
    CST does not know is a refusal rather than a new parameter, because the
    measured behaviour of ``StoreParameter`` on an unknown name is to create one
    -- so a typo would leave the geometry untouched and report success.

    Returns the before and after numbers, read back through CST's numeric
    accessor.  A change that did not take effect is raised, not returned.
    """
    known = parameter_names(model3d)
    exists = name in known
    if not exists and not create:
        raise GuardViolation(
            f"parameter {name!r} does not exist; CST would silently create it. "
            f"Pass create=True to add it deliberately. Known parameters: {known}"
        )
    if exists and create:
        raise GuardViolation(f"parameter {name!r} already exists; drop create=True")

    check_value_syntax(name, value, known)

    # A plain number can be range-checked before CST is touched at all, which is
    # the only way a rejected value never reaches the model.  An expression
    # cannot: its number is whatever CST evaluates it to, so it has to be stored
    # first and undone below if it turns out to be out of range.
    plain = isinstance(value, (int, float)) or _is_plain_number(str(value))
    if plain:
        check_range(name, float(value), allowed_range)

    before = parameter_number(model3d, name) if exists else None
    before_expression = parameter_expression(model3d, name) if exists else None

    model3d.StoreParameter(name, str(value))
    if rebuild:
        model3d.RebuildOnParametricChange(False, False)

    after = parameter_number(model3d, name)
    if not math.isfinite(after):
        _revert(model3d, name, before_expression, rebuild)
        raise GuardViolation(
            f"{name}: CST stored {value!r} but it does not evaluate to a finite "
            f"number (read back {after!r})"
        )
    if not plain:
        try:
            check_range(name, after, allowed_range)
        except GuardViolation:
            _revert(model3d, name, before_expression, rebuild)
            raise
    else:
        requested = float(value)
        if not math.isclose(after, requested, rel_tol=1e-9, abs_tol=1e-12):
            raise GuardViolation(
                f"{name}: asked for {requested} but CST reads back {after}; the "
                "change did not take effect"
            )
    return {
        "parameter": name,
        "before": before,
        "after": after,
        "expression": parameter_expression(model3d, name),
        "created": not exists,
    }


def _revert(model3d: Any, name: str, expression: str | None, rebuild: bool) -> None:
    """Put the parameter back the way it was after a refused change.

    Raising while leaving the bad value in the model would defeat the guard: the
    next call would read a model that had already accepted what we refused.
    """
    try:
        if expression is None:
            model3d.DeleteParameter(name)
        else:
            model3d.StoreParameter(name, expression)
        if rebuild:
            model3d.RebuildOnParametricChange(False, False)
    except Exception:  # pragma: no cover - best effort; the raise below matters more
        pass


def delete_parameter(model3d: Any, name: str, *, force: bool = False) -> None:
    """Delete a parameter, refusing to orphan geometry that still uses it.

    Measured: CST deletes it anyway, with no message, leaving the model
    referring to a name that no longer exists.
    """
    parameter_index(model3d, name)  # raises if absent
    if not force and bool(model3d.DoesProjectDependOnParameter(name)):
        raise GuardViolation(
            f"the model still depends on {name!r}; CST would delete it silently "
            "and leave the geometry referring to a missing parameter. Remove the "
            "dependency first, or pass force=True."
        )
    model3d.DeleteParameter(name)


def add_to_history(model3d: Any, title: str, code: str) -> None:
    """Add a named history block after refusing forbidden commands inside it."""
    if not title.strip():
        raise GuardViolation("a history block must have a name so it can be audited")
    check_history_code(code)
    model3d.add_to_history(title, code)


def _is_plain_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
