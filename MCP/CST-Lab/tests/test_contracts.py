"""Tests for the four data contracts and the automatic acceptance verdict.

The gate tests are deliberately built on synthesised Touchstone files with known
answers, so a wrong verdict is unambiguous.  The one test that uses a real
exported curve is the cross-check against the historical analysis script's
numbers, which is the only evidence that the evaluator agrees with an independent
implementation on real data.
"""

from __future__ import annotations

import cmath
import json
import math
from pathlib import Path

import pytest

from cst_lab.contracts import (
    ApprovalError,
    FrontmatterError,
    RangeViolation,
    TopologyMismatch,
    append_iteration,
    check_parameters,
    check_topology,
    amplitude_imbalance_db,
    curve,
    default_ranges,
    evaluate_gate,
    evaluate_gates,
    iteration_line,
    load_attempt,
    load_design,
    load_topic,
    next_iteration_number,
    parse_gates,
    phase_difference_deg,
    read_iterations,
    read_touchstone,
    require_approval,
    split_frontmatter,
    write_attempt,
)
from cst_lab.contracts.design import write_design
from cst_lab.validation import SchemaValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]
TOPIC_DIR = Path(__file__).resolve().parent / "fixtures" / "public-contract-fixture"
FIXTURE_DESIGN = TOPIC_DIR / "designs" / "filter-fixture"
FIXTURE_ATTEMPT = FIXTURE_DESIGN / "attempts" / "a01-test"


# ------------------------------------------------------------------ frontmatter


def test_frontmatter_splits_header_from_body() -> None:
    header, body = split_frontmatter("---\na: 1\nb: two\n---\n\n# Title\n\ntext\n")
    assert header == {"a": 1, "b": "two"}
    assert body.startswith("# Title")


def test_missing_frontmatter_is_an_error() -> None:
    with pytest.raises(FrontmatterError, match="must begin with"):
        split_frontmatter("# Title\n\ntext\n")


def test_unterminated_frontmatter_is_an_error() -> None:
    with pytest.raises(FrontmatterError, match="never closed"):
        split_frontmatter("---\na: 1\n\n# Title\n")


def test_empty_frontmatter_is_an_error() -> None:
    """An empty header would mean a design with no gates, which must not be silent."""
    with pytest.raises(FrontmatterError, match="empty"):
        split_frontmatter("---\n---\n\nbody\n")


def test_non_mapping_frontmatter_is_an_error() -> None:
    with pytest.raises(FrontmatterError, match="must be a mapping"):
        split_frontmatter("---\n- one\n- two\n---\n\nbody\n")


def test_broken_yaml_is_reported_as_frontmatter_not_swallowed() -> None:
    with pytest.raises(FrontmatterError, match="not valid YAML"):
        split_frontmatter("---\na: [1, 2\n---\n\nbody\n")


def test_yaml_dates_arrive_as_iso_strings() -> None:
    """``created: 2026-09-10`` is the natural spelling and must not be rejected.

    YAML resolves an unquoted date to ``datetime.date``, and the schemas ask for a
    string with ``format: date``, so before this every topic and design written the
    obvious way failed validation on a field the schema itself defines.  Nested
    values are converted too, because a date inside a list of sources would fail the
    same way and be harder to diagnose.
    """
    header, _ = split_frontmatter(
        "---\ncreated: 2026-09-10\nstamped: 2026-09-10T08:30:00\n"
        "sources:\n  - seen: 2026-01-02\n---\n\nbody\n"
    )
    assert header["created"] == "2026-09-10"
    assert header["stamped"].startswith("2026-09-10T08:30")
    assert header["sources"][0]["seen"] == "2026-01-02"


def test_quoted_dates_are_left_alone() -> None:
    header, _ = split_frontmatter("---\ncreated: '2026-09-10'\n---\n\nbody\n")
    assert header["created"] == "2026-09-10"


# ------------------------------------------------------------ topic and design


def test_the_public_fixture_topic_file_validates() -> None:
    header, body = load_topic(TOPIC_DIR / "topic.md")
    assert header["topic_id"] == "public-contract-fixture"
    assert header["shared_physics"], "a topic without shared physics has no boundary"
    assert "Synthetic" in body


def test_the_public_fixture_design_file_validates_and_parses_its_gates() -> None:
    header, gates, body = load_design(FIXTURE_DESIGN / "design.md")
    assert header["design_id"] == "filter-fixture"
    assert {gate.id for gate in gates} == {
        "interior_return_loss",
        "interior_insertion_loss",
        "lower_transmission_zero",
        "upper_transmission_zero",
    }
    assert body


def test_every_fixture_gate_records_where_its_threshold_came_from() -> None:
    """Synthetic test gates must state their source instead of masquerading as
    paper or measured engineering requirements."""
    header, _, _ = load_design(FIXTURE_DESIGN / "design.md")
    for entry in header["acceptance"]:
        assert entry.get("note"), f"gate {entry['id']} does not say where its threshold came from"


