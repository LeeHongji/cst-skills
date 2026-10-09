"""Geometry IR to STEP/DXF via CadQuery.

This keeps the CAD interchange path that the one-off review scripts had, but
sourced from the IR instead of a hand-written script. CadQuery and ezdxf are
optional extras: the rest of the plane must stay importable without the 1.2 GB
OCP stack, so both are imported lazily.

Note for callers: the OCP runtime can fault while the interpreter tears down.
Scripts that export STEP should end with ``os._exit(0)`` after flushing, which
is what the original review scripts did.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import ir

#: Fallback DXF layer colours (AutoCAD colour indices) by net class.
_DXF_CLASS_COLOR = {"signal": 5, "ground": 8, "reference": 4, "floating": 6}


class CadBackendUnavailable(RuntimeError):
    """Raised when the optional CadQuery/ezdxf extras are not installed."""


def _require_cadquery() -> Any:
    try:
        import cadquery
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise CadBackendUnavailable(
            "cadquery is required for STEP export. Install the 'cad' extra into MCP/CST-CAD/.venv."
        ) from exc
    return cadquery


def _require_ezdxf() -> Any:
    try:
        import ezdxf
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise CadBackendUnavailable(
            "ezdxf is required for DXF export. Install the 'cad' extra into MCP/CST-CAD/.venv."
        ) from exc
    return ezdxf


def _solid_workplane(cq: Any, solid: dict[str, Any]) -> Any:
    kind = solid["kind"]
    if kind == "box":
        box = solid["box"]
        width = box["x1"] - box["x0"]
        height = box["y1"] - box["y0"]
        return (
            cq.Workplane("XY")
            .workplane(offset=box["z0"])
            .center((box["x0"] + box["x1"]) / 2.0, (box["y0"] + box["y1"]) / 2.0)
            .rect(width, height)
            .extrude(box["z1"] - box["z0"])
        )
    if kind == "extrude_polygon":
        shape = solid["extrude_polygon"]
        points = [(float(x), float(y)) for x, y in shape["points"]]
        return (
            cq.Workplane("XY")
            .workplane(offset=shape["z0"])
            .polyline(points)
            .close()
            .extrude(shape["z1"] - shape["z0"])
        )
    raise NotImplementedError(f"primitive kind {kind!r} has no CadQuery backend yet")


def net_solid(document: dict[str, Any], net: dict[str, Any]) -> Any:
    """Union every primitive of a net into a single CadQuery solid."""
    cq = _require_cadquery()
    solids = sorted(net.get("solids", []), key=lambda item: str(item["id"]))
    if not solids:
        raise ValueError(f"net {net['name']!r} has no solids")
    result = _solid_workplane(cq, solids[0])
    for solid in solids[1:]:
        piece = _solid_workplane(cq, solid)
        if solid.get("operation") == "subtract":
            result = result.cut(piece, clean=True)
        else:
            result = result.union(piece, clean=True)
    return result


def build_assembly(document: dict[str, Any]) -> Any:
    cq = _require_cadquery()
    assembly = cq.Assembly(name=document.get("model_id", "cst_cad_model"))
    for net in sorted(document.get("nets", []), key=lambda item: str(item["name"])):
        color = net.get("color")
        kwargs: dict[str, Any] = {"name": net["name"]}
        if color:
            alpha = 0.45 if net.get("net_class") == "reference" else 1.0
            kwargs["color"] = cq.Color(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, alpha)
        assembly.add(net_solid(document, net), **kwargs)
    return assembly


def export_step(document: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    build_assembly(document).save(str(target), exportType="STEP", mode="default")
    return target


def export_dxf(document: dict[str, Any], path: str | Path, layer: str | None = None) -> Path:
    """Export the footprint of one layer (default: every layer) as a 2D DXF."""
    ezdxf = _require_ezdxf()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    drawing = ezdxf.new("R2010", setup=True)
    modelspace = drawing.modelspace()
    for net in sorted(document.get("nets", []), key=lambda item: str(item["name"])):
        if layer is not None and net["layer"] != layer:
            continue
        if net["name"] not in drawing.layers:
            drawing.layers.add(net["name"], color=_DXF_CLASS_COLOR.get(net.get("net_class", "signal"), 7))
        for solid in sorted(net.get("solids", []), key=lambda item: str(item["id"])):
            ring = ir.footprint(solid)
            if ring is None:
                continue
            modelspace.add_lwpolyline(ring, close=True, dxfattribs={"layer": net["name"]})

    for port in sorted(document.get("ports", []), key=lambda item: int(item["number"])):
        if "PORT_REFERENCE" not in drawing.layers:
            drawing.layers.add("PORT_REFERENCE", color=4)
        extent = port["extent"]
        modelspace.add_lwpolyline(
            [
                (extent["x0"], extent["y0"]),
                (extent["x1"], extent["y0"]),
                (extent["x1"], extent["y1"]),
                (extent["x0"], extent["y1"]),
            ],
            close=True,
            dxfattribs={"layer": "PORT_REFERENCE"},
        )

    units = document.get("units", {}).get("length", "mm")
    drawing.header["$INSUNITS"] = {"mm": 4, "cm": 5, "m": 6, "in": 1, "mil": 11}.get(units, 4)
    drawing.saveas(target)
    return target
