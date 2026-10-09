from __future__ import annotations

from math import isclose

from cst_metrics import evaluate_metric, normalize_1d_result


def result(data=None, *, truncated=False, xlabel="Frequency / GHz"):
    return {
        "tree_path": "1D Results\\S-Parameters\\S1,1",
        "title": "S1,1",
        "xlabel": xlabel,
        "ylabel": "S-Parameter",
        "truncated": truncated,
        "data": data
        or [
            [9.0, {"real": 1.0, "imag": 0.0}],
            [10.0, {"real": 0.1, "imag": 0.0}],
            [11.0, {"real": 0.5, "imag": 0.0}],
        ],
    }


def definition(**updates):
    value = {
        "name": "s11_min_db",
        "signal": "S1,1",
        "representation": "db20",
        "unit": "dB",
        "domain": "frequency",
        "frequency_window": {"start": 9.0, "stop": 11.0, "unit": "GHz"},
        "aggregation": "min",
        "direction": "minimize",
        "missing_data_policy": "invalid",
        "quality_gates": ["frequency-window-covered"],
    }
    value.update(updates)
    return value


def test_complex_normalization_and_db20_are_explicit() -> None:
    normalized = normalize_1d_result(result(), representation="db20")
    assert normalized["status"] == "valid"
    assert normalized["x_unit"] == "GHz"
    assert isclose(normalized["points"][1]["value"], -20.0)
    assert normalized["points"][1]["real"] == 0.1


def test_metric_evaluation_uses_20_log10_for_s_parameter() -> None:
    evaluated = evaluate_metric(result(), definition())
    assert evaluated["status"] == "valid"
    assert isclose(evaluated["value"], -20.0)
    assert evaluated["representation"] == "db20"


def test_metric_converts_frequency_units_and_requires_full_coverage() -> None:
    mhz_result = result(
        [
            [9000, [1, 0]],
            [10000, [0.1, 0]],
            [11000, [0.5, 0]],
        ],
        xlabel="Frequency [MHz]",
    )
    valid = evaluate_metric(mhz_result, definition())
    assert valid["status"] == "valid"
    assert isclose(valid["value"], -20.0)

    uncovered = definition()
    uncovered["frequency_window"] = {"start": 8.0, "stop": 12.0, "unit": "GHz"}
    invalid = evaluate_metric(mhz_result, uncovered)
    assert invalid["status"] == "invalid"
    assert "not fully covered" in invalid["error"]
    assert "value" not in invalid


def test_metric_coverage_allows_cst_float32_endpoint_noise() -> None:
    noisy = result(
        [
            [2.2049999237060547, [1, 0]],
            [2.45, [0.1, 0]],
            [2.694999933242798, [1, 0]],
        ]
    )
    requested = definition()
    requested["frequency_window"] = {"start": 2.205, "stop": 2.695, "unit": "GHz"}
    evaluated = evaluate_metric(noisy, requested)
    assert evaluated["status"] == "valid"
    assert isclose(evaluated["value"], -20.0)


def test_invalid_or_truncated_data_never_gets_numeric_objective() -> None:
    truncated = evaluate_metric(result(truncated=True), definition())
    assert truncated["status"] == "invalid"
    assert "value" not in truncated

    malformed = evaluate_metric(result([[10.0, "not-complex"]]), definition())
    assert malformed["status"] == "invalid"
    assert "value" not in malformed


def test_exact_zero_is_represented_without_json_infinity() -> None:
    zero = result(
        [
            [9.0, [1, 0]],
            [10.0, [0, 0]],
            [11.0, [1, 0]],
        ]
    )
    evaluated = evaluate_metric(zero, definition())
    assert evaluated["status"] == "valid"
    assert evaluated["value"] == "-Infinity"


def test_complex_representation_cannot_be_aggregated() -> None:
    evaluated = evaluate_metric(result(), definition(representation="complex"))
    assert evaluated["status"] == "invalid"
    assert "value" not in evaluated


def test_argmin_returns_resonance_coordinate_with_declared_unit() -> None:
    evaluated = evaluate_metric(
        result(), definition(name="resonance", aggregation="argmin_x", unit="GHz", direction="target")
    )
    assert evaluated["status"] == "valid"
    assert evaluated["value"] == 10.0
    assert evaluated["unit"] == "GHz"
