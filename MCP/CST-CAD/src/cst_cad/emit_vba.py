"""Deterministic geometry IR to CST History/VBA code generation.

Every block is small, named and idempotent so it can be injected one at a time
through ``add_to_history`` and checked against the CST message log before the
next one, which is what ``$cst-vba-modeling`` requires. The same IR always
produces byte-identical VBA: collections are emitted in the same canonical
order that ``ir.canonical_text`` uses for identity, so emission order cannot
drift from model identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from . import ir

#: Predefined CST materials that must not be re-created.
BUILTIN_MATERIALS = {"PEC", "Vacuum"}


@dataclass(frozen=True)
class Block:
    """One named CST history block."""

    index: int
    title: str
    code: str

    @property
    def caption(self) -> str:
        return f"{self.index:02d} {self.title}"


def escape(text: str) -> str:
    return str(text).replace('"', '""')


def number(value: float | int) -> str:
    return ir.canonical_number(value)


def _dimension(solid: dict[str, Any], key: str, fallback: float) -> str:
    """Prefer the CST parameter expression so the emitted model stays sweepable."""
    expressions = solid.get("expressions") or {}
    if key in expressions:
        return escape(str(expressions[key]))
    return number(fallback)


def component_name(net_name: str) -> str:
    return f"net_{net_name}"


def solid_name(net_name: str, solid_id: str) -> str:
    return f"net_{net_name}_{solid_id}"


def body_name(net_name: str) -> str:
    return f"net_{net_name}_body"


def full_name(net_name: str, solid_id: str) -> str:
    return f"{component_name(net_name)}:{solid_name(net_name, solid_id)}"


def body_full_name(net_name: str) -> str:
    return f"{component_name(net_name)}:{body_name(net_name)}"


def _sorted_nets(document: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(document.get("nets", []), key=lambda net: str(net["name"]))


def _sorted_solids(net: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(net.get("solids", []), key=lambda solid: str(solid["id"]))


# ------------------------------------------------------------------- sections


def _units_block(document: dict[str, Any]) -> str:
    units = document["units"]
    lines = [
        "With Units",
        f'    .Geometry "{escape(units["length"])}"',
        f'    .Frequency "{escape(units["frequency"])}"',
    ]
    if units.get("time"):
        lines.append(f'    .Time "{escape(units["time"])}"')
    if units.get("temperature"):
        lines.append(f'    .TemperatureUnit "{escape(units["temperature"])}"')
    lines += [
        '    .Current "A"',
        '    .Conductance "Siemens"',
        '    .Capacitance "PikoF"',
        "End With",
    ]
    return "\n".join(lines)


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def parameter_order(parameters: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order parameters so every expression only references earlier ones.

    CST evaluates a parameter as soon as it is defined, so emitting them
    alphabetically would reference names that do not exist yet. This is a
    Kahn topological sort whose ready set is drained alphabetically, which
    keeps the output deterministic while satisfying the dependencies.
    """
    by_name = {str(item["name"]): item for item in parameters}
    dependencies: dict[str, set[str]] = {}
    for name, parameter in by_name.items():
        expression = parameter.get("expression")
        found = set(_IDENTIFIER.findall(expression)) & set(by_name) if expression else set()
        dependencies[name] = found - {name}

    ordered: list[dict[str, Any]] = []
    resolved: set[str] = set()
    pending = set(by_name)
    while pending:
        ready = sorted(name for name in pending if dependencies[name] <= resolved)
        if not ready:
            # A dependency cycle cannot be expressed in CST; emit the rest
            # alphabetically so the failure surfaces in the CST log, not here.
            ready = sorted(pending)
        for name in ready:
            ordered.append(by_name[name])
            resolved.add(name)
            pending.discard(name)
    return ordered


def _parameters_block(document: dict[str, Any]) -> str:
    lines: list[str] = []
    for parameter in parameter_order(document.get("parameters", [])):
        # MakeSureParameterExists is the only safe way to define a parameter from
        # inside the history tree; changing a value with StoreParameter during a
        # rebuild is rejected by CST with a "Prevented attempt to change the
        # value ... inside history rebuild" warning.
        definition = parameter.get("expression") or number(parameter["value"])
        lines.append(f'MakeSureParameterExists "{escape(parameter["name"])}", "{escape(definition)}"')
    return "\n".join(lines)