def test_design_id_must_match_its_directory(tmp_path: Path) -> None:
    header, _, body = load_design(FIXTURE_DESIGN / "design.md")
    header["design_id"] = "somewhere-else"
    target = tmp_path / "filter-fixture" / "design.md"
    write_design(target, header, body)
    with pytest.raises(ValueError, match="does not match its directory"):
        load_design(target)


def test_a_gate_on_a_port_the_design_lacks_is_refused(tmp_path: Path) -> None:
    header, _, body = load_design(FIXTURE_DESIGN / "design.md")
    header["ports"] = 2
    header["acceptance"] = [
        {
            "id": "phase_balance",
            "metric": "s4_3_db",
            "band_ghz": [1.0, 1.1],
            "comparator": "<",
            "threshold": -3.0,
            "mode": "pointwise",
        }
    ]
    target = tmp_path / "filter-fixture" / "design.md"
    write_design(target, header, body)
    with pytest.raises(ValueError, match=r"reference port\(s\) \[3, 4\]"):
        load_design(target)


def test_an_inverted_band_is_refused() -> None:
    with pytest.raises(ValueError, match="inverted"):
        parse_gates(
            {
                "acceptance": [
                    {
                        "id": "backwards",
                        "metric": "s1_1_db",
                        "band_ghz": [1.2, 1.0],
                        "comparator": "<",
                        "threshold": -10.0,
                        "mode": "pointwise",
                    }
                ]
            }
        )


def test_duplicate_gate_ids_are_refused() -> None:
    entry = {
        "id": "same",
        "metric": "s1_1_db",
        "band_ghz": [1.0, 1.1],
        "comparator": "<",
        "threshold": -10.0,
        "mode": "pointwise",
    }
    with pytest.raises(ValueError, match="duplicate gate id"):
        parse_gates({"acceptance": [entry, dict(entry)]})


def test_an_aggregate_gate_without_an_aggregation_is_refused(tmp_path: Path) -> None:
    header, _, body = load_design(FIXTURE_DESIGN / "design.md")
    header["acceptance"] = [
        {
            "id": "no_aggregation",
            "metric": "s1_1_db",
            "band_ghz": [1.0, 1.1],
            "comparator": "<",
            "threshold": -10.0,
            "mode": "aggregate",
        }
    ]
    with pytest.raises(SchemaValidationError):
        write_design(tmp_path / "filter-fixture" / "design.md", header, body)


# ------------------------------------------------------------------- attempt


def test_the_public_fixture_attempt_validates_and_is_bound_to_the_real_topology() -> None:
    import sys

    sys.path.insert(0, str(REPO_ROOT / "MCP" / "CST-CAD" / "src"))
    from cst_cad import ir

    attempt = load_attempt(FIXTURE_ATTEMPT / "attempt.json")
    document = json.loads((FIXTURE_ATTEMPT / "geometry-ir.json").read_text(encoding="utf-8"))
    assert attempt["topology_hash"] == ir.topology_hash(document)
    assert attempt["model_intent_id"] == ir.model_intent_id(document)


def test_the_public_fixture_attempt_is_not_yet_approved_and_therefore_cannot_run() -> None:
    """Fail-closed is the whole point: the audit that would approve it is step 3."""
    attempt = load_attempt(FIXTURE_ATTEMPT / "attempt.json")
    with pytest.raises(ApprovalError, match="no approval record"):
        require_approval(attempt)


def test_the_public_fixture_attempt_approves_only_the_tunable_parameters() -> None:
    attempt = load_attempt(FIXTURE_ATTEMPT / "attempt.json")
    assert set(attempt["approved_ranges"]) == {"l3"}
    assert len(attempt["baseline_parameters"]) > len(attempt["approved_ranges"])


def test_the_public_fixture_attempt_lists_every_reviewable_assumption() -> None:
    attempt = load_attempt(FIXTURE_ATTEMPT / "attempt.json")
    kinds = {a["provenance"] for a in attempt["assumptions"]}
    assert kinds == {"assumption", "strong_inference"}
    assert len(attempt["assumptions"]) == 12


def test_default_ranges_are_the_audited_value_plus_or_minus_a_fifth() -> None:
    ranges = default_ranges({"gap": 0.200, "width": 1.5}, only=["gap"])
    assert ranges["gap"] == pytest.approx([0.16, 0.24])
    assert "width" not in ranges, "only= must fail closed, not approve everything"


def test_default_ranges_refuse_a_zero_baseline() -> None:
    with pytest.raises(ValueError, match="freeze it"):
        default_ranges({"tanD": 0.0})


