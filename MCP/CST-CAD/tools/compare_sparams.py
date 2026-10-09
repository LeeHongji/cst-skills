"""Compare a generated Touchstone response against reference filter evidence.

Magnitudes are always converted with 20*log10(abs(S)); no other quantity is
treated as a transmission or reflection level.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def read_touchstone(path: Path) -> tuple[list[float], list[float], list[float]]:
    scale = {"HZ": 1e-9, "KHZ": 1e-6, "MHZ": 1e-3, "GHZ": 1.0}
    unit, fmt = 1.0, "MA"
    freq: list[float] = []
    s11: list[float] = []
    s21: list[float] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            tokens = line[1:].upper().split()
            for index, token in enumerate(tokens):
                if token in scale:
                    unit = scale[token]
                if token in {"MA", "DB", "RI"}:
                    fmt = token
            continue
        values = [float(token) for token in line.replace(",", " ").split()]
        if len(values) < 9:
            continue
        frequency = values[0] * unit
        pairs = [(values[i], values[i + 1]) for i in range(1, 9, 2)]

        def magnitude_db(pair: tuple[float, float]) -> float:
            a, b = pair
            if fmt == "DB":
                return a
            if fmt == "RI":
                return 20.0 * math.log10(max(math.hypot(a, b), 1e-30))
            return 20.0 * math.log10(max(abs(a), 1e-30))

        freq.append(frequency)
        s11.append(magnitude_db(pairs[0]))
        # Touchstone 2-port row order is S11 S21 S12 S22.
        s21.append(magnitude_db(pairs[1]))
    order = sorted(range(len(freq)), key=freq.__getitem__)
    return [freq[i] for i in order], [s11[i] for i in order], [s21[i] for i in order]


def read_reference_csv(path: Path) -> tuple[list[float], list[float], list[float]]:
    freq: list[float] = []
    s11: list[float] = []
    s21: list[float] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            freq.append(float(row["frequency_ghz"]))
            s11.append(float(row["s11_db"]))
            s21.append(float(row["s21_db"]))
    order = sorted(range(len(freq)), key=freq.__getitem__)
    return [freq[i] for i in order], [s11[i] for i in order], [s21[i] for i in order]


def interpolate(freq: list[float], values: list[float], target: float) -> float | None:
    if target < freq[0] or target > freq[-1]:
        return None
    for i in range(len(freq) - 1):
        if freq[i] <= target <= freq[i + 1]:
            if freq[i + 1] == freq[i]:
                return values[i]
            t = (target - freq[i]) / (freq[i + 1] - freq[i])
            return values[i] + t * (values[i + 1] - values[i])
    return values[-1]


def crossing(freq: list[float], values: list[float], start: int, stop: int, threshold: float) -> float | None:
    step = 1 if stop >= start else -1
    i = start
    while i != stop:
        j = i + step
        y0, y1 = values[i], values[j]
        if (y0 - threshold) * (y1 - threshold) <= 0 and y0 != y1:
            return freq[i] + (threshold - y0) / (y1 - y0) * (freq[j] - freq[i])
        i = j
    return None


def metrics(freq: list[float], s11: list[float], s21: list[float]) -> dict:
    peak = max(range(len(s21)), key=s21.__getitem__)
    lower = crossing(freq, s21, peak, 0, s21[peak] - 3.0)
    upper = crossing(freq, s21, peak, len(freq) - 1, s21[peak] - 3.0)
    centre = math.sqrt(lower * upper) if lower and upper else None
    in_band = [i for i, f in enumerate(freq) if lower and upper and lower <= f <= upper]
    worst_s11 = max((s11[i] for i in in_band), default=None)
    best_s11 = min(range(len(s11)), key=s11.__getitem__)
    return {
        "representation": "20*log10(abs(S))",
        "sample_count": len(freq),
        "frequency_span_ghz": [freq[0], freq[-1]],
        "s21_peak_db": s21[peak],
        "s21_peak_frequency_ghz": freq[peak],
        "passband_3db_lower_ghz": lower,
        "passband_3db_upper_ghz": upper,
        "center_frequency_ghz": centre,
        "fractional_bandwidth": (upper - lower) / centre if centre else None,
        "s11_min_db": s11[best_s11],
        "s11_min_frequency_ghz": freq[best_s11],
        "s11_worst_in_band_db": worst_s11,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--touchstone", required=True)
    parser.add_argument("--reference-csv", required=True)
    parser.add_argument("--reference-label", default="reference")
    parser.add_argument("--csv-out")
    parser.add_argument("--output")
    args = parser.parse_args()

    # A .csv input is a native result-tree export; a .s2p is renormalised to the
    # requested reference impedance. Comparing the two kinds is not apples to apples.
    source = Path(args.touchstone)
    freq, s11, s21 = (read_reference_csv if source.suffix.lower() == ".csv" else read_touchstone)(source)
    rf, rs11, rs21 = read_reference_csv(Path(args.reference_csv))

    if args.csv_out:
        target = Path(args.csv_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["frequency_ghz", "s11_db", "s21_db"])
            for row in zip(freq, s11, s21):
                writer.writerow([f"{value:.9g}" for value in row])

    generated = metrics(freq, s11, s21)
    reference = metrics(rf, rs11, rs21)

    # Pointwise curve agreement on the overlapping band, sampled on the reference grid.
    overlap = [f for f in rf if freq[0] <= f <= freq[-1]]
    deltas_s11 = []
    deltas_s21 = []
    for f in overlap:
        a = interpolate(freq, s21, f)
        b = interpolate(rf, rs21, f)
        if a is not None and b is not None:
            deltas_s21.append(abs(a - b))
        a = interpolate(freq, s11, f)
        b = interpolate(rf, rs11, f)
        if a is not None and b is not None:
            deltas_s11.append(abs(a - b))

    comparison = {}
    for key in generated:
        left, right = generated[key], reference.get(key)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            comparison[key] = {"generated": left, args.reference_label: right, "delta": left - right}

    report = {
        "touchstone": str(Path(args.touchstone).resolve()),
        "reference_csv": str(Path(args.reference_csv).resolve()),
        "representation": "20*log10(abs(S))",
        "generated": generated,
        "reference": reference,
        "comparison": comparison,
        "pointwise": {
            "overlap_samples": len(overlap),
            "s21_max_abs_delta_db": max(deltas_s21) if deltas_s21 else None,
            "s21_mean_abs_delta_db": sum(deltas_s21) / len(deltas_s21) if deltas_s21 else None,
            "s11_max_abs_delta_db": max(deltas_s11) if deltas_s11 else None,
            "s11_mean_abs_delta_db": sum(deltas_s11) / len(deltas_s11) if deltas_s11 else None,
        },
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