def _material_block(material: dict[str, Any]) -> str:
    lines = ["With Material", "    .Reset", f'    .Name "{escape(material["name"])}"', '    .Folder ""']
    kind = material.get("kind", "normal")
    if kind == "lossy_metal":
        lines.append('    .Type "Lossy metal"')
        if material.get("mu") is not None:
            lines.append(f'    .Mue "{escape(material["mu"])}"')
        if material.get("conductivity") is not None:
            lines.append(f'    .Kappa "{escape(material["conductivity"])}"')
    else:
        lines.append('    .Type "Normal"')
        if material.get("epsilon") is not None:
            lines.append(f'    .Epsilon "{escape(material["epsilon"])}"')
        if material.get("mu") is not None:
            lines.append(f'    .Mue "{escape(material["mu"])}"')
        if material.get("tan_delta") is not None:
            lines.append(f'    .TanD "{escape(material["tan_delta"])}"')
        if material.get("conductivity") is not None:
            lines.append(f'    .Kappa "{escape(material["conductivity"])}"')
    lines += ["    .Create", "End With"]
    return "\n".join(lines)


def _materials_block(document: dict[str, Any]) -> str:
    chunks = [
        _material_block(material)
        for material in sorted(document.get("materials", []), key=lambda item: str(item["name"]))
        if material["name"] not in BUILTIN_MATERIALS and material.get("kind") != "pec"
    ]
    return "\n\n".join(chunks)


def _brick(net: dict[str, Any], solid: dict[str, Any], material: str) -> str:
    box = solid["box"]
    return "\n".join(
        [
            "With Brick",
            "    .Reset",
            f'    .Name "{escape(solid_name(net["name"], solid["id"]))}"',
            f'    .Component "{escape(component_name(net["name"]))}"',
            f'    .Material "{escape(material)}"',
            f'    .Xrange "{_dimension(solid, "x0", box["x0"])}", "{_dimension(solid, "x1", box["x1"])}"',
            f'    .Yrange "{_dimension(solid, "y0", box["y0"])}", "{_dimension(solid, "y1", box["y1"])}"',
            f'    .Zrange "{_dimension(solid, "z0", box["z0"])}", "{_dimension(solid, "z1", box["z1"])}"',
            "    .Create",
            "End With",
        ]
    )


def _extrude_polygon(net: dict[str, Any], solid: dict[str, Any], material: str) -> str:
    shape = solid["extrude_polygon"]
    expressions = solid.get("expressions") or {}
    curve_folder = "cad_curves"
    curve = f"curve_{solid_name(net['name'], solid['id'])}"
    z0 = expressions.get("z0", number(shape["z0"]))
    thickness = number(float(shape["z1"]) - float(shape["z0"]))
    if "z0" in expressions and "z1" in expressions:
        thickness = f'({expressions["z1"]})-({expressions["z0"]})'

    lines = ["With Polygon3D", "    .Reset", f'    .Name "{escape(curve)}"', f'    .Curve "{escape(curve_folder)}"']
    points = shape["points"]
    area2 = sum(x * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * y
                for i, (x, y) in enumerate(points))
    if abs(area2) <= 1e-12:
        raise ValueError("cannot extrude a polygon with zero signed area")
    # CST extrudes along the profile normal. IR z0/z1 are world coordinates,
    # independent of winding; a clockwise profile would otherwise go below z0.
    # Reverse the traversal, including expression indices, keeping the first point.
    order = list(range(len(points))) if area2 > 0 else [0, *range(len(points) - 1, 0, -1)]
    for index in order:
        x, y = points[index]
        px = expressions.get(f"p{index}x", number(x))
        py = expressions.get(f"p{index}y", number(y))
        lines.append(f'    .Point "{escape(px)}", "{escape(py)}", "{escape(z0)}"')
    first_x = expressions.get("p0x", number(shape["points"][0][0]))
    first_y = expressions.get("p0y", number(shape["points"][0][1]))
    lines.append(f'    .Point "{escape(first_x)}", "{escape(first_y)}", "{escape(z0)}"')
    lines += ["    .Create", "End With"]

    lines += [
        "With ExtrudeCurve",
        "    .Reset",
        f'    .Name "{escape(solid_name(net["name"], solid["id"]))}"',
        f'    .Component "{escape(component_name(net["name"]))}"',
        f'    .Material "{escape(material)}"',
        f'    .Thickness "{escape(thickness)}"',
        '    .Twistangle "0.0"',
        '    .Taperangle "0.0"',
        '    .DeleteProfile "True"',
        f'    .Curve "{escape(curve_folder)}:{escape(curve)}"',
        "    .Create",
        "End With",
    ]
    return "\n".join(lines)


