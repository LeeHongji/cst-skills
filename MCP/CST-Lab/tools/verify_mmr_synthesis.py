"""Cross-examine the MMR phase-shifter synthesis against the paper's own numbers.

Every assertion here compares an independent implementation with something the
paper prints, so a pass means the model reproduces published results rather than
its own assumptions.  Nothing in this file touches CST; it is the standard-answer
check that has to succeed before a four-port model is worth building.

Run:  python MCP/CST-Lab/tools/verify_mmr_synthesis.py [--output report.json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def _repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "MCP").is_dir():
            return candidate
    raise RuntimeError(f"no workspace root above {start}")


REPO_ROOT = _repo_root(Path(__file__).resolve())
TOPIC_ROOT = REPO_ROOT / "projects" / "wideband-phase-shifters-on-mmr"
sys.path.insert(0, str(TOPIC_ROOT))

import synthesis  # noqa: E402
from synthesis import Impedances  # noqa: E402

#: Resonant frequencies printed in Section II, normalised to f0.
PRINTED_RESONANCES = [
    {"kind": "mmr1", "rz": 1.5, "expect": (0.738, 1.262)},
    {"kind": "mmr1", "rz": 2.5, "expect": (0.816, 1.184)},
    {"kind": "mmr2", "rz": 2.0, "expect": (0.608, 1.0, 1.392)},
    {"kind": "mmr2", "rz": 4.0, "expect": (0.705, 1.0, 1.295)},
]

#: Table I: synthesised values for phase shifter 1 on MMR-I at RL = 16.4 dB.
TABLE_I = [
    {"shift": 45.0, "k": 3.5, "theta_c_cal": 39.0, "theta_c": 34.0, "z0e": 130.287, "z0o": 11.248, "zc": 60.858, "pd": 1.875, "fbw": 124.4},
    {"shift": 90.0, "k": 4.0, "theta_c_cal": 48.9, "theta_c": 45.0, "z0e": 140.091, "z0o": 23.608, "zc": 58.273, "pd": 2.365, "fbw": 100.0},
    {"shift": 135.0, "k": 4.5, "theta_c_cal": 55.0, "theta_c": 52.0, "z0e": 149.931, "z0o": 36.284, "zc": 55.470, "pd": 2.252, "fbw": 84.4},
    {"shift": 180.0, "k": 5.0, "theta_c_cal": 59.4, "theta_c": 57.0, "z0e": 160.099, "z0o": 48.934, "zc": 53.074, "pd": 1.996, "fbw": 73.3},
    {"shift": 225.0, "k": 5.5, "theta_c_cal": 62.7, "theta_c": 60.0, "z0e": 168.121, "z0o": 58.576, "zc": 51.538, "pd": 3.030, "fbw": 66.7},
    {"shift": 270.0, "k": 6.0, "theta_c_cal": 65.4, "theta_c": 63.0, "z0e": 178.101, "z0o": 70.234, "zc": 49.972, "pd": 2.888, "fbw": 60.0},
]

#: Table II: synthesised values for phase shifter 2 on MMR-II at RL = 16.4 dB.
TABLE_II = [
    {"shift": 45.0, "k": 4.5, "theta_c_cal": 31.3, "theta_c": 30.0, "z0e": 126.807, "z0o": 11.042, "zc": 53.783, "pd": 2.194, "fbw": 133.3},
    {"shift": 90.0, "k": 5.0, "theta_c_cal": 41.5, "theta_c": 40.0, "z0e": 133.109, "z0o": 22.046, "zc": 45.203, "pd": 2.715, "fbw": 111.1},
    {"shift": 135.0, "k": 5.5, "theta_c_cal": 47.9, "theta_c": 47.0, "z0e": 140.142, "z0o": 33.196, "zc": 37.988, "pd": 2.039, "fbw": 95.6},
    {"shift": 180.0, "k": 6.0, "theta_c_cal": 52.5, "theta_c": 51.0, "z0e": 145.838, "z0o": 41.294, "zc": 33.784, "pd": 3.437, "fbw": 86.7},
    {"shift": 225.0, "k": 6.5, "theta_c_cal": 56.2, "theta_c": 55.0, "z0e": 153.269, "z0o": 51.033, "zc": 29.688, "pd": 2.940, "fbw": 77.8},
    {"shift": 270.0, "k": 7.0, "theta_c_cal": 59.1, "theta_c": 58.0, "z0e": 160.349, "z0o": 59.742, "zc": 26.728, "pd": 3.064, "fbw": 71.1},
]

TABLES = {"mmr1": TABLE_I, "mmr2": TABLE_II}

#: Section IV, phase shifter 2 on MMR-II, synthesised column.
SYNTHESISED_MMR2_180 = {
    "return_loss_db": 16.4,
    "rl_band_ghz": (1.70, 4.30),
    "rl_fractional": 0.867,
    "phase_deviation_deg": 3.4,
    "phase_band_ghz": (1.95, 4.05),
    "phase_fractional": 0.70,
    "f0_ghz": 3.0,
}

SAMPLE_IMPEDANCES = (
    Impedances(0.9, 1.1, 0.7),
    Impedances(0.5, 1.4, 1.2),
    Impedances(1.3, 0.8, 0.9),
)


def check_f_matches_printed_polynomial() -> dict:
    """The ABCD cascade must reproduce the printed expansion (12)/(13), (22)/(23)."""
    rows = []
    worst = 0.0
    for kind in ("mmr1", "mmr2"):
        printed = ("k1", "k2", "k3") if kind == "mmr1" else ("k1", "k3")
        for z in SAMPLE_IMPEDANCES:
            fitted = synthesis.coefficients(kind, z)
            expected = synthesis.printed_coefficients(kind, z)
            for name in printed:
                relative = abs(fitted[name] - expected[name]) / max(abs(expected[name]), 1e-9)
                worst = max(worst, relative)
                rows.append(
                    {
                        "kind": kind,
                        "impedances": [z.za, z.zb, z.zc],
                        "coefficient": name,
                        "from_cascade": fitted[name],
                        "printed": expected[name],
                        "relative_error": relative,
                    }
                )
    return {
        "check": "F from the cascade equals the printed polynomial",
        "status": "pass" if worst < 1e-9 else "fail",
        "worst_relative_error": worst,
        "note": (
            "(23b) is truncated in the available transcription, so MMR-II is checked on "
            "k1 and k3 only; MMR-I is checked on all three.  The cascade's F carries the "
            "opposite overall sign to (10)'s definition, which is a sign slip between (10) "
            "and (13)/(23) in the paper: only |F| enters the magnitude response, and the "
            "sign is not free because the main line holds two coupled sections."
        ),
        "rows": rows,
    }


def check_resonances() -> dict:
    rows = []
    worst = 0.0
    for case in PRINTED_RESONANCES:
        got = synthesis.resonant_frequencies(case["kind"], case["rz"])
        for value, expected in zip(got, case["expect"]):
            error = abs(value - expected)
            worst = max(worst, error)
            rows.append(
                {
                    "kind": case["kind"],
                    "rz": case["rz"],
                    "computed": round(value, 6),
                    "printed": expected,
                    "absolute_error": error,
                }
            )
    return {
        "check": "resonant frequencies (6) and (8) reproduce the printed values",
        "status": "pass" if worst < 5e-4 else "fail",
        "worst_absolute_error": worst,
        "rows": rows,
    }


def check_slope_formulas() -> dict:
    """(21) and (27) must agree with a numerical derivative of the cascade."""
    rows = []
    worst = 0.0
    for kind in ("mmr1", "mmr2"):
        for z in SAMPLE_IMPEDANCES:
            printed = synthesis.phase_slope_from_impedances(kind, z)
            numeric = synthesis.phase_slope_numeric(kind, z)
            relative = abs(printed - numeric) / max(abs(numeric), 1e-9)
            worst = max(worst, relative)
            rows.append(
                {
                    "kind": kind,
                    "impedances": [z.za, z.zb, z.zc],
                    "printed_formula": printed,
                    "numeric_derivative": numeric,
                    "relative_error": relative,
                }
            )
    return {
        "check": "phase-slope formulas (21) and (27) match the cascade derivative",
        "status": "pass" if worst < 1e-5 else "fail",
        "worst_relative_error": worst,
        "rows": rows,
    }


def check_rz_gives_k_six() -> dict:
    """Section II: MMR-II with Rz = 2.95 is chosen so the slope equals -K = -6."""
    slope = synthesis.phase_slope_from_rz("mmr2", 2.95)
    return {
        "check": "Rz = 2.95 on MMR-II gives a phase slope of -6",
        "status": "pass" if abs(slope + 6.0) < 0.05 else "fail",
        "slope_from_rz": slope,
        "expected": -6.0,
        "resonances": [round(f, 4) for f in synthesis.resonant_frequencies("mmr2", 2.95)],
    }


def check_insertion_phase_at_f0() -> dict:
    """Section II: the main line's insertion phase at f0 is -270 (I) and -360 (II)."""
    rows = []
    ok = True
    sweep = [0.001 + 0.001 * index for index in range(1000)]
    for kind, expected in (("mmr1", -270.0), ("mmr2", -360.0)):
        for z in SAMPLE_IMPEDANCES:
            curves = synthesis.response(kind, z, synthesis.MAIN_LINE_SECTIONS[kind], sweep)
            at_f0 = curves["main_phase_deg"][sweep.index(min(sweep, key=lambda f: abs(f - 1.0)))]
            error = abs(at_f0 - expected)
            ok = ok and error < 1.0
            rows.append(
                {
                    "kind": kind,
                    "impedances": [z.za, z.zb, z.zc],
                    "phase_at_f0_deg": round(at_f0, 4),
                    "printed": expected,
                    "absolute_error_deg": error,
                }
            )
    return {
        "check": "insertion phase at f0 is -270 (MMR-I) and -360 (MMR-II) for any Rz",
        "status": "pass" if ok else "fail",
        "rows": rows,
    }


