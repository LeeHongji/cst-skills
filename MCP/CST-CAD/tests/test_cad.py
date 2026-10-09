from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "MCP" / "CST-CAD" / "src"))

from cst_cad import drc, emit_vba, ir  # noqa: E402
from cst_cad.dsl import Expr, ModelBuilder, as_expr  # noqa: E402

PUBLIC_CAD_DESIGN = Path(__file__).parent / "fixtures" / "public-cad"
PUBLIC_CAD_IR = PUBLIC_CAD_DESIGN / "geometry-ir.json"
PUBLIC_CAD_MODEL = PUBLIC_CAD_DESIGN / "model.py"


# --------------------------------------------------------------------- fixtures


def two_net_model(gap: float = 0.5, width: float = 0.4, bridge: bool = False, split: bool = False) -> dict:
    """A minimal two-net board used to exercise the DRC rules both ways."""
    model = ModelBuilder(model_id="drc-fixture", title="DRC fixture")
    model.units(length="mm", frequency="GHz")
    t_cu = model.param("t_cu", 0.035, provenance="assumption")
    h = model.param("h", 1.0, provenance="assumption")
    model.material("Sub", kind="normal", epsilon=4.4, mu=1.0, tan_delta=0.02)
    model.material("PEC", kind="pec")
    model.layer("sub", 0.0, h, "Sub", role="substrate")
    model.layer("top", h, h + t_cu, "PEC", role="signal")

    board = model.net("BOARD", "sub", net_class="reference")
    board.box(-6.0, -6.0, 20.0, 22.0)

    # LEFT is an L: a vertical trace with an arm that runs away from RIGHT, so the
    # only tight cross-net gap in the fixture is the trace-to-trace one.
    left = model.net("LEFT", "top")
    left.rect(0.0, 0.0, width, 10.0, solid_id="trace")
    # `split` lifts the arm 1 mm clear of the trace, breaking the net in two.
    left.rect(-3.0, 11.0 if split else 10.0, 3.0 + width, width, solid_id="arm")

    right = model.net("RIGHT", "top")
    right.rect(width + gap, 0.0, width, 8.0, solid_id="trace")
    if bridge:
        # Spans the gap and touches both traces: an unintended short.
        right.rect(width, 4.0, gap, width, solid_id="bridge")

    model.port("P1", 1, "LEFT", "ymin", 0.0, 0.0, 0.0, width, 0.0, h + t_cu)
    return model.build()


@pytest.fixture(scope="module")
def cad_fixture() -> dict:
    return ir.read(PUBLIC_CAD_IR)


# ------------------------------------------------------------- IR canonical form


def test_intent_id_is_stable_across_key_and_declaration_order(cad_fixture: dict) -> None:
    shuffled = copy.deepcopy(cad_fixture)
    shuffled["nets"] = list(reversed(shuffled["nets"]))
    shuffled["parameters"] = list(reversed(shuffled["parameters"]))
    for net in shuffled["nets"]:
        net["solids"] = list(reversed(net["solids"]))
    assert ir.model_intent_id(shuffled) == ir.model_intent_id(cad_fixture)


def test_intent_id_ignores_float_noise_below_resolution(cad_fixture: dict) -> None:
    noisy = copy.deepcopy(cad_fixture)
    for net in noisy["nets"]:
        for solid in net["solids"]:
            if solid["kind"] == "box":
                solid["box"]["x0"] += 1e-13
    assert ir.model_intent_id(noisy) == ir.model_intent_id(cad_fixture)


def test_intent_id_changes_when_a_real_dimension_moves(cad_fixture: dict) -> None:
    moved = copy.deepcopy(cad_fixture)
    moved["nets"][0]["solids"][0]["box"]["x0"] += 0.001
    assert ir.model_intent_id(moved) != ir.model_intent_id(cad_fixture)


def test_intent_id_ignores_metadata_and_analysis_setup(cad_fixture: dict) -> None:
    rebranded = copy.deepcopy(cad_fixture)
    rebranded["title"] = "a completely different title"
    rebranded["description"] = None
    rebranded["source"] = {"paper": "someone else"}
    rebranded["derived"] = {}
    rebranded["simulation"]["frequency"]["max"] = 99.0
    rebranded["simulation"]["convergence"]["max_passes"] = 1
    rebranded["simulation"]["monitors"] = []
    assert ir.model_intent_id(rebranded) == ir.model_intent_id(cad_fixture)


def test_intent_id_treats_absent_and_null_identically(cad_fixture: dict) -> None:
    with_nulls = copy.deepcopy(cad_fixture)
    for parameter in with_nulls["parameters"]:
        parameter.setdefault("description", None)
        parameter.setdefault("min", None)
    assert ir.model_intent_id(with_nulls) == ir.model_intent_id(cad_fixture)


def test_canonical_number_collapses_accumulated_noise() -> None:
    assert ir.canonical_number(15.299999999999999) == ir.canonical_number(15.3)
    assert ir.canonical_number(-0.0) == ir.canonical_number(0.0)
    assert ir.canonical_number(7.949999999999999) == "7.95"