def merge_order(net: dict[str, Any]) -> list[dict[str, Any]]:
    """Order primitives so each Boolean add joins something already present.

    The survivor is always the canonically first primitive, so the final entity
    name never depends on this ordering. Within that constraint we repeatedly
    take the canonically smallest remaining primitive that touches what has
    been merged so far, which keeps CST from ever holding a multi-lump
    intermediate solid. When nothing touches (a genuinely disconnected net) we
    fall back to canonical order so the output stays deterministic.
    """
    from .drc import EPS, ring_distance

    solids = _sorted_solids(net)
    if len(solids) <= 2:
        return solids

    rings = {solid["id"]: ir.footprint(solid) for solid in solids}
    ordered = [solids[0]]
    remaining = solids[1:]
    accumulated = [rings[solids[0]["id"]]]
    while remaining:
        chosen_index = 0
        for index, candidate in enumerate(remaining):
            ring = rings[candidate["id"]]
            if ring is None:
                continue
            if any(other is not None and ring_distance(ring, other) <= EPS for other in accumulated):
                chosen_index = index
                break
        chosen = remaining.pop(chosen_index)
        ordered.append(chosen)
        accumulated.append(rings[chosen["id"]])
    return ordered


def _net_block(document: dict[str, Any], net: dict[str, Any]) -> str:
    solids = _sorted_solids(net)
    chunks: list[str] = []
    for solid in solids:
        material = ir.solid_material(document, net, solid)
        kind = solid["kind"]
        if kind == "box":
            chunks.append(_brick(net, solid, material))
        elif kind == "extrude_polygon":
            chunks.append(_extrude_polygon(net, solid, material))
        else:
            raise NotImplementedError(
                f"primitive kind {kind!r} is reserved in the schema but not emitted by the Phase 1 VBA backend"
            )

    merge: list[str] = []
    ordered = merge_order(net)
    survivor = full_name(net["name"], ordered[0]["id"])
    for solid in ordered[1:]:
        merge.append(f'Solid.Add "{escape(survivor)}", "{escape(full_name(net["name"], solid["id"]))}"')
    merge.append(f'Solid.Rename "{escape(survivor)}", "{escape(body_name(net["name"]))}"')

    color = net.get("color")
    if color:
        target = body_full_name(net["name"])
        merge.append(f'Solid.SetUseIndividualColor "{escape(target)}", 1')
        merge.append(
            f'Solid.ChangeIndividualColor "{escape(target)}", "{color[0]}", "{color[1]}", "{color[2]}"'
        )

    report = (
        f'ReportInformation "CST-CAD net {escape(net["name"])}: '
        f'{len(solids)} primitives merged into {escape(body_name(net["name"]))}"'
    )
    return "\n\n".join(chunks + ["\n".join(merge), report])