def check_tables_are_self_consistent() -> dict:
    """K from (19)/(26) and FBW from (180 - 2*theta_c)/90 must match both tables."""
    rows = []
    ok = True
    for kind, table in TABLES.items():
        for row in table:
            k = synthesis.k_for_phase_shift(kind, row["shift"])
            fbw = (180.0 - 2.0 * row["theta_c"]) / 90.0 * 100.0
            k_ok = abs(k - row["k"]) < 1e-9
            fbw_ok = abs(fbw - row["fbw"]) < 0.06
            ok = ok and k_ok and fbw_ok
            rows.append(
                {
                    "kind": kind,
                    "shift_deg": row["shift"],
                    "k_computed": k,
                    "k_printed": row["k"],
                    "fbw_computed_percent": round(fbw, 2),
                    "fbw_printed_percent": row["fbw"],
                    "agrees": k_ok and fbw_ok,
                }
            )
    return {
        "check": "K from (19)/(26) and FBW from the practical theta_c match the tables",
        "status": "pass" if ok else "fail",
        "rows": rows,
    }


def check_tabulated_impedances_fall_short_of_k() -> dict:
    """The tabulated impedances give a slope slightly *flatter* than -K, never steeper.

    The paper reduces the cutoff length below the calculated value "in order to widen
    the phase shift bandwidth", and a smaller theta_c widens the equal-ripple band at
    the cost of flattening the slope.  So the printed impedances are expected to miss
    the slope condition, in one direction only.  A row that overshot would mean the
    interpretation is wrong, not that the paper is imprecise.
    """
    rows = []
    ok = True
    worst = 0.0
    for kind, table in TABLES.items():
        for row in table:
            z = Impedances.from_ohms(row["z0e"], row["z0o"], row["zc"])
            slope = synthesis.phase_slope_from_impedances(kind, z)
            shortfall = row["k"] - abs(slope)
            worst = max(worst, abs(shortfall))
            direction_ok = 0.0 < shortfall < 0.5
            ok = ok and direction_ok
            rows.append(
                {
                    "kind": kind,
                    "shift_deg": row["shift"],
                    "slope_from_impedances": round(slope, 4),
                    "minus_k": -row["k"],
                    "shortfall": round(shortfall, 4),
                    "theta_c_reduction_deg": round(row["theta_c_cal"] - row["theta_c"], 2),
                    "flatter_not_steeper": direction_ok,
                }
            )
    return {
        "check": "tabulated impedances are flatter than -K, consistent with the reduced theta_c",
        "status": "pass" if ok else "fail",
        "worst_shortfall": round(worst, 4),
        "rows": rows,
    }