def test_canonical_number_rejects_non_finite() -> None:
    with pytest.raises(ir.IRError):
        ir.canonical_number(float("inf"))
    with pytest.raises(ir.IRError):
        ir.canonical_number(float("nan"))


def test_stamp_is_idempotent(cad_fixture: dict) -> None:
    once = ir.stamp(cad_fixture)
    assert ir.stamp(once)["model_intent_id"] == once["model_intent_id"]


# --------------------------------------------------------------- topology digest


def _perturb_dimensions(document: dict, scale: float = 1.37) -> dict:
    """Return the document with every *dimension* changed and nothing else.

    A parameter change in a real iteration moves the parameter and every
    coordinate derived from it, so testing one edited value would understate the
    claim.  Changing them all at once is the strongest form of the property
    ``topology_hash`` promises: invariance to dimensions, whatever they are.

    The sections in :data:`ir.TOPOLOGY_NUMERIC_SECTIONS` are left alone, because
    their numbers are deliberately part of the topology -- see the DRC-loosening
    test below.
    """

    def walk(value):
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return value
        if isinstance(value, int):
            return value + 3
        return round(value * scale + 0.011, 6)

    return {
        key: value if key in ir.TOPOLOGY_NUMERIC_SECTIONS else walk(value)
        for key, value in document.items()
    }


def test_topology_hash_survives_every_dimension_changing(cad_fixture: dict) -> None:
    moved = _perturb_dimensions(cad_fixture)
    assert ir.topology_hash(moved) == ir.topology_hash(cad_fixture)
    assert ir.model_intent_id(moved) != ir.model_intent_id(cad_fixture)


def test_topology_hash_survives_the_documented_parameter_nudge(cad_fixture: dict) -> None:
    """The plan's worked example: a coupling gap moves 5 um and iteration continues."""
    nudged = copy.deepcopy(cad_fixture)
    for parameter in nudged["parameters"]:
        if parameter["name"] == "coupling_gap":
            parameter["value"] = round(float(parameter["value"]) + 0.005, 6)
            break
    else:  # pragma: no cover - guards against a silent fixture change
        pytest.fail("cad_fixture no longer declares coupling_gap")
    assert ir.topology_hash(nudged) == ir.topology_hash(cad_fixture)


def test_topology_hash_ignores_declaration_and_key_order(cad_fixture: dict) -> None:
    shuffled = copy.deepcopy(cad_fixture)
    shuffled["nets"] = list(reversed(shuffled["nets"]))
    for net in shuffled["nets"]:
        net["solids"] = list(reversed(net.get("solids", [])))
    shuffled["parameters"] = list(reversed(shuffled["parameters"]))
    assert ir.topology_hash(shuffled) == ir.topology_hash(cad_fixture)


def test_topology_hash_ignores_annotations(cad_fixture: dict) -> None:
    relabelled = copy.deepcopy(cad_fixture)
    for parameter in relabelled["parameters"]:
        parameter["provenance"] = "optimized"
        parameter["description"] = "rewritten"
        parameter["tunable"] = True
    for material in relabelled["materials"]:
        material["note"] = "rewritten"
        material["color"] = [1, 2, 3]
    assert ir.topology_hash(relabelled) == ir.topology_hash(cad_fixture)


def test_topology_hash_ignores_mesh_density(cad_fixture: dict) -> None:
    """Mesh is how we look at the device, not which device it is."""
    refined = copy.deepcopy(cad_fixture)
    refined["mesh_hints"]["steps_per_wavelength_near"] = 30.0
    assert ir.topology_hash(refined) == ir.topology_hash(cad_fixture)
    assert ir.model_intent_id(refined) != ir.model_intent_id(cad_fixture)


def test_topology_hash_ignores_simulation_setup(cad_fixture: dict) -> None:
    retuned = copy.deepcopy(cad_fixture)
    retuned["simulation"]["frequency"] = {"min": 0.1, "max": 9.9}
    assert ir.topology_hash(retuned) == ir.topology_hash(cad_fixture)