def _ports_block(document: dict[str, Any]) -> str:
    chunks: list[str] = []
    for port in sorted(document.get("ports", []), key=lambda item: (int(item["number"]), str(item["name"]))):
        extent = port["extent"]
        expressions = port.get("expressions") or {}

        def bound(key: str) -> str:
            if key in expressions:
                return escape(str(expressions[key]))
            return number(extent[key])

        axis, side = port["orientation"][0], port["orientation"][1:]
        # A boundary port collapses to a plane on its own axis.
        if side == "min":
            x_range = (bound("x0"), bound("x0")) if axis == "x" else (bound("x0"), bound("x1"))
            y_range = (bound("y0"), bound("y0")) if axis == "y" else (bound("y0"), bound("y1"))
            z_range = (bound("z0"), bound("z0")) if axis == "z" else (bound("z0"), bound("z1"))
        else:
            x_range = (bound("x1"), bound("x1")) if axis == "x" else (bound("x0"), bound("x1"))
            y_range = (bound("y1"), bound("y1")) if axis == "y" else (bound("y0"), bound("y1"))
            z_range = (bound("z1"), bound("z1")) if axis == "z" else (bound("z0"), bound("z1"))

        lines = [
            "With Port",
            "    .Reset",
            f'    .PortNumber "{int(port["number"])}"',
            f'    .Label "{escape(port.get("label") or port["name"])}"',
            '    .Folder ""',
            f'    .NumberOfModes "{int(port.get("modes", 1))}"',
            '    .AdjustPolarization "False"',
            '    .PolarizationAngle "0"',
            '    .ReferencePlaneDistance "0"',
            '    .TextSize "50"',
            '    .TextMaxLimit "1"',
            '    .Coordinates "Free"',
            f'    .Orientation "{escape(port["orientation"])}"',
            f'    .PortOnBound "{"True" if port.get("on_boundary", True) else "False"}"',
            '    .ClipPickedPortToBound "False"',
            f'    .Xrange "{x_range[0]}", "{x_range[1]}"',
            f'    .Yrange "{y_range[0]}", "{y_range[1]}"',
            f'    .Zrange "{z_range[0]}", "{z_range[1]}"',
            '    .XrangeAdd "0", "0"',
            '    .YrangeAdd "0", "0"',
            '    .ZrangeAdd "0", "0"',
            '    .SingleEnded "False"',
            '    .WaveguideMonitor "False"',
            "    .Create",
            "End With",
        ]
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)


def _boundaries_block(document: dict[str, Any]) -> str:
    boundaries = document.get("boundaries", {})
    if not boundaries:
        return ""
    lines = ["With Boundary"]
    for face in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"):
        if boundaries.get(face):
            lines.append(f'    .{face.capitalize()} "{escape(boundaries[face])}"')
    symmetry = boundaries.get("symmetry", {})
    for axis in ("x", "y", "z"):
        if symmetry.get(axis):
            lines.append(f'    .{axis.upper()}symmetry "{escape(symmetry[axis])}"')
    lines.append("End With")

    open_space = boundaries.get("open_space")
    if open_space:
        lines += ["", "With Background", "    .ResetBackground"]
        for face in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"):
            if face in open_space:
                value = open_space[face]
                rendered = escape(value) if isinstance(value, str) else number(value)
                lines.append(f'    .{face[0].upper()}{face[1:]}Space "{rendered}"')
        lines += ['    .ApplyInAllDirections "False"', "End With"]
    return "\n".join(lines)


def _mesh_block(document: dict[str, Any]) -> str:
    hints = document.get("mesh_hints", {})
    if not hints:
        return ""
    mesh_type = {"tetrahedral": "Tet", "hexahedral": "Hex", "surface": "Surface"}[hints.get("kind", "tetrahedral")]
    lines = ['Mesh.SetCreator "High Frequency"', "With MeshSettings", f'    .SetMeshType "{mesh_type}"']
    if hints.get("steps_per_wavelength_near") is not None:
        # CST 2026.2 accepts this policy for tetrahedra but rejects it for Hex.
        if mesh_type == "Tet":
            lines.append('    .Set "CellsPerWavelengthPolicy", "cellsperwavelength"')
        lines.append(f'    .Set "StepsPerWaveNear", "{number(hints["steps_per_wavelength_near"])}"')
    if hints.get("cells_per_max_cell_near") is not None:
        lines.append(f'    .Set "StepsPerBoxNear", "{number(hints["cells_per_max_cell_near"])}"')
    lines.append("End With")

    refinements = [
        item
        for item in sorted(hints.get("local_refinements", []), key=lambda item: str(item["target"]))
        if str(item["target"]).partition(":")[0] == "net"
    ]
    if refinements:
        # This block used to emit ``MeshSettings.SetSolidMeshStepWidthTet``, which
        # CST Studio Suite 2026 rejects with "(10091) ActiveX Automation: no such
        # property or method" -- and it rejects it in a Qt modal that stalls the
        # whole history injection until somebody dismisses it by hand. No IR in the
        # repository had ever set local_refinements, so nothing caught it.
        #
        # Failing here, offline, is the honest replacement: an emitter must not
        # produce a command nobody has watched CST accept. Adaptive tetrahedral
        # refinement under ``simulation.convergence`` covers the same need, so
        # until the correct per-solid call is confirmed against a live CST, the
        # right answer for a caller is to drop the hint rather than trust it.
        targets = ", ".join(str(item["target"]) for item in refinements)
        raise NotImplementedError(
            "mesh_hints.local_refinements cannot be emitted: the per-solid tetrahedral "
            f"step command has not been verified against CST 2026 (targets: {targets}). "
            "Use simulation.convergence adaptive refinement instead."
        )
    return "\n".join(lines)


