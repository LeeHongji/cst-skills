"""Touchstone reader for gate evaluation.

Dependency-free on purpose: the repository already contains around eight separate
Touchstone readers, each with its own idea of which column is which, and adding a
ninth that also needed numpy would make the consolidation in step 7 harder rather
than easier.  Pure ``math`` handles a thousand frequency points without noticing.

The parser is strict about the option line.  A ``.s2p`` written in ``MA`` or ``DB``
format read as ``RI`` produces plausible-looking numbers that are silently wrong,
which is exactly the class of error an automatic acceptance gate must not make.
"""

from __future__ import annotations

import cmath
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

#: Multipliers from the option line's frequency unit to Hz.
FREQUENCY_UNITS = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}

_PORTS_FROM_SUFFIX = re.compile(r"\.s(?P<ports>\d+)p$", re.IGNORECASE)


@dataclass(frozen=True)
class Touchstone:
    """Sampled S-parameters, frequency in Hz, matrix entries as complex numbers."""

    path: Path
    ports: int
    frequencies_hz: tuple[float, ...]
    #: ``s[(out, in)]`` is the sampled column, one complex value per frequency.
    s: dict[tuple[int, int], tuple[complex, ...]]
    comments: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.frequencies_hz)


def _to_complex(a: float, b: float, fmt: str) -> complex:
    if fmt == "ri":
        return complex(a, b)
    if fmt == "ma":
        return cmath.rect(a, math.radians(b))
    if fmt == "db":
        return cmath.rect(10.0 ** (a / 20.0), math.radians(b))
    raise ValueError(f"unsupported Touchstone data format: {fmt!r}")


def _column_order(ports: int) -> tuple[tuple[int, int], ...]:
    """Return the ``(out, in)`` key of each data column, in file order.

    Touchstone v1 is row-major -- S11 S12 ... S1N, S21 ... -- **except** for
    two-port files, which the format specifies as ``S11 S21 S12 S22``.  Reading a
    two-port file row-major transposes S21 and S12, which is invisible on a
    reciprocal filter and silently wrong on anything that is not; the same mistake
    on a four-port phase shifter would corrupt a phase-difference metric while
    every magnitude still looked right.
    """
    if ports == 2:
        return ((1, 1), (2, 1), (1, 2), (2, 2))
    return tuple(
        (out + 1, inp + 1) for out in range(ports) for inp in range(ports)
    )


def read_touchstone(path: str | Path) -> Touchstone:
    """Parse a Touchstone v1 file into complex S-parameters."""
    target = Path(path)
    text = target.read_text(encoding="utf-8", errors="replace")

    match = _PORTS_FROM_SUFFIX.search(target.name)
    if match is None:
        raise ValueError(f"{target.name}: not a Touchstone filename (expected .sNp)")
    ports = int(match.group("ports"))

    unit_scale = FREQUENCY_UNITS["ghz"]
    fmt = "ma"
    saw_option_line = False
    comments: list[str] = []
    numbers: list[float] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("!"):
            comments.append(line[1:].strip())
            continue
        if line.startswith("#"):
            tokens = line[1:].lower().split()
            if not tokens:
                raise ValueError(f"{target.name}: empty option line")
            unit = tokens[0]
            if unit not in FREQUENCY_UNITS:
                raise ValueError(f"{target.name}: unknown frequency unit {unit!r}")
            unit_scale = FREQUENCY_UNITS[unit]
            if "s" not in tokens:
                raise ValueError(f"{target.name}: option line does not declare S-parameters")
            for candidate in ("ri", "ma", "db"):
                if candidate in tokens:
                    fmt = candidate
                    break
            else:
                raise ValueError(f"{target.name}: option line declares no data format (RI/MA/DB)")
            saw_option_line = True
            continue
        body = line.split("!", 1)[0]
        numbers.extend(float(token) for token in body.split())

    if not saw_option_line:
        raise ValueError(
            f"{target.name}: no '#' option line, so the frequency unit and data format are "
            "unknown; guessing them would produce a plausible wrong curve"
        )

    stride = 1 + 2 * ports * ports
    if not numbers or len(numbers) % stride:
        raise ValueError(
            f"{target.name}: {len(numbers)} numbers is not a whole number of "
            f"{ports}-port rows (expected a multiple of {stride})"
        )

    frequencies: list[float] = []
    columns: dict[tuple[int, int], list[complex]] = {
        (out + 1, inp + 1): [] for out in range(ports) for inp in range(ports)
    }

    order = _column_order(ports)
    for offset in range(0, len(numbers), stride):
        row = numbers[offset : offset + stride]
        frequencies.append(row[0] * unit_scale)
        for index, key in enumerate(order):
            pair = row[1 + 2 * index], row[2 + 2 * index]
            columns[key].append(_to_complex(pair[0], pair[1], fmt))

    if len(frequencies) > 1 and any(
        b <= a for a, b in zip(frequencies, frequencies[1:])
    ):
        raise ValueError(f"{target.name}: frequencies are not strictly increasing")

    return Touchstone(
        path=target,
        ports=ports,
        frequencies_hz=tuple(frequencies),
        s={key: tuple(value) for key, value in columns.items()},
        comments=tuple(comments),
    )