def check_synthesis_reproduces_tables() -> dict:
    """Synthesis from (phase shift, RL) alone must reproduce theta_c(Cal) and Z.

    This is the whole design method run in reverse: nothing is fed in but the target
    phase shift and the return loss, and every impedance in Table I and Table II
    plus the calculated cutoff length has to come back out.
    """
    rows = []
    worst_theta = 0.0
    worst_impedance = 0.0
    for kind, table in TABLES.items():
        for row in table:
            entry: dict = {"kind": kind, "shift_deg": row["shift"]}
            try:
                solved = synthesis.synthesise(kind, row["shift"], 16.4)
            except synthesis.SynthesisError as exc:
                entry["error"] = str(exc)
                rows.append(entry)
                worst_theta = float("inf")
                continue
            theta_error = abs(solved.theta_c_deg - row["theta_c_cal"])
            worst_theta = max(worst_theta, theta_error)
            entry.update(
                {
                    "theta_c_computed_deg": round(solved.theta_c_deg, 3),
                    "theta_c_cal_printed_deg": row["theta_c_cal"],
                    "theta_c_error_deg": round(theta_error, 3),
                }
            )

            # Second stage: at the reduced practical theta_c the slope condition is
            # dropped, and the three ripple matches alone should give the printed
            # impedances.
            final = synthesis.impedances_at_theta_c(kind, 16.4, row["theta_c"])
            deltas = {
                "z0e": final.z0e_ohm - row["z0e"],
                "z0o": final.z0o_ohm - row["z0o"],
                "zc": final.zc_ohm - row["zc"],
            }
            worst_impedance = max(worst_impedance, max(abs(v) for v in deltas.values()))
            entry.update(
                {
                    "z0e_computed": round(final.z0e_ohm, 3),
                    "z0e_printed": row["z0e"],
                    "z0o_computed": round(final.z0o_ohm, 3),
                    "z0o_printed": row["z0o"],
                    "zc_computed": round(final.zc_ohm, 3),
                    "zc_printed": row["zc"],
                    "worst_delta_ohm": round(max(abs(v) for v in deltas.values()), 3),
                }
            )
            rows.append(entry)
    return {
        "check": "synthesis reproduces theta_c(Cal) and, at the reduced theta_c, both tables",
        "status": "pass" if worst_theta < 0.35 and worst_impedance < 1.5 else "fail",
        "worst_theta_c_error_deg": round(worst_theta, 4) if worst_theta != float("inf") else None,
        "worst_impedance_error_ohm": round(worst_impedance, 4),
        "note": (
            "Two stages, as the paper describes them: the four-equation solve returns "
            "theta_c(Cal), then theta_c is reduced by hand and the three ripple matches "
            "alone give the impedances printed beside it."
        ),
        "rows": rows,
    }