@pytest.mark.parametrize(
    "mutate,what",
    [
        (lambda d: d["nets"][2]["solids"].pop(), "a solid is removed"),
        (
            lambda d: d["nets"][2]["solids"].append(
                {"id": "extra", "kind": "box", "box": {"x0": 0.0, "x1": 1.0, "y0": 0.0, "y1": 1.0, "z0": 1.27, "z1": 1.305}}
            ),
            "a solid is added",
        ),
        (lambda d: d["nets"][2].update(name="RENAMED_FEED"), "a net is renamed"),
        (lambda d: d["nets"][2]["solids"][0].update(id="renamed"), "a solid is renamed"),
        (lambda d: d["nets"][2].update(layer="ground_plane"), "a net moves layer"),
        (lambda d: d["nets"][2].update(net_class="ground"), "a net changes class"),
        (lambda d: d["ports"][0].update(net="LOAD_FEED"), "a port is repointed"),
        (lambda d: d["ports"][0].update(orientation="xmax"), "a port turns around"),
        (lambda d: d["ports"][0].pop("impedance"), "a port loses its impedance"),
        (lambda d: d["ports"][0]["expressions"].update(x0="board_xmax"), "an expression changes"),
        (lambda d: d["parameters"].pop(), "a parameter is removed"),
        (
            lambda d: d["parameters"].append({"name": "zz_new", "value": 1.0, "provenance": "assumption", "tunable": True}),
            "a parameter is added",
        ),
        (lambda d: d["parameters"][0].update(name="er_substrate"), "a parameter is renamed"),
        (lambda d: d["materials"][0].update(name="Substrate_Other"), "a material is renamed"),
        (lambda d: d["materials"][0].update(epsilon="er_other"), "a material references another parameter"),
        (lambda d: d["materials"][0].update(kind="anisotropic"), "a material changes kind"),
        (lambda d: d["stackup"][1].update(material="PEC"), "a layer changes material"),
        (lambda d: d["stackup"][1].update(role="signal"), "a layer changes role"),
        (lambda d: d["boundaries"].update(zmax="electric"), "a boundary condition changes"),
        (lambda d: d["units"].update(length="mil"), "the length unit changes"),
    ],
)
def test_topology_hash_changes_when_the_structure_changes(cad_fixture: dict, mutate, what: str) -> None:
    mutated = copy.deepcopy(cad_fixture)
    mutate(mutated)
    assert ir.topology_hash(mutated) != ir.topology_hash(cad_fixture), what


def test_topology_hash_changes_when_a_drc_rule_is_loosened(cad_fixture: dict) -> None:
    """The one place numbers are kept, and the reason the audit gate is safe.

    ``topology_hash`` cannot see a gap driven to zero -- the expressions do not
    change when two conductors merge -- so DRC is what catches it.  If rule
    thresholds were dropped along with every other number, that net could be
    loosened inside an approved attempt and the approval would still look valid.
    """
    loosened = copy.deepcopy(cad_fixture)
    for rule in loosened["design_rules"]:
        if rule["rule"] == "min_spacing":
            rule["params"]["min_spacing"] = 0.001
            break
    else:  # pragma: no cover
        pytest.fail("cad_fixture no longer declares a min_spacing rule")
    assert ir.topology_hash(loosened) != ir.topology_hash(cad_fixture)


def test_topology_hash_changes_when_a_drc_rule_is_dropped(cad_fixture: dict) -> None:
    without = copy.deepcopy(cad_fixture)
    without["design_rules"] = without["design_rules"][:-1]
    assert ir.topology_hash(without) != ir.topology_hash(cad_fixture)


def test_topology_hash_is_coarser_than_the_intent_id(cad_fixture: dict) -> None:
    """Every topology change is an intent change, but not the reverse."""
    moved = _perturb_dimensions(cad_fixture)
    assert ir.model_intent_id(moved) != ir.model_intent_id(cad_fixture)
    assert ir.topology_hash(moved) == ir.topology_hash(cad_fixture)

    restructured = copy.deepcopy(cad_fixture)
    restructured["nets"][2].update(name="RENAMED")
    assert ir.model_intent_id(restructured) != ir.model_intent_id(cad_fixture)
    assert ir.topology_hash(restructured) != ir.topology_hash(cad_fixture)


def test_short_topology_hash_is_prefixed_and_accepts_a_digest(cad_fixture: dict) -> None:
    digest = ir.topology_hash(cad_fixture)
    assert ir.short_topology_hash(cad_fixture) == f"topo-{digest[:12]}"
    assert ir.short_topology_hash(digest) == ir.short_topology_hash(cad_fixture)


def test_topology_hash_distinguishes_a_missing_key_from_a_changed_number() -> None:
    """Numbers collapse to a placeholder rather than vanishing.

    Deleting them outright would make ``{"z0": 0.0}`` and ``{}`` hash alike, so
    removing a coordinate would read as a dimension change and slip through the
    audit gate.
    """
    with_key = {"schema_version": 1, "nets": [{"name": "N", "solids": [{"id": "s", "box": {"z0": 0.0}}]}]}
    without_key = {"schema_version": 1, "nets": [{"name": "N", "solids": [{"id": "s", "box": {}}]}]}
    assert ir.topology_hash(with_key) != ir.topology_hash(without_key)


# -------------------------------------------------------------------- validation


def test_cad_fixture_ir_validates_cleanly(cad_fixture: dict) -> None:
    assert ir.validate(cad_fixture) == []


def test_validation_catches_a_tampered_identity(cad_fixture: dict) -> None:
    tampered = copy.deepcopy(cad_fixture)
    tampered["model_intent_id"] = "0" * 64
    problems = ir.validate(tampered)
    assert any("model_intent_id" in problem for problem in problems)


