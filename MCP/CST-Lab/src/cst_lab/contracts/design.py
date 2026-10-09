"""The ``design.md`` contract: one device and its machine-readable gates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..paths import LabPaths
from ..validation import load_schema, validate_document
from .frontmatter import read_frontmatter, write_frontmatter

SCHEMA_NAME = "design.schema.json"

_METRIC = re.compile(r"^s(?P<out>\d+)_(?P<in>\d+)_(?P<unit>db|deg)$")

#: Metrics that are a relation between two S-parameters rather than one curve.
#: Mapped to the unit their values carry, which is what a report has to label.
DERIVED_METRICS = {
    "phase_shift_deg": "deg",
    "phase_deviation_deg": "deg",
    "amplitude_imbalance_db": "db",
}

#: Derived metrics whose value depends on which multiple of 360 degrees is chosen,
#: and which therefore cannot be evaluated without an anchor.
_NEEDS_ANCHOR = ("phase_shift_deg", "phase_deviation_deg")

#: Derived metrics that need a nominal value.  Both phase metrics do, for the same
#: reason: ``target`` is the value expected at the anchor frequency, and it is what
#: picks the 360 degree branch.  ``phase_deviation_deg`` then also measures from it.
_NEEDS_TARGET = ("phase_shift_deg", "phase_deviation_deg")


@dataclass(frozen=True)
class Derived:
    """The extra binding a derived metric needs and a single-curve metric does not.

    A four-port phase shifter is the case that forces this to exist.  Its headline
    specification, "180 degrees plus or minus 3.4 degrees", is not a property of any
    one S-parameter: it is the difference between the main line's S21 and the
    reference line's S43.  Nothing in an ``s<out>_<in>_<unit>`` metric name can say
    which pair is the main line, which is the reference, or which 360 degree branch
    the number 180 refers to, so a gate on it could only ever have been prose.
    """

    name: str
    main: tuple[int, int]
    reference: tuple[int, int]
    target: float | None = None
    anchor_ghz: float | None = None
    phase_convention: str = 'main-minus-reference'

    @property
    def unit(self) -> str:
        return DERIVED_METRICS[self.name]

    def describe(self) -> str:
        main = f"S{self.main[0]}{self.main[1]}"
        reference = f"S{self.reference[0]}{self.reference[1]}"
        text = f"{self.name} ({main} vs {reference}"
        if self.target is not None:
            text += f", target {self.target:g}"
        if self.anchor_ghz is not None:
            text += f", branch pinned at {self.anchor_ghz:g} GHz"
            text += f", {self.phase_convention}"
        return text + ")"


@dataclass(frozen=True)
class Gate:
    """One acceptance gate, resolved from frontmatter into something evaluable.

    Deliberately a value object with no reference back to the document: the loop
    evaluates gates against exported curve data long after the design file was
    read, and a gate that could still reach back into its source would invite the
    threshold being re-read from a file that has since changed.
    """

    id: str
    out_port: int
    in_port: int
    unit: str
    band_ghz: tuple[float, float]
    comparator: str
    threshold: float
    mode: str
    aggregate: str | None = None
    severity: str = "required"
    min_samples: int = 5
    note: str | None = None
    derived: Derived | None = None

    @property
    def metric(self) -> str:
        if self.derived is not None:
            return self.derived.name
        return f"s{self.out_port}_{self.in_port}_{self.unit}"

    @property
    def ports_used(self) -> tuple[int, ...]:
        """Every port this gate reads, so a design can check it has them all."""
        if self.derived is None:
            return (self.out_port, self.in_port)
        return (*self.derived.main, *self.derived.reference)

    def describe(self) -> str:
        low, high = self.band_ghz
        band = f"{low:g} GHz" if low == high else f"[{low:g}, {high:g}] GHz"
        where = "every point in" if self.mode == "pointwise" else f"{self.aggregate} over"
        subject = self.derived.describe() if self.derived is not None else self.metric
        return f"{subject} {where} {band} {self.comparator} {self.threshold:g}"


def _parse_derived(entry: dict[str, Any]) -> Derived:
    """Bind a derived metric to its two S-parameters, refusing partial declarations.

    Fail-closed on purpose.  Every missing field here has a tempting default -- take
    the first two ports as the main line, assume the target is whatever the
    threshold implies, pick the branch nearest zero -- and every one of those
    defaults would turn a mis-specified gate into a confident wrong verdict on a
    phase, which is the one quantity where being 360 degrees out looks perfect.
    """
    name = entry["metric"]
    gate_id = entry["id"]
    for field in ("main", "reference"):
        if entry.get(field) is None:
            raise ValueError(
                f"gate {gate_id}: {name} needs '{field}: [out, in]'; without it there is "
                "no way to know which S-parameter plays which role"
            )
    main = (int(entry["main"][0]), int(entry["main"][1]))
    reference = (int(entry["reference"][0]), int(entry["reference"][1]))
    if main == reference:
        raise ValueError(
            f"gate {gate_id}: main and reference are both S{main[0]}{main[1]}, "
            "which makes the metric identically zero"
        )

    target = entry.get("target")
    if name in _NEEDS_TARGET and target is None:
        raise ValueError(
            f"gate {gate_id}: {name} needs 'target', the value expected at the anchor "
            "frequency; it is what selects the 360 degree branch, and the threshold "
            "alone only says how far from it is acceptable"
        )
    if name not in _NEEDS_TARGET and target is not None:
        raise ValueError(f"gate {gate_id}: {name} does not use 'target'")

    anchor = entry.get("anchor_ghz")
    if name in _NEEDS_ANCHOR and anchor is None:
        raise ValueError(
            f"gate {gate_id}: {name} needs 'anchor_ghz'; a phase difference is only "
            "defined up to a multiple of 360 degrees, and which multiple is meant "
            "cannot be inferred from the sweep"
        )
    if name not in _NEEDS_ANCHOR and anchor is not None:
        raise ValueError(f"gate {gate_id}: {name} does not use 'anchor_ghz'")
    convention = entry.get('phase_convention', 'main-minus-reference')
    if convention not in ('main-minus-reference', 'reference-minus-main'):
        raise ValueError(f'gate {gate_id}: invalid phase_convention')
    if name not in _NEEDS_ANCHOR and 'phase_convention' in entry:
        raise ValueError(f'gate {gate_id}: {name} does not use phase_convention')

    return Derived(
        name=name,
        main=main,
        reference=reference,
        target=None if target is None else float(target),
        anchor_ghz=None if anchor is None else float(anchor),
        phase_convention=convention,
    )


def parse_gates(header: dict[str, Any]) -> list[Gate]:
    """Turn validated frontmatter into :class:`Gate` objects."""
    gates: list[Gate] = []
    seen: set[str] = set()
    for entry in header["acceptance"]:
        name = entry["metric"]
        derived: Derived | None = None
        if name in DERIVED_METRICS:
            derived = _parse_derived(entry)
            match = None
        else:
            match = _METRIC.match(name)
            if match is None:  # pragma: no cover - the schema pattern already rejects this
                raise ValueError(f"unsupported metric name: {name!r}")
            for field in ("main", "reference", "target", "anchor_ghz", "phase_convention"):
                if entry.get(field) is not None:
                    raise ValueError(
                        f"gate {entry['id']}: {name} is a single curve and ignores "
                        f"'{field}'; a field that is silently ignored is worse than a "
                        "missing one, because it reads as if it took effect"
                    )
        low, high = (float(entry["band_ghz"][0]), float(entry["band_ghz"][1]))
        if low > high:
            raise ValueError(f"gate {entry['id']}: band_ghz is inverted: [{low}, {high}]")
        if entry["id"] in seen:
            raise ValueError(f"duplicate gate id {entry['id']!r}; verdicts are recorded per id")
        seen.add(entry["id"])
        gates.append(
            Gate(
                id=entry["id"],
                out_port=derived.main[0] if derived else int(match.group("out")),
                in_port=derived.main[1] if derived else int(match.group("in")),
                unit=derived.unit if derived else match.group("unit"),
                derived=derived,
                band_ghz=(low, high),
                comparator=entry["comparator"],
                threshold=float(entry["threshold"]),
                mode=entry["mode"],
                aggregate=entry.get("aggregate"),
                severity=entry.get("severity", "required"),
                min_samples=int(entry.get("min_samples", 5)),
                note=entry.get("note"),
            )
        )
    return gates


def load_design(
    path: Path, paths: LabPaths | None = None
) -> tuple[dict[str, Any], list[Gate], str]:
    """Read and validate ``design.md``, returning header, gates and prose body."""
    header, body = read_frontmatter(path)
    resolved = paths or LabPaths.resolve()
    validate_document(header, load_schema(resolved.schemas_root, SCHEMA_NAME), resolved.schemas_root)
    directory = Path(path).parent.name
    if header["design_id"] != directory:
        raise ValueError(f"design_id {header['design_id']!r} does not match its directory {directory!r}")

    gates = parse_gates(header)
    declared = header.get("ports")
    if declared is not None:
        over = sorted({p for gate in gates for p in gate.ports_used if p > declared})
        if over:
            raise ValueError(
                f"design declares {declared} ports but its gates reference port(s) {over}; "
                "a gate on a port the model does not have can never be evaluated"
            )
    return header, gates, body


def write_design(
    path: Path, header: dict[str, Any], body: str, paths: LabPaths | None = None
) -> Path:
    resolved = paths or LabPaths.resolve()
    validate_document(header, load_schema(resolved.schemas_root, SCHEMA_NAME), resolved.schemas_root)
    parse_gates(header)
    return write_frontmatter(path, header, body)