_SOLVER_TYPE = {
    "frequency_domain": "HF Frequency Domain",
    "time_domain": "HF Time Domain",
    "eigenmode": "HF Eigenmode",
    "integral": "HF IntegralEq",
}


def _solver_block(document: dict[str, Any]) -> str:
    simulation = document.get("simulation") or {}
    if not simulation:
        return ""
    solver = simulation.get("solver", "frequency_domain")
    settings = simulation.get("settings") or {}
    frequency = simulation.get("frequency") or {}
    lines = [f'ChangeSolverType "{escape(_SOLVER_TYPE[solver])}"']

    def render(value: Any) -> str:
        return escape(value) if isinstance(value, str) else number(value)

    if "min" in frequency and "max" in frequency:
        lines.append(f'Solver.FrequencyRange "{render(frequency["min"])}", "{render(frequency["max"])}"')

    # Adaptive refinement is a convergence control, so it is emitted with the
    # solver rather than with the geometry-tied mesh hints.
    convergence = simulation.get("convergence") or {}
    if convergence.get("adaptive_mesh"):
        mesh_kind = (document.get("mesh_hints") or {}).get("kind", "tetrahedral")
        lines += [
            "With MeshAdaption3D",
            f'    .SetType "{"HighFrequencyTet" if mesh_kind == "tetrahedral" else "HighFrequencyHex"}"',
            f'    .MinPasses "{int(convergence.get("min_passes", 3))}"',
            f'    .MaxPasses "{int(convergence.get("max_passes", 8))}"',
            f'    .MeshIncrement "{number(convergence.get("increment_percent", 5))}"',
            f'    .MaxDeltaS "{number(convergence.get("max_delta_s", 0.01))}"',
            f'    .NumberOfDeltaSChecks "{int(convergence.get("checks", 2))}"',
            "End With",
        ]

    if solver == "frequency_domain":
        lines += [
            "With FDSolver",
            f'    .SetMethod "{escape(settings.get("method", "Tetrahedral"))}", "{escape(settings.get("method_variant", "Fast reduced order model"))}"',
            f'    .OrderTet "{escape(settings.get("order_tet", "Second"))}"',
            f'    .OrderSrf "{escape(settings.get("order_srf", "First"))}"',
            '    .Stimulation "All", "All"',
            '    .AutoNormImpedance "False"',
            f'    .NormingImpedance "{number(settings.get("norming_impedance", 50))}"',
            '    .ConsiderPortLossesTet "True"',
            f'    .AccuracyTet "{escape(settings.get("accuracy_tet", "1e-6"))}"',
            f'    .AccuracyROM "{escape(settings.get("accuracy_rom", "1e-5"))}"',
            f'    .SetNumberOfResultDataSamples "{int(settings.get("result_samples", 801))}"',
            '    .SetResultDataSamplingMode "Automatic"',
        ]
        if "adaptive_mesh" in convergence:
            # The adaptation limits do not enable/disable the solver's switch.
            # Set it in both directions so a parent project's state cannot leak
            # into a setup-only iteration (CST 2026 FDSolver object reference).
            enabled = "True" if convergence["adaptive_mesh"] else "False"
            method = settings.get("method", "Tetrahedral")
            lines.append(f'    .{"MeshAdaptionTet" if method == "Tetrahedral" else "MeshAdaptionHex"} "{enabled}"')
            # These are the complete sampling settings, not an addition to a
            # previous iteration's intervals. Keep the default broadband sweep;
            # the single interval below specifies the adaptation frequency.
            lines.append('    .ResetSampleIntervals "all"')
        if frequency.get("center") is not None:
            centre = render(frequency["center"])
            adaptation = "True" if convergence.get("adaptive_mesh", True) else "False"
            lines.append(f'    .AddSampleInterval "{centre}", "{centre}", "1", "Single", "{adaptation}"')
        lines += [f'    .StoreAllResults "{"True" if settings.get("store_all_results", True) else "False"}"', "End With"]
    elif solver == "time_domain":
        lines += [
            "With Solver",
            '    .Method "Hexahedral"',
            '    .CalculationType "TD-S"',
            f'    .SteadyStateLimit "{escape(settings.get("accuracy_db", "-40"))}"',
            f'    .AutoNormImpedance "{"True" if settings.get("auto_norm_impedance", True) else "False"}"',
            f'    .NormingImpedance "{number(settings.get("norming_impedance", 50))}"',
            '    .StimulationPort "All"',
            '    .StimulationMode "All"',
        ]
        if "adaptive_mesh" in convergence:
            lines.append(f'    .MeshAdaption "{"True" if convergence["adaptive_mesh"] else "False"}"')
        lines.append("End With")
    return "\n".join(lines)