def test_validation_catches_dangling_layer_reference(cad_fixture: dict) -> None:
    broken = copy.deepcopy(cad_fixture)
    broken["nets"][0]["layer"] = "no_such_layer"
    broken = ir.stamp(broken)
    problems = ir.validate(broken)
    assert any("unknown layer" in problem for problem in problems)


def test_validation_catches_inverted_box(cad_fixture: dict) -> None:
    broken = copy.deepcopy(cad_fixture)
    box = next(solid["box"] for net in broken["nets"] for solid in net["solids"] if solid["kind"] == "box")
    box["x1"] = box["x0"] - 1.0
    broken = ir.stamp(broken)
    assert any("x1 <= x0" in problem for problem in ir.validate(broken))


def test_validation_catches_port_on_unknown_net(cad_fixture: dict) -> None:
    broken = copy.deepcopy(cad_fixture)
    broken["ports"][0]["net"] = "NOT_A_NET"
    broken = ir.stamp(broken)
    assert any("unknown net" in problem for problem in ir.validate(broken))


def test_schema_rejects_an_unknown_provenance_value(cad_fixture: dict) -> None:
    broken = copy.deepcopy(cad_fixture)
    broken["parameters"][0]["provenance"] = "vibes"
    broken = ir.stamp(broken)
    assert any("provenance" in problem or "vibes" in problem for problem in ir.validate(broken))


# --------------------------------------------------------------------------- DSL


def test_expression_precedence_is_parenthesised_correctly() -> None:
    a = Expr("a", 2.0)
    b = Expr("b", 3.0)
    c = Expr("c", 4.0)
    assert (a + b).text == "a+b"
    assert (a - (b + c)).text == "a-(b+c)"
    assert ((a + b) * c).text == "(a+b)*c"
    assert (a / (b + c)).text == "a/(b+c)"
    assert (a * b / c).text == "a*b/c"
    assert float(a + b * c) == 14.0


def test_rect_records_both_a_value_and_an_expression() -> None:
    document = two_net_model()
    solid = next(s for net in document["nets"] if net["name"] == "LEFT" for s in net["solids"] if s["id"] == "trace")
    assert solid["box"]["x1"] == pytest.approx(0.4)
    assert solid["expressions"]["y1"] == "0.0+10.0"


def test_duplicate_parameter_is_rejected() -> None:
    model = ModelBuilder(model_id="dup")
    model.param("w", 1.0, provenance="assumption")
    with pytest.raises(ValueError):
        model.param("w", 2.0, provenance="assumption")


def test_unknown_provenance_is_rejected_at_declaration_time() -> None:
    model = ModelBuilder(model_id="bad")
    with pytest.raises(ValueError):
        model.param("w", 1.0, provenance="guessed")


def test_as_expr_keeps_negative_literals_safe_for_concatenation() -> None:
    assert (Expr("a", 1.0) * as_expr(-2.0)).text == "a*(-2.0)"


# ----------------------------------------------------------------- overrides


def _tunable_model(overrides: dict | None = None) -> ModelBuilder:
    """A model whose one tunable parameter drives one derived parameter and one solid."""
    model = ModelBuilder(model_id="tune", overrides=overrides)
    model.units(length="mm", frequency="GHz")
    w = model.param("w", 1.0, provenance="assumption", tunable=True, minimum=0.5, maximum=2.0)
    h = model.param("h", 1.27, provenance="paper_explicit")
    model.derived_param("w_half", w / as_expr(2.0))
    model.material("PEC", kind="pec")
    model.layer("top", h, h + as_expr(0.035), "PEC", role="signal")
    net = model.net("N", "top")
    net.rect(as_expr(0.0), as_expr(0.0), w, w, solid_id="pad")
    return model


def test_override_moves_the_parameter_and_everything_derived_from_it() -> None:
    document = _tunable_model({"w": 1.5}).build()
    values = {p["name"]: p["value"] for p in document["parameters"]}
    assert values["w"] == 1.5
    assert values["w_half"] == 0.75
    solid = document["nets"][0]["solids"][0]
    assert solid["box"]["x1"] == 1.5
    # The solid's own expression still names the parameter, so CST rebuilds it too.
    assert solid["expressions"]["x1"] == "0.0+w"


def test_override_keeps_the_topology_but_changes_the_intent() -> None:
    """The pair of digests is the point: same device, different dimensions.

    An approval granted for a layout has to survive tuning its dimensions, which is what
    the topology hash is for, while a tuned board must not be filed as a reproduction of
    the one whose dimensions were published, which is what the intent id is for.
    """
    printed = ir.stamp(_tunable_model().build())
    tuned = ir.stamp(_tunable_model({"w": 1.5}).build())
    assert ir.topology_hash(printed) == ir.topology_hash(tuned)
    assert ir.model_intent_id(printed) != ir.model_intent_id(tuned)


