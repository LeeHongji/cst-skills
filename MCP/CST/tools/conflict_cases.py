#!/usr/bin/env python3
"""Registry of CST conflict cases, and how to classify what CST does with them.

Quiet mode stops CST from asking, which is what the automation needs, but it
also means a conflict no longer announces itself.  The question this registry
answers is what actually happens to each class of conflict once nobody is there
to answer a prompt.  There are five possible answers and only two of them are
safe:

``raised``               CST raised an exception.  Safe: the caller finds out.
``refused_with_warning`` CST returned normally, logged a warning, and left the
                         state unchanged.  Dangerous: the call looks like it
                         worked.  This is the class that needs a code guard.
``applied_wrongly``      CST returned normally and changed the state to
                         something nonsensical.  Dangerous for the same reason,
                         and worse, because later steps build on it.
``blocked``              CST never returned.  Only the L2 watchdog catches this.
``applied``             CST did what was asked.

The classification is computed from observations, never assumed: the parameter's
value and expression are read back through CST's own accessors, the shape count
is compared, and CST's message queue is diffed.  A case that "did nothing" and a
case that "worked" are otherwise indistinguishable from the Python side.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConflictCase:
    """One deliberately wrong CST call, plus what to watch while it runs.

    ``statement`` is executed with ``model3d`` and ``project`` bound.  It is
    literal source from this file rather than caller input; the indirection
    exists so the parent process can run each case in a fresh CST instance
    without needing to know what the case does.
    """

    case_id: str
    category: str
    description: str
    statement: str
    #: Parameter whose value and expression are read before and after.
    watch_parameter: str | None = None
    #: Extra parameters to check for existence, e.g. one the case may create.
    watch_exists: tuple[str, ...] = field(default_factory=tuple)
    #: What a correct CST would do.  Used to flag cases whose real behaviour is
    #: worse than expected, not to decide the verdict.
    should: str = "reject"


_BRICK = (
    "With Brick\n"
    ".Reset\n"
    '.Name "{name}"\n'
    '.Component "{component}"\n'
    '.Material "{material}"\n'
    '.Xrange "{x0}", "{x1}"\n'
    '.Yrange "{y0}", "{y1}"\n'
    '.Zrange "{z0}", "{z1}"\n'
    ".Create\n"
    "End With\n"
)


def _brick(name: str, **kw) -> str:
    """A minimal Brick block.

    The default component is ``component1``, the one the project already uses.
    Creating into a fresh component instead was a defect in the first version of
    this registry: a brick named ``substrate`` in component ``conflict`` collides
    with nothing, so the duplicate-name and overlap cases were not testing a
    conflict at all and both reported a clean success.
    """
    values = {
        "name": name,
        "component": "component1",
        "material": "PEC",
        "x0": "0",
        "x1": "2",
        "y0": "0",
        "y1": "2",
        "z0": "0",
        "z1": "0.1",
    }
    values.update({k: str(v) for k, v in kw.items()})
    return _BRICK.format(**values)


CASES: tuple[ConflictCase, ...] = (
    # -- parameter conflicts -------------------------------------------------
    ConflictCase(
        case_id="param_unknown_name",
        category="parameter",
        description="StoreParameter on a name no parameter has",
        statement="model3d.StoreParameter('zz_no_such_param', '1.0')",
        watch_exists=("zz_no_such_param",),
        should="reject or create explicitly",
    ),
    ConflictCase(
        case_id="param_non_numeric",
        category="parameter",
        description="a value that is not a number and not an expression",
        statement="model3d.StoreParameter('l3', 'not_a_number')",
        watch_parameter="l3",
    ),
    ConflictCase(
        case_id="param_self_reference",
        category="parameter",
        description="an expression that refers to the parameter itself",
        statement="model3d.StoreParameter('l3', 'l3+1')",
        watch_parameter="l3",
    ),
    ConflictCase(
        case_id="param_undefined_reference",
        category="parameter",
        description="an expression referring to a parameter that does not exist",
        statement="model3d.StoreParameter('l3', 'zz_undefined*2')",
        watch_parameter="l3",
    ),
    ConflictCase(
        case_id="param_empty_value",
        category="parameter",
        description="an empty value",
        statement="model3d.StoreParameter('l3', '')",
        watch_parameter="l3",
    ),
    ConflictCase(
        case_id="param_negative_width",
        category="parameter",
        description="a negative line width, which cannot be built",
        statement=(
            "model3d.StoreParameter('wl', '-5.0'); "
            "model3d.RebuildOnParametricChange(False, False)"
        ),
        watch_parameter="wl",
    ),
    ConflictCase(
        case_id="param_zero_width",
        category="parameter",
        description="a zero line width: the topology_hash blind spot",
        statement=(
            "model3d.StoreParameter('wh', '0'); "
            "model3d.RebuildOnParametricChange(False, False)"
        ),
        watch_parameter="wh",
    ),
    ConflictCase(
        case_id="param_delete_in_use",
        category="parameter",
        description="delete a parameter the geometry still depends on",
        statement="model3d.DeleteParameter('l3')",
        watch_parameter="l3",
        watch_exists=("l3",),
    ),
    ConflictCase(
        case_id="param_huge_value",
        category="parameter",
        description="a length far outside the board, which breaks containment",
        statement=(
            "model3d.StoreParameter('l3', '10000'); "
            "model3d.RebuildOnParametricChange(False, False)"
        ),
        watch_parameter="l3",
        should="build but violate containment",
    ),
    # -- modelling conflicts -------------------------------------------------
    ConflictCase(
        case_id="model_duplicate_name",
        category="modelling",
        description="create a solid with a name that already exists",
        statement=(
            "model3d.add_to_history('conflict duplicate', "
            + repr(_brick("substrate"))
            + ")"
        ),
    ),
    ConflictCase(
        case_id="model_overlapping_solid",
        category="modelling",
        description=(
            "create a solid intersecting an existing one with no boolean "
            "resolution -- the classic CST modelling conflict"
        ),
        statement=(
            "model3d.add_to_history('conflict overlap', "
            + repr(
                _brick(
                    # Straddles the substrate in every axis, so CST cannot treat
                    # it as merely touching.
                    "overlap_probe",
                    x0="-1",
                    x1="sub_w/2",
                    y0="-1",
                    y1="sub_w/2",
                    z0="-0.1",
                    z1="sub_h/2",
                )
            )
            + ")"
        ),
    ),
    ConflictCase(
        case_id="model_overlapping_different_material",
        category="modelling",
        description=(
            "intersect an existing solid with a different material, which CST "
            "cannot resolve by merging"
        ),
        statement=(
            "model3d.add_to_history('conflict overlap material', "
            + repr(
                _brick(
                    "overlap_vacuum_probe",
                    material="Vacuum",
                    x0="-1",
                    x1="sub_w/2",
                    y0="-1",
                    y1="sub_w/2",
                    z0="-0.1",
                    z1="sub_h/2",
                )
            )
            + ")"
        ),
    ),
    ConflictCase(
        case_id="model_zero_thickness",
        category="modelling",
        description="a brick with zero extent in x",
        statement=(
            "model3d.add_to_history('conflict zero', "
            + repr(_brick("zero_probe", x0="1", x1="1"))
            + ")"
        ),
    ),
    ConflictCase(
        case_id="model_inverted_range",
        category="modelling",
        description="a brick whose x1 is less than x0",
        statement=(
            "model3d.add_to_history('conflict inverted', "
            + repr(_brick("inverted_probe", x0="5", x1="1"))
            + ")"
        ),
    ),
    ConflictCase(
        case_id="model_unknown_material",
        category="modelling",
        description="a brick referring to a material that is not defined",
        statement=(
            "model3d.add_to_history('conflict material', "
            + repr(_brick("material_probe", material="ZZ_No_Such_Material"))
            + ")"
        ),
    ),
    ConflictCase(
        case_id="model_bad_vba_syntax",
        category="modelling",
        description="syntactically invalid VBA",
        statement=(
            "model3d.add_to_history('conflict syntax', "
            "'With Brick\\n.Reset\\n.ThisIsNotACommand \"x\"\\n.Create\\nEnd With\\n')"
        ),
    ),
    ConflictCase(
        case_id="model_delete_missing",
        category="modelling",
        description="delete a solid that does not exist",
        statement=(
            "model3d.add_to_history('conflict delete', "
            "'Solid.Delete \"component1:zz_no_such_solid\"\\n')"
        ),
    ),
    # -- history and rebuild conflicts --------------------------------------
    ConflictCase(
        case_id="history_store_parameter",
        category="history",
        description=(
            "change a parameter from inside a history block -- known to be "
            "refused with a warning while appearing to succeed"
        ),
        statement=(
            "model3d.add_to_history('conflict param in history', "
            "'StoreParameter(\"l3\", \"13.0\")\\n')"
        ),
        watch_parameter="l3",
    ),
    ConflictCase(
        case_id="history_nested_rebuild",
        category="history",
        description="ask for a rebuild from inside a history block",
        statement=(
            "model3d.add_to_history('conflict nested rebuild', "
            "'StoreParameter(\"l3\", \"13.0\")\\nRebuild\\n')"
        ),
        watch_parameter="l3",
    ),
)


CASES_BY_ID = {case.case_id: case for case in CASES}


def classify(
    *,
    outcome: str,
    error: str | None,
    before: dict | None,
    after: dict | None,
    new_messages: list[dict],
) -> str:
    """Decide which behaviour CST exhibited.

    ``outcome`` is the process-level result the parent observed; everything else
    comes from CST's own accessors, read in the worker before and after the call.

    The absence of an after-observation is treated as its own verdict rather than
    as "nothing changed".  An earlier version compared the missing state against
    the before state, found them different, and reported ``applied`` for two
    cases where the worker had in fact crashed -- the most misleading possible
    answer, since the whole point of the matrix is to find calls that look like
    they worked.
    """
    if outcome == "blocked":
        return "blocked"
    if after is None:
        return "worker_crashed"
    if error:
        return "raised"

    changed = (before or {}) != after
    warned = any(m.get("type") in {"WARNING", "ERROR"} for m in new_messages)
    errored = any(m.get("type") == "ERROR" for m in new_messages)

    if not changed:
        if warned or errored:
            return "refused_with_warning"
        return "silently_ignored"
    return "applied_wrongly" if (warned or errored) else "applied"


#: Verdicts that leave the caller unable to tell that something went wrong.
UNSAFE_VERDICTS = frozenset(
    {
        "refused_with_warning",
        "silently_ignored",
        "applied_wrongly",
        "blocked",
        "worker_crashed",
    }
)