def test_default_ranges_handle_a_negative_baseline() -> None:
    low, high = default_ranges({"offset": -5.0})["offset"]
    assert (low, high) == (-6.0, -4.0)


def test_default_ranges_accept_explicit_overrides() -> None:
    ranges = default_ranges({"gap": 0.2}, only=["gap"], overrides={"gap": (0.1, 0.5)})
    assert ranges == {"gap": [0.1, 0.5]}


def test_range_overrides_are_normalised_when_given_backwards() -> None:
    ranges = default_ranges({"gap": 0.2}, only=["gap"], overrides={"gap": (0.5, 0.1)})
    assert ranges == {"gap": [0.1, 0.5]}


def _approved(tmp_path: Path, **changes) -> dict:
    attempt = {
        "schema_version": 1,
        "attempt_id": "a01-test",
        "design_id": "d",
        "topic_id": "t",
        "topology_hash": "a" * 64,
        "baseline_parameters": {"gap": 0.2},
        "approved_ranges": {"gap": [0.16, 0.24]},
        "max_iterations": 5,
        "approval": {
            "approved_by": "reviewer",
            "approved_at": "2026-09-10T12:00:00+00:00",
            "topology_hash": "a" * 64,
            "audit_html": "audit.html",
        },
    }
    attempt.update(changes)
    return attempt


def test_an_approved_attempt_may_run(tmp_path: Path) -> None:
    require_approval(_approved(tmp_path))


def test_an_approval_for_a_different_topology_is_refused(tmp_path: Path) -> None:
    """Editing topology_hash after approval must be detectable, not silent."""
    attempt = _approved(tmp_path)
    attempt["topology_hash"] = "b" * 64
    with pytest.raises(ApprovalError, match="edited after approval"):
        require_approval(attempt)


def test_a_rebuilt_topology_that_differs_stops_the_loop(tmp_path: Path) -> None:
    with pytest.raises(TopologyMismatch, match="Open a new attempt"):
        check_topology(_approved(tmp_path), "c" * 64)


def test_a_matching_topology_passes(tmp_path: Path) -> None:
    check_topology(_approved(tmp_path), "a" * 64)


def test_a_value_inside_its_approved_range_passes(tmp_path: Path) -> None:
    check_parameters(_approved(tmp_path), {"gap": 0.195})


def test_a_value_outside_its_approved_range_requires_a_re_audit(tmp_path: Path) -> None:
    with pytest.raises(RangeViolation, match=r"Regenerate audit\.html"):
        check_parameters(_approved(tmp_path), {"gap": 0.30})


def test_range_bounds_are_inclusive(tmp_path: Path) -> None:
    check_parameters(_approved(tmp_path), {"gap": 0.16})
    check_parameters(_approved(tmp_path), {"gap": 0.24})


def test_a_parameter_nobody_approved_is_refused(tmp_path: Path) -> None:
    """Forgetting to approve a parameter must be a refusal, not a licence."""
    with pytest.raises(RangeViolation, match="no approved range"):
        check_parameters(_approved(tmp_path), {"w_loop": 1.5})


def test_writing_an_attempt_validates_it(tmp_path: Path) -> None:
    attempt = _approved(tmp_path)
    attempt["max_iterations"] = 0  # schema requires at least 1
    with pytest.raises(SchemaValidationError):
        write_attempt(tmp_path / "attempt.json", attempt)


# ---------------------------------------------------------------- iterations


def test_an_iteration_always_carries_both_deltas() -> None:
    line = iteration_line(iter_number=0)
    assert line["param_delta"] == {}
    assert line["setup_delta"] == {}


def test_appending_iterations_is_append_only(tmp_path: Path) -> None:
    path = tmp_path / "iterations.jsonl"
    append_iteration(path, iteration_line(iter_number=0, drc="pass"))
    append_iteration(path, iteration_line(iter_number=1, drc="pass", parent=0))
    with pytest.raises(ValueError, match="append-only"):
        append_iteration(path, iteration_line(iter_number=1, drc="pass"))
    assert [r["iter"] for r in read_iterations(path)] == [0, 1]


def test_next_iteration_number_starts_at_zero_and_follows_the_highest(tmp_path: Path) -> None:
    path = tmp_path / "iterations.jsonl"
    assert next_iteration_number(path) == 0
    append_iteration(path, iteration_line(iter_number=0, drc="pass"))
    append_iteration(path, iteration_line(iter_number=4, drc="pass"))
    assert next_iteration_number(path) == 5


def test_an_invalid_iteration_is_rejected_before_it_is_written(tmp_path: Path) -> None:
    path = tmp_path / "iterations.jsonl"
    with pytest.raises(SchemaValidationError):
        append_iteration(path, iteration_line(iter_number=0, drc="maybe"))
    assert not path.exists(), "a rejected line must not be appended"