def test_override_leaves_expressions_intact_so_cst_still_recomputes() -> None:
    document = _tunable_model({"w": 1.5}).build()
    derived = next(p for p in document["parameters"] if p["name"] == "w_half")
    assert derived["expression"] == "w/2.0"


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"w": 0.4}, "below the declared minimum"),
        ({"w": 2.1}, "above the declared maximum"),
        ({"h": 1.0}, "not declared tunable"),
        ({"w_half": 0.9}, "it is derived from"),
        ({"wdith": 1.5}, "parameters this model never declares"),
    ],
)
def test_override_refusals(overrides: dict, expected: str) -> None:
    with pytest.raises(ValueError, match=expected):
        _tunable_model(overrides).build()


def test_override_at_the_declared_boundary_is_allowed() -> None:
    """A range is closed, so the optimum is allowed to sit on its edge.

    Refusing the boundary would make the declared envelope quietly narrower than it
    reads, and an optimum found on the edge is a signal worth surfacing to a reviewer
    rather than an error worth hiding.
    """
    for value in (0.5, 2.0):
        values = {p["name"]: p["value"] for p in _tunable_model({"w": value}).build()["parameters"]}
        assert values["w"] == value


def test_no_overrides_reproduces_the_declared_defaults() -> None:
    assert _tunable_model().build() == _tunable_model({}).build()


# --------------------------------------------------------------------------- DRC


def test_min_spacing_passes_when_the_gap_meets_the_rule() -> None:
    document = two_net_model(gap=0.5)
    rule = {"id": "sp", "rule": "min_spacing", "scope": "layer:top", "severity": "error", "params": {"min_spacing": 0.5}}
    check = drc.run(document, [rule])["checks"][0]
    assert check["status"] == "pass"
    assert check["measured"] == pytest.approx(0.5)


def test_min_spacing_fails_and_localises_the_violation() -> None:
    document = two_net_model(gap=0.15)
    rule = {"id": "sp", "rule": "min_spacing", "scope": "layer:top", "severity": "error", "params": {"min_spacing": 0.5}}
    check = drc.run(document, [rule])["checks"][0]
    assert check["status"] == "fail"
    assert check["measured"] == pytest.approx(0.15)
    violation = check["violations"][0]
    assert {violation["a"], violation["b"]} == {"LEFT:trace", "RIGHT:trace"}
    assert violation["location"]["a"]["x0"] == pytest.approx(0.0)


def test_min_spacing_ignores_intentional_intra_net_gaps() -> None:
    document = two_net_model(gap=5.0, split=True)
    rule = {"id": "sp", "rule": "min_spacing", "scope": "layer:top", "severity": "error", "params": {"min_spacing": 2.0}}
    assert drc.run(document, [rule])["checks"][0]["status"] == "pass"


def test_min_width_measures_the_narrowest_feature() -> None:
    document = two_net_model(width=0.4)
    rule = {"id": "w", "rule": "min_width", "scope": "layer:top", "severity": "error", "params": {"min_width": 0.4}}
    check = drc.run(document, [rule])["checks"][0]
    assert check["status"] == "pass"
    assert check["measured"] == pytest.approx(0.4)

    strict = {**rule, "params": {"min_width": 0.6}}
    failed = drc.run(document, [strict])["checks"][0]
    assert failed["status"] == "fail"
    assert failed["violations"][0]["measured"] == pytest.approx(0.4)


def test_net_connectivity_passes_for_a_contiguous_net() -> None:
    document = two_net_model()
    rule = {"id": "c", "rule": "net_connectivity", "scope": "*", "severity": "error", "params": {"max_components": 1}}
    check = drc.run(document, [rule])["checks"][0]
    assert check["status"] == "pass"
    assert all(item["components"] == 1 for item in check["per_net"])


def test_net_connectivity_fails_for_a_detached_arm() -> None:
    document = two_net_model(split=True)
    rule = {"id": "c", "rule": "net_connectivity", "scope": "*", "severity": "error", "params": {"max_components": 1}}
    check = drc.run(document, [rule])["checks"][0]
    assert check["status"] == "fail"
    violation = check["violations"][0]
    assert violation["net"] == "LEFT"
    assert violation["measured"] == 2
    assert sorted(sorted(group) for group in violation["components"]) == [["arm"], ["trace"]]


def test_no_cross_net_short_passes_when_the_gap_is_open() -> None:
    document = two_net_model(bridge=False)
    rule = {"id": "s", "rule": "no_cross_net_short", "scope": "layer:top", "severity": "error", "params": {}}
    assert drc.run(document, [rule])["checks"][0]["status"] == "pass"


def test_no_cross_net_short_catches_a_metal_bridge() -> None:
    document = two_net_model(bridge=True)
    rule = {"id": "s", "rule": "no_cross_net_short", "scope": "layer:top", "severity": "error", "params": {}}
    check = drc.run(document, [rule])["checks"][0]
    assert check["status"] == "fail"
    assert {check["violations"][0]["net_a"], check["violations"][0]["net_b"]} == {"LEFT", "RIGHT"}


