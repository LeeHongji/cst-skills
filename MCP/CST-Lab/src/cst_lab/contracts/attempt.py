"""The ``attempt.json`` contract: one approved topology.

The three refusals in this module are the whole point of the attempt layer.  They
run before CST is touched, which is what makes them cheap enough to be
unconditional:

``check_topology``   the rebuilt IR must hash to the approved topology
``check_parameters`` every value must sit inside its approved range
``require_approval``  an unapproved attempt cannot run at all

Historically "is this still the same design or a new one?" was answered by
directory naming and self-discipline, which produced 35 project-shaped
directories and 118 sibling folders of the same family.  The topology hash makes
it a machine decision.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..paths import LabPaths
from ..validation import load_schema, validate_document

SCHEMA_NAME = "attempt.schema.json"

#: Default half-width of an approved range, as a fraction of the audited value.
DEFAULT_RANGE_FRACTION = 0.20


class ApprovalError(RuntimeError):
    """Raised when an attempt is not in a state that may run."""


class TopologyMismatch(RuntimeError):
    """Raised when the rebuilt model is not the structure that was approved."""


class RangeViolation(RuntimeError):
    """Raised when a parameter value falls outside its approved range."""


def load_attempt(path: Path, paths: LabPaths | None = None) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    resolved = paths or LabPaths.resolve()
    validate_document(document, load_schema(resolved.schemas_root, SCHEMA_NAME), resolved.schemas_root)
    return document


def write_attempt(path: Path, document: dict[str, Any], paths: LabPaths | None = None) -> Path:
    resolved = paths or LabPaths.resolve()
    validate_document(document, load_schema(resolved.schemas_root, SCHEMA_NAME), resolved.schemas_root)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def default_ranges(
    baseline: Mapping[str, float],
    *,
    fraction: float = DEFAULT_RANGE_FRACTION,
    only: Iterable[str] | None = None,
    overrides: Mapping[str, tuple[float, float]] | None = None,
) -> dict[str, list[float]]:
    """Build approved ranges as the audited value plus or minus ``fraction``.

    ``only`` restricts approval to the parameters that may actually move.  Leaving
    it out approves everything in ``baseline``, which is convenient and usually
    wrong: a parameter absent from the ranges is refused by
    :func:`check_parameters`, so a narrow ``only`` list fails closed while a broad
    one silently permits the loop to move a dimension nobody meant to tune.

    A baseline of exactly zero has no meaningful proportional band -- the range
    would collapse to ``[0, 0]`` and lock the parameter -- so it must be given an
    explicit override instead of being silently frozen.
    """
    if not 0 < fraction < 1:
        raise ValueError(f"fraction must be between 0 and 1, got {fraction}")
    names = list(baseline) if only is None else list(only)
    supplied = dict(overrides or {})
    ranges: dict[str, list[float]] = {}
    for name in names:
        if name in supplied:
            low, high = supplied[name]
            ranges[name] = [float(min(low, high)), float(max(low, high))]
            continue
        if name not in baseline:
            raise ValueError(f"cannot derive a range for {name!r}: it has no audited value")
        value = float(baseline[name])
        if value == 0.0:
            raise ValueError(
                f"{name!r} is 0 in the audited model, so a +/-{fraction:.0%} range would "
                "freeze it; give an explicit range if it is meant to move"
            )
        span = abs(value) * fraction
        ranges[name] = [value - span, value + span]
    for name in supplied:
        if name not in ranges:
            ranges[name] = [float(min(supplied[name])), float(max(supplied[name]))]
    return ranges


def require_approval(attempt: Mapping[str, Any]) -> None:
    """Refuse to run an attempt that no human has signed off on."""
    approval = attempt.get("approval")
    if not approval:
        raise ApprovalError(
            f"attempt {attempt['attempt_id']!r} has no approval record; generate audit.html "
            "and have it approved before iterating"
        )
    if approval["topology_hash"] != attempt["topology_hash"]:
        raise ApprovalError(
            f"attempt {attempt['attempt_id']!r} declares topology {attempt['topology_hash'][:12]} "
            f"but the approval was granted for {approval['topology_hash'][:12]}; the topology was "
            "edited after approval, so the signature no longer covers this structure"
        )


def check_topology(attempt: Mapping[str, Any], candidate: str) -> None:
    """Refuse a rebuilt model whose structure is not the approved one."""
    approved = attempt["topology_hash"]
    if candidate != approved:
        raise TopologyMismatch(
            f"rebuilt topology {candidate[:12]} does not match the approved "
            f"{approved[:12]} for attempt {attempt['attempt_id']!r}. Parameter values may move "
            "freely inside an attempt; structure may not. Open a new attempt and have the new "
            "topology audited."
        )


def check_parameters(attempt: Mapping[str, Any], values: Mapping[str, float]) -> None:
    """Refuse parameter values outside their approved range, or never approved.

    Both halves matter.  The range check is the backstop for the topology hash's
    blind spot: dimensions can walk far enough that the geometry no longer
    resembles the figure it was approved against while the structure is untouched.
    The unapproved-name check is what makes forgetting to approve a parameter a
    refusal rather than a licence.
    """
    ranges = attempt["approved_ranges"]
    unapproved = sorted(set(values) - set(ranges))
    if unapproved:
        raise RangeViolation(
            f"parameter(s) {unapproved} have no approved range in attempt "
            f"{attempt['attempt_id']!r}; approve a range for them or leave them alone. "
            f"Approved: {sorted(ranges)}"
        )
    outside = []
    for name, value in values.items():
        low, high = ranges[name]
        if not low <= float(value) <= high:
            outside.append(f"{name}={value:g} outside [{low:g}, {high:g}]")
    if outside:
        raise RangeViolation(
            "; ".join(outside)
            + ". Regenerate audit.html and re-approve: the audit does not touch CST, so a "
            "re-review costs almost nothing."
        )