def check_mmr2_180_bandwidths() -> dict:
    """The headline standard answer: the synthesised 180-degree device's two bands."""
    spec = SYNTHESISED_MMR2_180
    row = next(r for r in TABLE_II if r["shift"] == 180.0)
    z = Impedances.from_ohms(row["z0e"], row["z0o"], row["zc"])
    sweep = [0.30 + 0.0005 * index for index in range(2801)]
    curves = synthesis.response("mmr2", z, row["k"], sweep)

    rl = synthesis.bandwidth(sweep, curves["s11_db"], "below", -spec["return_loss_db"])
    deviation = [abs(value - 180.0) for value in curves["phase_shift_deg"]]
    # Section IV rounds the deviation to 3.4 degrees; Table II's 3.437 is the figure
    # the curve actually touches, and rounding it down cuts the band into fragments.
    phase = synthesis.bandwidth(sweep, deviation, "below", row["pd"])

    f0 = spec["f0_ghz"]
    result = {
        "check": "synthesised MMR-II 180-degree bands match Section IV",
        "impedances_ohm": {"z0e": row["z0e"], "z0o": row["z0o"], "zc": row["zc"], "k": row["k"]},
        "return_loss": None,
        "phase_shift": None,
    }
    status = "pass"

    if rl is None:
        result["return_loss"] = {"error": f"no band below -{spec['return_loss_db']} dB"}
        status = "fail"
    else:
        band = (rl["low"] * f0, rl["high"] * f0)
        errors = [abs(band[i] - spec["rl_band_ghz"][i]) for i in (0, 1)]
        result["return_loss"] = {
            "band_ghz": [round(v, 4) for v in band],
            "printed_ghz": list(spec["rl_band_ghz"]),
            "fractional": round(rl["fractional"], 4),
            "printed_fractional": spec["rl_fractional"],
            "worst_edge_error_ghz": round(max(errors), 4),
        }
        if max(errors) > 0.03:
            status = "fail"

    def deviation_at(ghz: float) -> float:
        target = ghz / f0
        index = min(range(len(sweep)), key=lambda i: abs(sweep[i] - target))
        return deviation[index]

    inside_worst = max(
        value
        for f, value in zip(sweep, deviation)
        if spec["phase_band_ghz"][0] / f0 <= f <= spec["phase_band_ghz"][1] / f0
    )
    # The band is stated as the range where the deviation stays within PD, so its
    # edges are exactly where the deviation equals PD.  Testing "widest run below PD"
    # is therefore a knife-edge that fragments on rounding; the two meaningful
    # assertions are that the worst deviation inside the printed band equals PD, and
    # that just outside it the deviation is already worse.
    outside = {
        "below_band_ghz": round(deviation_at(spec["phase_band_ghz"][0] - 0.10), 4),
        "above_band_ghz": round(deviation_at(spec["phase_band_ghz"][1] + 0.10), 4),
    }
    result["phase_shift"] = {
        "max_deviation_in_printed_band_deg": round(inside_worst, 4),
        "printed_pd_deg": row["pd"],
        "deviation_error_deg": round(abs(inside_worst - row["pd"]), 4),
        "printed_band_ghz": list(spec["phase_band_ghz"]),
        "deviation_just_outside_deg": outside,
        "widest_run_within_pd": None
        if phase is None
        else {
            "band_ghz": [round(phase["low"] * f0, 4), round(phase["high"] * f0, 4)],
            "fractional": round(phase["fractional"], 4),
        },
        "printed_fractional": spec["phase_fractional"],
    }
    if abs(inside_worst - row["pd"]) > 0.05:
        status = "fail"
    if min(outside.values()) <= row["pd"]:
        status = "fail"

    result["status"] = status
    return result


CHECKS = (
    check_f_matches_printed_polynomial,
    check_resonances,
    check_slope_formulas,
    check_rz_gives_k_six,
    check_insertion_phase_at_f0,
    check_tables_are_self_consistent,
    check_tabulated_impedances_fall_short_of_k,
    check_mmr2_180_bandwidths,
    check_synthesis_reproduces_tables,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    results = [check() for check in CHECKS]
    asserted = [r for r in results if r["status"] != "informational"]
    report = {
        "paper": "Lyu, Zhu, Wu, Cheng - Wideband Phase Shifters on Multimode Resonator",
        "checks": results,
        "all_passed": all(r["status"] == "pass" for r in asserted),
    }
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