def test_board_containment_passes_inside_and_fails_outside() -> None:
    document = two_net_model()
    rule = {
        "id": "b",
        "rule": "board_containment",
        "scope": "layer:top",
        "severity": "error",
        "params": {"reference_net": "BOARD"},
    }
    assert drc.run(document, [rule])["checks"][0]["status"] == "pass"

    escaped = copy.deepcopy(document)
    solid = next(s for net in escaped["nets"] if net["name"] == "RIGHT" for s in net["solids"])
    solid["box"]["x1"] = 99.0
    check = drc.run(escaped, [rule])["checks"][0]
    assert check["status"] == "fail"
    assert check["violations"][0]["measured"] < 0


def test_port_attachment_passes_when_touching_and_fails_when_floating() -> None:
    document = two_net_model()
    rule = {"id": "p", "rule": "port_attachment", "scope": "port:*", "severity": "error", "params": {"tolerance": 1e-6}}
    assert drc.run(document, [rule])["checks"][0]["status"] == "pass"

    floating = copy.deepcopy(document)
    for key in ("y0", "y1"):
        floating["ports"][0]["extent"][key] -= 5.0
    check = drc.run(floating, [rule])["checks"][0]
    assert check["status"] == "fail"


def test_symmetry_rule_detects_a_broken_mirror() -> None:
    model = ModelBuilder(model_id="sym")
    model.units()
    model.material("PEC", kind="pec")
    model.layer("top", 0.0, 0.1, "PEC", role="signal")
    net = model.net("A", "top")
    net.rect(-3.0, 0.0, 1.0, 1.0, solid_id="left")
    net.rect(2.0, 0.0, 1.0, 1.0, solid_id="right")
    document = model.build()
    rule = {"id": "m", "rule": "symmetry", "scope": "*", "severity": "error", "params": {"axis": "x", "position": 0.0}}
    assert drc.run(document, [rule])["checks"][0]["status"] == "pass"

    broken = copy.deepcopy(document)
    solid = next(s for s in broken["nets"][0]["solids"] if s["id"] == "right")
    solid["box"]["x0"] += 0.5
    solid["box"]["x1"] += 0.5
    assert drc.run(broken, [rule])["checks"][0]["status"] == "fail"


def test_unknown_rule_is_reported_not_swallowed() -> None:
    document = two_net_model()
    rule = {"id": "x", "rule": "teleportation", "scope": "*", "severity": "error"}
    check = drc.run(document, [rule])["checks"][0]
    assert check["status"] == "error"
    assert "teleportation" in check["message"]


def test_drc_report_is_deterministic(cad_fixture: dict) -> None:
    first = json.dumps(drc.run(cad_fixture), sort_keys=True)
    second = json.dumps(drc.run(cad_fixture), sort_keys=True)
    assert first == second


def test_cad_fixture_drc_passes_every_rule(cad_fixture: dict) -> None:
    report = drc.run(cad_fixture)
    assert report["status"] == "pass", [check for check in report["checks"] if check["status"] != "pass"]
    assert report["summary"]["shapes_unsupported"] == 0


def test_ring_min_width_of_a_rectangle_is_its_short_side() -> None:
    assert drc.ring_min_width([(0, 0), (10, 0), (10, 2), (0, 2)]) == pytest.approx(2.0)


def test_ring_distance_is_zero_for_touching_rectangles() -> None:
    a = [(0, 0), (1, 0), (1, 1), (0, 1)]
    b = [(1, 0), (2, 0), (2, 1), (1, 1)]
    assert drc.ring_distance(a, b) == pytest.approx(0.0)
    c = [(1.5, 0), (2, 0), (2, 1), (1.5, 1)]
    assert drc.ring_distance(a, c) == pytest.approx(0.5)


# ---------------------------------------------------------------- VBA generation


def test_vba_generation_is_byte_identical_for_the_same_ir(cad_fixture: dict) -> None:
    assert emit_vba.emit(cad_fixture) == emit_vba.emit(copy.deepcopy(cad_fixture))


def test_vba_generation_is_independent_of_declaration_order(cad_fixture: dict) -> None:
    shuffled = copy.deepcopy(cad_fixture)
    shuffled["nets"] = list(reversed(shuffled["nets"]))
    for net in shuffled["nets"]:
        net["solids"] = list(reversed(net["solids"]))
    shuffled["parameters"] = list(reversed(shuffled["parameters"]))
    assert emit_vba.emit(shuffled) == emit_vba.emit(cad_fixture)


def test_parameters_are_emitted_in_dependency_order(cad_fixture: dict) -> None:
    ordered = [item["name"] for item in emit_vba.parameter_order(cad_fixture["parameters"])]
    positions = {name: index for index, name in enumerate(ordered)}
    for parameter in cad_fixture["parameters"]:
        expression = parameter.get("expression")
        if not expression:
            continue
        for token in emit_vba._IDENTIFIER.findall(expression):
            if token in positions and token != parameter["name"]:
                assert positions[token] < positions[parameter["name"]], (
                    f"{parameter['name']} is emitted before its dependency {token}"
                )