def _monitors_block(document: dict[str, Any]) -> str:
    monitors = (document.get("simulation") or {}).get("monitors") or []
    chunks = []
    for monitor in sorted(monitors, key=lambda item: str(item["name"])):
        lines = [
            "With Monitor",
            "    .Reset",
            f'    .Name "{escape(monitor["name"])}"',
            f'    .FieldType "{escape(monitor["kind"])}"',
        ]
        if monitor.get("frequency") is not None:
            value = monitor["frequency"]
            lines.append(f'    .Frequency "{escape(value) if isinstance(value, str) else number(value)}"')
        lines += ["    .Create", "End With"]
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)


# ---------------------------------------------------------------------- public


def build_blocks(document: dict[str, Any]) -> list[Block]:
    """Return the ordered, named history blocks for an IR document."""
    sections: list[tuple[str, str]] = [
        ("units", _units_block(document)),
        ("parameters", _parameters_block(document)),
        ("materials", _materials_block(document)),
    ]
    for net in _sorted_nets(document):
        sections.append((f"net {net['name']}", _net_block(document, net)))
    sections += [
        ("ports", _ports_block(document)),
        ("boundaries and background", _boundaries_block(document)),
        ("mesh", _mesh_block(document)),
        ("solver", _solver_block(document)),
        ("monitors", _monitors_block(document)),
    ]

    blocks: list[Block] = []
    for title, code in sections:
        if not code.strip():
            continue
        blocks.append(Block(index=len(blocks) + 1, title=title, code=code.rstrip() + "\n"))
    return blocks


def emit(document: dict[str, Any]) -> str:
    """Return the full VBA bundle as a single reviewable text document."""
    header = [
        "' Generated by cst-cad emit_vba. Do not edit by hand.",
        f"' model_id        : {document.get('model_id')}",
        f"' model_intent_id : {document.get('model_intent_id')}",
        f"' blocks          : {len(build_blocks(document))}",
        "",
    ]
    chunks = list(header)
    for block in build_blocks(document):
        chunks += [
            "'" + "=" * 70,
            f"' BLOCK {block.caption}",
            "'" + "=" * 70,
            block.code.rstrip(),
            "",
        ]
    return "\n".join(chunks) + "\n"


def write_blocks(document: dict[str, Any], directory: str | Path) -> dict[str, Any]:
    """Write one .vba file per block plus a combined bundle, and index them."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    blocks = build_blocks(document)
    entries = []
    for block in blocks:
        slug = block.title.replace(" ", "_").replace(":", "_")
        path = target / f"{block.index:02d}_{slug}.vba"
        path.write_text(block.code, encoding="utf-8")
        entries.append({"index": block.index, "caption": block.caption, "title": block.title, "path": str(path)})
    bundle = target / "bundle.vba"
    bundle.write_text(emit(document), encoding="utf-8")
    return {
        "model_intent_id": document.get("model_intent_id"),
        "block_count": len(blocks),
        "bundle": str(bundle),
        "blocks": entries,
    }


def expected_entities(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The CST entities this VBA will create, with their expected bounding boxes.

    ``verify.py`` compares this against what CST actually reports.
    """
    entities = []
    for net in _sorted_nets(document):
        box = ir.net_bounding_box(net)
        entities.append(
            {
                "net": net["name"],
                "component": component_name(net["name"]),
                "name": body_name(net["name"]),
                "full_name": body_full_name(net["name"]),
                "material": ir.solid_material(document, net, {}),
                "primitive_count": len(net.get("solids", [])),
                "bounding_box": None
                if box is None
                else {"x0": box[0], "y0": box[1], "z0": box[2], "x1": box[3], "y1": box[4], "z1": box[5]},
            }
        )
    return entities