def test_a_corrupt_line_is_reported_rather_than_skipped(tmp_path: Path) -> None:
    path = tmp_path / "iterations.jsonl"
    append_iteration(path, iteration_line(iter_number=0, drc="pass"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json}\n")
    with pytest.raises(ValueError, match="corrupt iteration line"):
        read_iterations(path)


@pytest.mark.parametrize("bad,match", [
    ({"not_an_iteration": True}, "schema_version"),
    (iteration_line(iter_number=0), "already recorded"),
    (iteration_line(iter_number=1, parent=1), "earlier recorded"),
    (iteration_line(iter_number=1, parent=99), "earlier recorded"),
    (iteration_line(iter_number=1, provenance="legacy", audited=True), "audited: false"),
])
def test_reading_edited_history_rejects_invalid_rows(tmp_path, bad, match):
    path = tmp_path / "iterations.jsonl"
    first = iteration_line(iter_number=0)
    path.write_text(json.dumps(first) + "\n" + json.dumps(bad) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        read_iterations(path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        append_iteration(path, iteration_line(iter_number=2))
    assert path.read_bytes() == before


def test_iteration_numbers_increase_without_requiring_contiguous_ids(tmp_path):
    path = tmp_path / "iterations.jsonl"
    append_iteration(path, iteration_line(iter_number=2, provenance="legacy", audited=False))
    append_iteration(path, iteration_line(iter_number=5, parent=2))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="strictly increasing"):
        append_iteration(path, iteration_line(iter_number=3))
    assert path.read_bytes() == before
    assert [r["iter"] for r in read_iterations(path)] == [2, 5]


def test_a_failed_iteration_is_still_a_line(tmp_path: Path) -> None:
    """The record of what was tried must not depend on it having worked."""
    path = tmp_path / "iterations.jsonl"
    append_iteration(
        path,
        iteration_line(
            iter_number=0,
            drc="fail",
            param_delta={"gap": [0.2, 0.0]},
            error="DRC refused: min_spacing violated",
        ),
    )
    assert read_iterations(path)[0]["error"].startswith("DRC refused")


def test_setup_delta_and_param_delta_stay_distinguishable(tmp_path: Path) -> None:
    """A mesh study and a geometry study must never look alike in the record."""
    path = tmp_path / "iterations.jsonl"
    append_iteration(path, iteration_line(iter_number=0, drc="pass", param_delta={"gap": [0.2, 0.21]}))
    append_iteration(
        path,
        iteration_line(iter_number=1, drc="pass", setup_delta={"steps_per_wavelength": [14, 20]}),
    )
    geometry, mesh = read_iterations(path)
    assert geometry["param_delta"] and not geometry["setup_delta"]
    assert mesh["setup_delta"] and not mesh["param_delta"]


# ----------------------------------------------------------------- touchstone


def _write_s2p(path: Path, frequencies_ghz, s11, s21=None, fmt="RI") -> Path:
    """Write a synthetic two-port file. ``s11``/``s21`` are complex sequences."""
    lines = ["! synthetic test fixture", f"# GHz S {fmt} R 50"]
    for index, frequency in enumerate(frequencies_ghz):
        a = s11[index]
        b = (s21[index] if s21 is not None else complex(0.0, 0.0))
        row = [f"{frequency:.9g}"]
        for value in (a, b, b, a):  # two-port order: S11 S21 S12 S22
            if fmt == "RI":
                row += [f"{value.real:.9g}", f"{value.imag:.9g}"]
            elif fmt == "MA":
                row += [f"{abs(value):.9g}", f"{math.degrees(cmath.phase(value)):.9g}"]
            else:  # DB
                magnitude = 20.0 * math.log10(max(abs(value), 1e-30))
                row += [f"{magnitude:.9g}", f"{math.degrees(cmath.phase(value)):.9g}"]
        lines.append(" ".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_touchstone_reads_frequencies_in_hz_and_complex_entries(tmp_path: Path) -> None:
    path = _write_s2p(tmp_path / "x.s2p", [1.0, 1.1], [complex(0.1, 0.0), complex(0.2, 0.0)])
    data = read_touchstone(path)
    assert data.ports == 2
    assert data.frequencies_hz == (1e9, 1.1e9)
    assert data.s[(1, 1)][0] == complex(0.1, 0.0)


@pytest.mark.parametrize("fmt", ["RI", "MA", "DB"])
def test_every_declared_format_yields_the_same_curve(tmp_path: Path, fmt: str) -> None:
    """A DB-format file read as RI produces plausible numbers that are wrong."""
    values = [complex(0.05, 0.02), complex(0.3, -0.1)]
    data = read_touchstone(_write_s2p(tmp_path / f"{fmt}.s2p", [1.0, 1.1], values, fmt=fmt))
    for index, expected in enumerate(values):
        assert abs(data.s[(1, 1)][index] - expected) < 1e-6


def test_a_file_without_an_option_line_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "x.s2p"
    path.write_text("1.0 0.1 0 0 0 0 0 0.1 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no '#' option line"):
        read_touchstone(path)


def test_a_truncated_row_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "x.s2p"
    path.write_text("# GHz S RI R 50\n1.0 0.1 0.0 0.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="whole number"):
        read_touchstone(path)


def test_non_monotonic_frequencies_are_refused(tmp_path: Path) -> None:
    path = _write_s2p(tmp_path / "x.s2p", [1.1, 1.0], [complex(0.1, 0), complex(0.1, 0)])
    with pytest.raises(ValueError, match="strictly increasing"):
        read_touchstone(path)


def test_curve_uses_twenty_log_ten_of_the_magnitude(tmp_path: Path) -> None:
    data = read_touchstone(_write_s2p(tmp_path / "x.s2p", [1.0], [complex(0.1, 0.0)]))
    assert curve(data, 1, 1, "db")[0] == pytest.approx(-20.0)


def test_curve_survives_a_perfect_null(tmp_path: Path) -> None:
    data = read_touchstone(_write_s2p(tmp_path / "x.s2p", [1.0], [complex(0.0, 0.0)]))
    assert curve(data, 1, 1, "db")[0] < -500.0


def test_curve_unwraps_phase(tmp_path: Path) -> None:
    angles = [170.0, -170.0, -150.0]
    values = [cmath.rect(1.0, math.radians(a)) for a in angles]
    data = read_touchstone(_write_s2p(tmp_path / "x.s2p", [1.0, 1.1, 1.2], values))
    unwrapped = curve(data, 1, 1, "deg")
    assert unwrapped[1] == pytest.approx(190.0, abs=1e-6)
    assert unwrapped[2] == pytest.approx(210.0, abs=1e-6)


def test_a_two_port_file_is_read_in_touchstone_s11_s21_s12_s22_order(tmp_path: Path) -> None:
    """The format specifies this order only for two ports, unlike every other N.

    A non-reciprocal fixture is the only way to see the mistake: on a filter,
    S21 == S12 and transposing them changes nothing.
    """
    path = tmp_path / "x.s2p"
    path.write_text(
        "# GHz S RI R 50\n"
        # f    S11      S21      S12      S22
        "1.0  0.1 0.0  0.7 0.0  0.3 0.0  0.2 0.0\n",
        encoding="utf-8",
    )
    data = read_touchstone(path)
    assert data.s[(1, 1)][0] == complex(0.1, 0.0)
    assert data.s[(2, 1)][0] == complex(0.7, 0.0), "forward transmission"
    assert data.s[(1, 2)][0] == complex(0.3, 0.0), "reverse transmission"
    assert data.s[(2, 2)][0] == complex(0.2, 0.0)


def test_a_four_port_file_is_read_row_major(tmp_path: Path) -> None:
    """Four-port files are row-major, so S21 and S43 must land where they belong.

    This is the ordering a phase-difference metric depends on; getting it wrong
    would leave every magnitude looking correct and every phase wrong.
    """
    path = tmp_path / "x.s4p"
    row = [f"{value:.4g}" for index in range(16) for value in (index / 100.0, 0.0)]
    path.write_text("# GHz S RI R 50\n1.0 " + " ".join(row) + "\n", encoding="utf-8")
    data = read_touchstone(path)
    assert data.ports == 4
    # Row-major: index = (out-1)*4 + (in-1)
    assert data.s[(1, 1)][0].real == pytest.approx(0.00)
    assert data.s[(2, 1)][0].real == pytest.approx(0.04)
    assert data.s[(4, 3)][0].real == pytest.approx(0.14)
    assert data.s[(4, 4)][0].real == pytest.approx(0.15)


def test_asking_for_a_port_the_file_lacks_is_refused(tmp_path: Path) -> None:
    data = read_touchstone(_write_s2p(tmp_path / "x.s2p", [1.0], [complex(0.1, 0.0)]))
    with pytest.raises(ValueError, match="does not contain S43"):
        curve(data, 4, 3, "db")


# ---------------------------------------------------------------------- gates


def _gate(**changes):
    entry = {
        "id": "g",
        "metric": "s1_1_db",
        "band_ghz": [1.0, 1.1],
        "comparator": "<",
        "threshold": -10.0,
        "mode": "pointwise",
        "min_samples": 3,
    }
    entry.update(changes)
    return parse_gates({"acceptance": [entry]})[0]


def _flat_s11(tmp_path: Path, db: float, points: int = 11, low: float = 0.9, high: float = 1.2):
    magnitude = 10.0 ** (db / 20.0)
    frequencies = [low + (high - low) * i / (points - 1) for i in range(points)]
    values = [complex(magnitude, 0.0)] * points
    return read_touchstone(_write_s2p(tmp_path / "flat.s2p", frequencies, values))


def test_a_pointwise_gate_passes_when_every_sample_satisfies_it(tmp_path: Path) -> None:
    result = evaluate_gate(_gate(), _flat_s11(tmp_path, -15.0))
    assert result.status == "pass"
    assert result.measured == pytest.approx(-15.0, abs=1e-6)


def test_a_pointwise_gate_fails_and_localises_the_worst_sample(tmp_path: Path) -> None:
    frequencies = [0.9 + 0.03 * i for i in range(11)]
    values = [complex(10 ** (-15 / 20), 0.0)] * 11
    values[5] = complex(10 ** (-6 / 20), 0.0)  # a single spike at 1.05 GHz
    data = read_touchstone(_write_s2p(tmp_path / "spike.s2p", frequencies, values))
    result = evaluate_gate(_gate(), data)
    assert result.status == "fail"
    assert result.measured == pytest.approx(-6.0, abs=1e-6)
    assert result.worst_frequency_ghz == pytest.approx(1.05, abs=1e-9)


def test_a_gate_whose_band_the_sweep_does_not_cover_errors(tmp_path: Path) -> None:
    """A vacuous pass is worse than a wrong threshold: it looks like a real one."""
    data = _flat_s11(tmp_path, -15.0, low=1.0, high=1.05)
    result = evaluate_gate(_gate(band_ghz=[1.0, 1.1]), data)
    assert result.status == "error"
    assert "not covered" in result.reason


def test_a_gate_on_too_few_samples_errors_rather_than_passing(tmp_path: Path) -> None:
    data = _flat_s11(tmp_path, -15.0, points=5, low=0.5, high=2.0)
    result = evaluate_gate(_gate(min_samples=5), data)
    assert result.status == "error"
    assert "too coarse" in result.reason


def test_band_edges_are_interpolated_into_a_pointwise_verdict(tmp_path: Path) -> None:
    """Without interpolated edges a violation straddling the edge is invisible."""
    frequencies = [0.95, 0.99, 1.05, 1.11, 1.15]
    good, bad = 10 ** (-20 / 20), 10 ** (-2 / 20)
    values = [complex(bad, 0.0), complex(bad, 0.0)] + [complex(good, 0.0)] * 3
    data = read_touchstone(_write_s2p(tmp_path / "edge.s2p", frequencies, values))
    # The band starts at 1.00 GHz, between the bad sample at 0.99 and the good one
    # at 1.05, so only the interpolated edge can see the violation.
    result = evaluate_gate(_gate(band_ghz=[1.00, 1.10], min_samples=1), data)
    assert result.status == "fail"


def test_a_single_frequency_gate_needs_no_minimum_sample_count(tmp_path: Path) -> None:
    data = _flat_s11(tmp_path, -15.0)
    result = evaluate_gate(_gate(band_ghz=[1.05, 1.05], min_samples=99), data)
    assert result.status == "pass"


@pytest.mark.parametrize(
    "aggregate,expected",
    [("min", -20.0), ("max", -10.0), ("ripple", 10.0)],
)
def test_aggregations_reduce_the_band_before_comparing(
    tmp_path: Path, aggregate: str, expected: float
) -> None:
    frequencies = [1.0, 1.05, 1.1]
    values = [complex(10 ** (-10 / 20), 0), complex(10 ** (-15 / 20), 0), complex(10 ** (-20 / 20), 0)]
    data = read_touchstone(_write_s2p(tmp_path / "slope.s2p", frequencies, values))
    gate = _gate(mode="aggregate", aggregate=aggregate, threshold=1000.0, min_samples=3)
    result = evaluate_gate(gate, data)
    assert result.measured == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize(
    "comparator,threshold,expected",
    [
        ("<", -10.0, "pass"),
        ("<", -20.0, "fail"),
        ("<=", -10.0, "pass"),
        ("<=", -20.0, "fail"),
        (">", -20.0, "pass"),
        (">", -10.0, "fail"),
        (">=", -20.0, "pass"),
        (">=", -10.0, "fail"),
    ],
)
def test_every_comparator_is_honoured(
    tmp_path: Path, comparator: str, threshold: float, expected: str
) -> None:
    """Thresholds are kept clear of the measured value on purpose.

    A -15 dB curve written to a text file and read back lands a fraction of a
    femto-dB off -15, so a gate whose threshold is exactly the measured value is
    decided by float representation rather than by engineering. Real gates should
    likewise not be set exactly at an expected value.
    """
    data = _flat_s11(tmp_path, -15.0)
    assert evaluate_gate(_gate(comparator=comparator, threshold=threshold), data).status == expected


def test_a_failed_desired_gate_does_not_fail_the_iteration(tmp_path: Path) -> None:
    data = _flat_s11(tmp_path, -5.0)
    gates = parse_gates(
        {
            "acceptance": [
                {
                    "id": "required_one",
                    "metric": "s1_1_db",
                    "band_ghz": [1.0, 1.1],
                    "comparator": "<",
                    "threshold": -3.0,
                    "mode": "pointwise",
                    "min_samples": 3,
                },
                {
                    "id": "desired_one",
                    "metric": "s1_1_db",
                    "band_ghz": [1.0, 1.1],
                    "comparator": "<",
                    "threshold": -15.0,
                    "mode": "pointwise",
                    "severity": "desired",
                    "min_samples": 3,
                },
            ]
        }
    )
    report = evaluate_gates(gates, data)
    assert report.status == "pass"
    assert {g.id: g.status for g in report.gates} == {"required_one": "pass", "desired_one": "fail"}


def test_an_error_on_a_required_gate_is_not_reported_as_a_failure(tmp_path: Path) -> None:
    """'we could not tell' and 'it does not meet spec' are different answers."""
    data = _flat_s11(tmp_path, -20.0, low=1.0, high=1.05)
    report = evaluate_gates([_gate(band_ghz=[1.0, 1.4])], data)
    assert report.status == "error"


def test_a_gate_report_serialises_the_context_needed_to_see_why(tmp_path: Path) -> None:
    report = evaluate_gates([_gate()], _flat_s11(tmp_path, -15.0))
    record = report.to_json()
    assert record["status"] == "pass"
    entry = record["gates"][0]
    assert entry["gate"].startswith("s1_1_db every point in")
    assert entry["threshold"] == -10.0
    assert entry["samples_in_band"] >= 3


# ------------------------------------------- derived metrics on a four-port device


def _write_s4p(path: Path, frequencies_ghz, main, reference) -> Path:
    """Write a synthetic four-port file with two independent through paths.

    Ports 1-2 are the main line and ports 3-4 the reference line, with no coupling
    between them, which is the topology a phase shifter is measured in.
    """
    lines = ["! synthetic four-port fixture", "# GHz S RI R 50"]
    for index, frequency in enumerate(frequencies_ghz):
        matrix = [[complex(0.0, 0.0)] * 4 for _ in range(4)]
        matrix[1][0] = matrix[0][1] = main[index]
        matrix[3][2] = matrix[2][3] = reference[index]
        row = [f"{frequency:.9g}"]
        for out in range(4):  # N != 2 is row-major
            for inp in range(4):
                value = matrix[out][inp]
                row += [f"{value.real:.9g}", f"{value.imag:.9g}"]
        lines.append(" ".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _shifter(tmp_path: Path, shift_deg, points: int = 21, low: float = 2.0, high: float = 4.0):
    """A four-port whose S21 leads S43 by ``shift_deg`` at every frequency."""
    frequencies = [low + (high - low) * i / (points - 1) for i in range(points)]
    if not isinstance(shift_deg, (list, tuple)):
        shift_deg = [shift_deg] * points
    # Both branches also carry a steep common phase slope, so a reader that
    # subtracts two independently unwrapped curves gets this wrong.
    reference = [cmath.exp(-1j * math.radians(700.0 * f)) for f in frequencies]
    main = [
        value * cmath.exp(1j * math.radians(shift))
        for value, shift in zip(reference, shift_deg)
    ]
    return read_touchstone(_write_s4p(tmp_path / "shifter.s4p", frequencies, main, reference))


def _phase_gate(**changes):
    entry = {
        "id": "phase_in_band",
        "metric": "phase_deviation_deg",
        "main": [2, 1],
        "reference": [4, 3],
        "target": 180.0,
        "anchor_ghz": 3.0,
        "band_ghz": [2.5, 3.5],
        "comparator": "<=",
        "threshold": 3.437,
        "mode": "pointwise",
        "min_samples": 3,
    }
    entry.update(changes)
    return parse_gates({"acceptance": [entry]})[0]


def test_a_phase_difference_survives_a_steep_common_slope(tmp_path: Path) -> None:
    """The whole point of forming the difference before unwrapping."""
    data = _shifter(tmp_path, 180.0)
    values = phase_difference_deg(data, (2, 1), (4, 3), anchor_ghz=3.0, anchor_target_deg=180.0)
    assert max(abs(v - 180.0) for v in values) < 1e-6


def test_the_anchor_selects_which_360_degree_branch_is_meant(tmp_path: Path) -> None:
    """+180 and -180 produce the identical curve; only the anchor tells them apart."""
    data = _shifter(tmp_path, 180.0)
    positive = phase_difference_deg(data, (2, 1), (4, 3), 3.0, 180.0)
    negative = phase_difference_deg(data, (2, 1), (4, 3), 3.0, -180.0)
    assert positive[0] == pytest.approx(180.0, abs=1e-6)
    assert negative[0] == pytest.approx(-180.0, abs=1e-6)


def test_an_anchor_outside_the_sweep_is_refused(tmp_path: Path) -> None:
    data = _shifter(tmp_path, 180.0)
    with pytest.raises(ValueError, match="outside the swept range"):
        phase_difference_deg(data, (2, 1), (4, 3), 9.0, 180.0)


def test_a_reversed_port_pair_flips_the_sign_of_the_shift(tmp_path: Path) -> None:
    """Which branch is 'main' is a declaration, not something to be inferred."""
    data = _shifter(tmp_path, 180.0)
    swapped = phase_difference_deg(data, (4, 3), (2, 1), 3.0, -180.0)
    assert swapped[0] == pytest.approx(-180.0, abs=1e-6)


def test_amplitude_imbalance_is_the_absolute_difference(tmp_path: Path) -> None:
    frequencies = [2.0, 3.0, 4.0]
    main = [complex(10 ** (-1.0 / 20), 0.0)] * 3
    reference = [complex(10 ** (-0.5 / 20), 0.0)] * 3
    data = read_touchstone(_write_s4p(tmp_path / "imbalance.s4p", frequencies, main, reference))
    values = amplitude_imbalance_db(data, (2, 1), (4, 3))
    assert all(v == pytest.approx(0.5, abs=1e-6) for v in values)


def test_a_derived_gate_passes_inside_its_tolerance(tmp_path: Path) -> None:
    result = evaluate_gate(_phase_gate(), _shifter(tmp_path, 182.0))
    assert result.status == "pass"
    assert result.metric == "phase_deviation_deg"
    assert result.measured == pytest.approx(2.0, abs=1e-6)
    assert "S21 vs S43" in result.describe


def test_a_derived_gate_fails_and_localises_the_worst_frequency(tmp_path: Path) -> None:
    shifts = [180.0] * 21
    shifts[10] = 190.0  # 3.0 GHz
    result = evaluate_gate(_phase_gate(), _shifter(tmp_path, shifts))
    assert result.status == "fail"
    assert result.measured == pytest.approx(10.0, abs=1e-6)
    assert result.worst_frequency_ghz == pytest.approx(3.0, abs=1e-9)


def test_a_derived_gate_on_a_two_port_export_errors_rather_than_passing(tmp_path: Path) -> None:
    result = evaluate_gate(_phase_gate(), _flat_s11(tmp_path, -20.0, low=2.0, high=4.0))
    assert result.status == "error"
    assert "does not contain S43" in (result.reason or "")


# -------------------------------------------------- derived gates are fail-closed


@pytest.mark.parametrize("missing", ["main", "reference", "target", "anchor_ghz"])
def test_a_derived_gate_missing_its_binding_is_refused(missing: str) -> None:
    """Every one of these has a tempting default that would produce a wrong verdict."""
    with pytest.raises(ValueError, match=missing):
        _phase_gate(**{missing: None})


def test_a_single_curve_gate_carrying_derived_fields_is_refused() -> None:
    """A field that is silently ignored reads as if it took effect."""
    with pytest.raises(ValueError, match="ignores 'main'"):
        _gate(main=[2, 1])


def test_a_derived_gate_measuring_a_branch_against_itself_is_refused() -> None:
    with pytest.raises(ValueError, match="identically zero"):
        _phase_gate(reference=[2, 1])


def test_amplitude_imbalance_refuses_a_target_it_would_ignore() -> None:
    with pytest.raises(ValueError, match="does not use 'target'"):
        _phase_gate(metric="amplitude_imbalance_db", target=0.0, anchor_ghz=None, threshold=0.2)


def test_a_derived_gate_reaching_past_the_declared_port_count_is_refused(tmp_path: Path) -> None:
    """The reference branch has to be checked too, not only the main one.

    Before derived metrics, a gate named every port it read in its own metric name.
    A phase gate hides two of them in ``reference``, so the port-count check has to
    look there as well or a two-port model would accept a four-port gate.
    """
    header, _, body = load_design(FIXTURE_DESIGN / "design.md")
    header["ports"] = 2
    header["acceptance"] = [
        {
            "id": "phase_in_band",
            "metric": "phase_deviation_deg",
            "main": [2, 1],
            "reference": [4, 3],
            "target": 180.0,
            "anchor_ghz": 3.0,
            "band_ghz": [1.0, 1.1],
            "comparator": "<=",
            "threshold": 3.437,
            "mode": "pointwise",
        }
    ]
    target = tmp_path / "filter-fixture" / "design.md"
    write_design(target, header, body)
    with pytest.raises(ValueError, match=r"reference port\(s\) \[3, 4\]"):
        load_design(target)