def test_parameters_use_make_sure_parameter_exists(cad_fixture: dict) -> None:
    block = next(block for block in emit_vba.build_blocks(cad_fixture) if block.title == "parameters")
    assert "StoreParameter" not in block.code
    assert block.code.count("MakeSureParameterExists") == len(cad_fixture["parameters"])


def test_merge_order_never_adds_a_detached_primitive(cad_fixture: dict) -> None:
    net = next(net for net in cad_fixture["nets"] if net["name"] == "RESONATOR_1")
    ordered = emit_vba.merge_order(net)
    assert [solid["id"] for solid in ordered][0] == sorted(s["id"] for s in net["solids"])[0]
    accumulated = [ir.footprint(ordered[0])]
    for solid in ordered[1:]:
        ring = ir.footprint(solid)
        assert any(drc.ring_distance(ring, other) <= drc.EPS for other in accumulated), solid["id"]
        accumulated.append(ring)


def test_each_net_becomes_exactly_one_named_body(cad_fixture: dict) -> None:
    entities = emit_vba.expected_entities(cad_fixture)
    assert len(entities) == len(cad_fixture["nets"])
    assert {entity["full_name"] for entity in entities} == {
        f"net_{net['name']}:net_{net['name']}_body" for net in cad_fixture["nets"]
    }


def test_every_primitive_is_created_and_merged(cad_fixture: dict) -> None:
    for net in cad_fixture["nets"]:
        block = next(b for b in emit_vba.build_blocks(cad_fixture) if b.title == f"net {net['name']}")
        for solid in net["solids"]:
            assert f'.Name "net_{net["name"]}_{solid["id"]}"' in block.code
        assert block.code.count("Solid.Add ") == len(net["solids"]) - 1
        assert f'Solid.Rename' in block.code


def test_reserved_primitive_kinds_fail_loudly_rather_than_silently() -> None:
    document = two_net_model()
    document["nets"][1]["solids"][0] = {
        "id": "cyl",
        "kind": "cylinder",
        "cylinder": {"axis": "z", "outer_radius": 1.0, "center": [0.0, 0.0], "from": 0.0, "to": 1.0},
    }
    with pytest.raises(NotImplementedError):
        emit_vba.emit(ir.stamp(document))


def test_vba_strings_are_escaped() -> None:
    assert emit_vba.escape('a"b') == 'a""b'


def test_solver_block_carries_convergence_not_the_mesh_block(cad_fixture: dict) -> None:
    blocks = {block.title: block.code for block in emit_vba.build_blocks(cad_fixture)}
    assert "MeshAdaption3D" in blocks["solver"]
    assert "MeshAdaption3D" not in blocks["mesh"]


@pytest.mark.parametrize("adaptive", [True, False])
def test_fd_setup_replaces_old_adaptation_switch_and_intervals(cad_fixture, adaptive):
    document = copy.deepcopy(cad_fixture)
    document["simulation"]["convergence"]["adaptive_mesh"] = adaptive
    code = {b.title: b.code for b in emit_vba.build_blocks(document)}["solver"]
    flag = "True" if adaptive else "False"
    assert f'.MeshAdaptionTet "{flag}"' in code
    assert code.index('.ResetSampleIntervals "all"') < code.index('.AddSampleInterval')
    assert f'"Single", "{flag}"' in code


def test_td_setup_explicitly_disables_previous_adaptation(cad_fixture):
    document = copy.deepcopy(cad_fixture)
    document["simulation"]["solver"] = "time_domain"
    document["simulation"]["convergence"]["adaptive_mesh"] = False
    code = {b.title: b.code for b in emit_vba.build_blocks(document)}["solver"]
    assert '.MeshAdaption "False"' in code


def test_clockwise_profile_is_reversed_together_with_its_expressions():
    import re
    m = ModelBuilder(model_id='winding', title='Winding')
    m.units(length='mm', frequency='GHz'); m.material('PEC', kind='pec')
    m.layer('top', -.035, 0, 'PEC')
    x = m.param('x', 2.)
    m.net('CW','top').polygon([(0,0),(0,1),(x,1),(x,0)],solid_id='cw')
    doc=m.build()
    code={b.title:b.code for b in emit_vba.build_blocks(doc)}['net CW']
    points=re.findall(r'\.Point "([^"]+)", "([^"]+)", "([^"]+)"',code)
    assert [p[:2] for p in points]==[('0.0','0.0'),('x','0.0'),('x','1.0'),('0.0','1.0'),('0.0','0.0')]
    assert all(float(p[2])==-.035 for p in points)
    assert '.Thickness "(0.0)-(-0.035)"' in code


def test_union_drc_scope_checks_shorts_across_two_signal_layers():
    m = ModelBuilder(model_id='cross-layer',title='Touching conductor planes')
    m.material('PEC',kind='pec');m.layer('top',0,.035,'PEC');m.layer('inset',-.035,0,'PEC')
    m.net('A','top').box(0,0,2,2);m.net('B','inset').box(1,1,3,3)
    m.rule('short','no_cross_net_short','layer:top|layer:inset')
    assert drc.run(m.build())['status']=='fail'


