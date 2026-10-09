"""Automatic acceptance verdicts from exported curve data.

The evaluator has one non-obvious job: refusing to answer.  A gate applied to a
curve that does not cover its band, or covers it with three samples, returns
``error`` rather than ``pass``.  Getting that wrong is worse than a wrong
threshold, because a vacuous pass looks exactly like a real one and would let a
design be declared met on a sweep too coarse to see the feature it was judging.

Band edges are interpolated and included in pointwise judgements.  Without them a
gate on ``[0.98, 1.14] GHz`` evaluated on samples at 0.975 and 1.025 GHz would
judge only the interior points and could miss a violation that straddles the edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .design import Gate
from .touchstone import (
    Touchstone,
    amplitude_imbalance_db,
    curve,
    phase_difference_deg,
)

COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    "<": lambda value, threshold: value < threshold,
    "<=": lambda value, threshold: value <= threshold,
    ">": lambda value, threshold: value > threshold,
    ">=": lambda value, threshold: value >= threshold,
}

AGGREGATORS: dict[str, Callable[[Sequence[float]], float]] = {
    "min": min,
    "max": max,
    "mean": lambda values: sum(values) / len(values),
    "ripple": lambda values: max(values) - min(values),
}


@dataclass
class GateResult:
    """One gate's verdict plus enough context to see why."""

    id: str
    status: str
    metric: str
    describe: str
    severity: str = "required"
    measured: float | None = None
    threshold: float | None = None
    samples_in_band: int = 0
    worst_frequency_ghz: float | None = None
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        record = {
            "id": self.id,
            "status": self.status,
            "metric": self.metric,
            "gate": self.describe,
            "severity": self.severity,
            "measured": self.measured,
            "threshold": self.threshold,
            "samples_in_band": self.samples_in_band,
        }
        if self.worst_frequency_ghz is not None:
            record["worst_frequency_ghz"] = self.worst_frequency_ghz
        if self.reason is not None:
            record["reason"] = self.reason
        return record


@dataclass
class GateReport:
    status: str
    gates: list[GateResult] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"status": self.status, "gates": [gate.to_json() for gate in self.gates]}


def _interpolate(x: Sequence[float], y: Sequence[float], at: float) -> float | None:
    if not x or at < x[0] or at > x[-1]:
        return None
    for index in range(1, len(x)):
        if x[index] >= at:
            x0, x1 = x[index - 1], x[index]
            y0, y1 = y[index - 1], y[index]
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (at - x0) / (x1 - x0)
    return y[-1]


def _band_samples(
    frequencies_ghz: Sequence[float], values: Sequence[float], low: float, high: float
) -> tuple[list[float], list[float], int]:
    """Return the band's samples with interpolated edges, and the real-sample count."""
    interior_f = [f for f in frequencies_ghz if low <= f <= high]
    interior_v = [v for f, v in zip(frequencies_ghz, values) if low <= f <= high]
    real = len(interior_f)

    points = list(zip(interior_f, interior_v))
    for edge in (low, high):
        if edge not in interior_f:
            interpolated = _interpolate(frequencies_ghz, values, edge)
            if interpolated is not None:
                points.append((edge, interpolated))
    points.sort()
    if not points:
        return [], [], 0
    return [f for f, _ in points], [v for _, v in points], real


def _values_for(gate: Gate, data: Touchstone) -> tuple[float, ...]:
    """The curve a gate judges: one S-parameter, or a relation between two."""
    spec = gate.derived
    if spec is None:
        return curve(data, gate.out_port, gate.in_port, gate.unit)
    if spec.name == "amplitude_imbalance_db":
        return amplitude_imbalance_db(data, spec.main, spec.reference)

    # parse_gates refuses either phase metric without both of these.
    assert spec.anchor_ghz is not None and spec.target is not None
    first, second = (spec.reference, spec.main) if spec.phase_convention == 'reference-minus-main' else (spec.main, spec.reference)
    shift = phase_difference_deg(data, first, second, spec.anchor_ghz, spec.target)
    if spec.name == "phase_shift_deg":
        return shift
    return tuple(abs(value - spec.target) for value in shift)


def evaluate_gate(gate: Gate, data: Touchstone) -> GateResult:
    """Judge one gate against one exported curve."""
    result = GateResult(
        id=gate.id,
        status="error",
        metric=gate.metric,
        describe=gate.describe(),
        severity=gate.severity,
        threshold=gate.threshold,
    )

    try:
        values = _values_for(gate, data)
    except ValueError as exc:
        result.reason = str(exc)
        return result

    frequencies_ghz = [f / 1e9 for f in data.frequencies_hz]
    low, high = gate.band_ghz
    if not frequencies_ghz:
        result.reason = f"{data.path.name} contains no frequency samples"
        return result
    covered_low, covered_high = frequencies_ghz[0], frequencies_ghz[-1]
    if low < covered_low - 1e-12 or high > covered_high + 1e-12:
        result.reason = (
            f"band [{low:g}, {high:g}] GHz is not covered by the sweep "
            f"[{covered_low:g}, {covered_high:g}] GHz; widen the sweep rather than "
            "judging the part that happens to be there"
        )
        return result

    band_f, band_v, real_samples = _band_samples(frequencies_ghz, values, low, high)
    result.samples_in_band = real_samples
    if not band_v:
        result.reason = f"no samples fall inside [{low:g}, {high:g}] GHz"
        return result
    if low != high and real_samples < gate.min_samples:
        result.reason = (
            f"only {real_samples} real sample(s) inside [{low:g}, {high:g}] GHz, "
            f"below the {gate.min_samples} this gate requires; the sweep is too coarse "
            "for the verdict to mean anything"
        )
        return result

    compare = COMPARATORS[gate.comparator]
    if gate.mode == "pointwise":
        # Report the sample furthest from satisfying the gate, which is the one an
        # engineer would look at first.
        worst_index = max(
            range(len(band_v)),
            key=lambda i: band_v[i] if gate.comparator in ("<", "<=") else -band_v[i],
        )
        result.measured = band_v[worst_index]
        result.worst_frequency_ghz = band_f[worst_index]
        result.status = "pass" if all(compare(v, gate.threshold) for v in band_v) else "fail"
        return result

    aggregate = AGGREGATORS[gate.aggregate or ""]
    result.measured = aggregate(band_v)
    result.status = "pass" if compare(result.measured, gate.threshold) else "fail"
    return result


def evaluate_gates(gates: Sequence[Gate], data: Touchstone) -> GateReport:
    """Judge every gate and reduce them to one status.

    A ``desired`` gate that fails does not fail the iteration; a ``required`` one
    does.  An ``error`` on a required gate is not a failure but an error: the
    difference between "this design does not meet the spec" and "we could not tell"
    is the difference between a result and a broken measurement.
    """
    results = [evaluate_gate(gate, data) for gate in gates]
    required = [r for r in results if r.severity == "required"]
    if any(r.status == "error" for r in required):
        status = "error"
    elif any(r.status == "fail" for r in required):
        status = "fail"
    elif not required:
        status = "error" if any(r.status == "error" for r in results) else "pass"
    else:
        status = "pass"
    return GateReport(status=status, gates=results)