def curve(data: Touchstone, out_port: int, in_port: int, unit: str) -> tuple[float, ...]:
    """Return one typed curve: magnitude in dB or unwrapped phase in degrees.

    Magnitude is ``20*log10(abs(S))`` without exception.  Phase is unwrapped
    because a gate on a phase difference across a band is meaningless if the curve
    jumps by 360 degrees in the middle of it.
    """
    try:
        samples = data.s[(out_port, in_port)]
    except KeyError:
        raise ValueError(
            f"{data.path.name} has {data.ports} ports and does not contain S{out_port}{in_port}"
        ) from None

    if unit == "db":
        floor = 1e-30  # a perfect null would otherwise be -inf
        return tuple(20.0 * math.log10(max(abs(value), floor)) for value in samples)
    if unit == "deg":
        return _unwrap_deg(math.degrees(cmath.phase(value)) for value in samples)
    raise ValueError(f"unsupported curve unit: {unit!r}")


def _unwrap_deg(angles: Iterable[float]) -> tuple[float, ...]:
    unwrapped: list[float] = []
    previous = 0.0
    offset = 0.0
    for index, angle in enumerate(angles):
        if index:
            step = angle + offset - previous
            if step > 180.0:
                offset -= 360.0
            elif step < -180.0:
                offset += 360.0
        previous = angle + offset
        unwrapped.append(previous)
    return tuple(unwrapped)


def _column(data: Touchstone, pair: tuple[int, int]) -> tuple[complex, ...]:
    try:
        return data.s[pair]
    except KeyError:
        raise ValueError(
            f"{data.path.name} has {data.ports} ports and does not contain S{pair[0]}{pair[1]}"
        ) from None


def phase_difference_deg(
    data: Touchstone,
    main: tuple[int, int],
    reference: tuple[int, int],
    anchor_ghz: float,
    anchor_target_deg: float,
) -> tuple[float, ...]:
    """Unwrapped ``angle(S_main) - angle(S_ref)`` in degrees, with the branch pinned.

    Computed from the pointwise product ``S_main * conj(S_ref)`` rather than by
    subtracting two separately unwrapped curves.  Each unwrapped curve carries its
    own arbitrary multiple of 360 degrees, inherited from wherever the sweep
    happened to start, and subtracting them keeps both errors.  The product cancels
    them and leaves a single global ambiguity.

    That last ambiguity is real and cannot be reasoned away: a 180 degree shifter
    and a -180 degree one produce the identical product curve.  So the caller must
    say which branch it means, by naming a frequency and the value expected there;
    the whole curve is then shifted by the multiple of 360 that gets closest.  An
    anchor outside the swept range raises rather than guessing.
    """
    frequencies_ghz = [f / 1e9 for f in data.frequencies_hz]
    if not frequencies_ghz:
        raise ValueError(f"{data.path.name} contains no frequency samples")
    if not frequencies_ghz[0] - 1e-12 <= anchor_ghz <= frequencies_ghz[-1] + 1e-12:
        raise ValueError(
            f"branch anchor {anchor_ghz:g} GHz lies outside the swept range "
            f"[{frequencies_ghz[0]:g}, {frequencies_ghz[-1]:g}] GHz, so the 360 degree "
            "branch of the phase difference cannot be pinned"
        )

    main_column = _column(data, main)
    reference_column = _column(data, reference)
    difference = _unwrap_deg(
        math.degrees(cmath.phase(a * b.conjugate()))
        for a, b in zip(main_column, reference_column)
    )

    nearest = min(range(len(frequencies_ghz)), key=lambda i: abs(frequencies_ghz[i] - anchor_ghz))
    turns = round((anchor_target_deg - difference[nearest]) / 360.0)
    if turns:
        return tuple(value + 360.0 * turns for value in difference)
    return difference


def amplitude_imbalance_db(
    data: Touchstone, main: tuple[int, int], reference: tuple[int, int]
) -> tuple[float, ...]:
    """``abs(|S_main|dB - |S_ref|dB)``: how unequally the two paths transmit.

    Absolute because the specification it serves is two-sided -- a paper reporting
    "magnitude imbalance below 0.2 dB" is not saying which branch may be louder.
    """
    floor = 1e-30
    main_column = _column(data, main)
    reference_column = _column(data, reference)
    return tuple(
        abs(
            20.0 * math.log10(max(abs(a), floor))
            - 20.0 * math.log10(max(abs(b), floor))
        )
        for a, b in zip(main_column, reference_column)
    )