def test_a_net_local_refinement_is_refused_offline(cad_fixture: dict) -> None:
    """The emitter must not produce a command nobody has watched CST accept.

    It used to emit ``MeshSettings.SetSolidMeshStepWidthTet``, which CST 2026
    rejects -- in a modal that stalls the entire history injection until a human
    dismisses it. No IR in the repository set ``local_refinements``, so the path was
    never executed until a four-port model needed it.
    """
    document = copy.deepcopy(cad_fixture)
    document["mesh_hints"]["local_refinements"] = [{"target": "net:SOURCE_FEED", "max_step": 0.4}]
    with pytest.raises(NotImplementedError) as raised:
        emit_vba.build_blocks(document)
    assert "net:SOURCE_FEED" in str(raised.value)
    assert "SetSolidMeshStepWidthTet" not in emit_vba.emit(cad_fixture)


def test_a_non_net_local_refinement_still_emits(cad_fixture: dict) -> None:
    """Only net-scoped hints were ever emitted, so only they are refused."""
    document = copy.deepcopy(cad_fixture)
    document["mesh_hints"]["local_refinements"] = [{"target": "solid:probe", "max_step": 0.4}]
    blocks = {block.title: block.code for block in emit_vba.build_blocks(document)}
    assert "MeshSettings" in blocks["mesh"]


# ------------------------------------------------------------------------ verify


def test_verify_reports_a_match_for_a_synthetic_perfect_observation(cad_fixture: dict) -> None:
    from cst_cad import verify

    observation = {
        "project_path": "synthetic",
        "entities": [
            {
                "component": entity["component"],
                "name": entity["name"],
                "bounding_box": entity["bounding_box"],
            }
            for entity in emit_vba.expected_entities(cad_fixture)
        ],
        "parameters": {item["name"]: item["value"] for item in cad_fixture["parameters"]},
    }
    report = verify.compare(cad_fixture, verify.normalize_observation(observation))
    assert report["status"] == "match"
    assert report["summary"]["entities_missing"] == 0


def test_verify_flags_a_moved_solid(cad_fixture: dict) -> None:
    from cst_cad import verify

    entities = emit_vba.expected_entities(cad_fixture)
    entities[0]["bounding_box"]["x0"] += 0.01
    observation = {
        "entities": [
            {"component": e["component"], "name": e["name"], "bounding_box": e["bounding_box"]} for e in entities
        ],
        "parameters": {item["name"]: item["value"] for item in cad_fixture["parameters"]},
    }
    report = verify.compare(cad_fixture, verify.normalize_observation(observation))
    assert report["status"] == "mismatch"
    assert report["summary"]["entities_bounding_box_mismatch"] == 1


def test_sanitize_name_strips_the_cst_buffer_garbage() -> None:
    from cst_cad.verify import sanitize_name

    assert sanitize_name("FeedLoad:probe\x00   $\x01\x02junk") == "FeedLoad:probe"
    assert sanitize_name("  clean_name  ") == "clean_name"


# -------------------------------------------------------------------------- diff


def test_diff_is_empty_for_identical_documents(cad_fixture: dict) -> None:
    report = ir.diff(cad_fixture, copy.deepcopy(cad_fixture))
    assert report["difference_count"] == 0
    assert report["identical_intent"] is True


def test_diff_localises_a_single_moved_dimension(cad_fixture: dict) -> None:
    moved = ir.stamp({**copy.deepcopy(cad_fixture)})
    moved["nets"][0]["solids"][0]["box"]["x0"] += 0.25
    report = ir.diff(cad_fixture, moved)
    assert report["difference_count"] >= 1
    assert any(entry["path"].endswith("box.x0") and entry["delta"] == pytest.approx(0.25) for entry in report["differences"])


# ------------------------------------------------------------- cad_fixture integration


def test_cad_fixture_model_script_is_reproducible(cad_fixture: dict) -> None:
    from cst_cad.cli import load_model_script

    rebuilt = load_model_script(str(PUBLIC_CAD_MODEL))
    assert rebuilt["model_intent_id"] == cad_fixture["model_intent_id"]


def test_public_fixture_matches_frozen_geometry() -> None:
    """A public specification baseline, independent of external topic files."""
    from cst_cad.cli import load_model_script

    expected = json.loads(PUBLIC_CAD_IR.read_text(encoding="utf-8"))
    rebuilt = load_model_script(str(PUBLIC_CAD_MODEL))
    assert rebuilt == expected
    assert ir.diff(expected, rebuilt)["difference_count"] == 0


def test_cad_fixture_parameter_provenance_is_fully_declared(cad_fixture: dict) -> None:
    counts = ir.provenance_summary(cad_fixture)
    assert counts["synthesized"] > 0
    assert counts["assumption"] > 0
    assert sum(counts.values()) == len(cad_fixture["parameters"])
    assert all(
        parameter.get("source") for parameter in cad_fixture["parameters"]
        if parameter["provenance"] != "synthesized"
    )
