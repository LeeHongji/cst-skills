"""Geometry IR: canonicalization, identity hashing, validation and diffing.

The IR document is the design-first source of truth for a CST model. Its
identity is ``model_intent_id``, the SHA-256 of a canonical serialization that
is invariant to declaration order, key order, insignificant float noise, prose
metadata and analysis setup. The algorithm is also written into
``brain/schemas/geometry-ir.schema.json`` under ``x-model-intent-id-algorithm``
so the two can be reviewed against each other.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .paths import CadPaths

SCHEMA_VERSION = 1

#: Sections that carry physical model intent and therefore define identity.
IDENTITY_SECTIONS = (
    "schema_version",
    "units",
    "parameters",
    "materials",
    "stackup",
    "nets",
    "ports",
    "boundaries",
    "mesh_hints",
    "design_rules",
)

#: Sections deliberately excluded from identity. See the schema for rationale.
EXCLUDED_SECTIONS = (
    "model_intent_id",
    "model_id",
    "title",
    "description",
    "source",
    "simulation",
    "derived",
    "notes",
)

#: Decimal places kept when normalizing floats. At millimetre units this is
#: nanometre resolution, far below any manufacturable or meshable tolerance.
FLOAT_DECIMALS = 9

PROVENANCE_VALUES = (
    "paper_explicit",
    "strong_inference",
    "assumption",
    "synthesized",
    "optimized",
)

#: Sections that define *topology* -- what the model is made of and how it is
#: connected -- as opposed to how big any of it is.
#:
#: This is :data:`IDENTITY_SECTIONS` without ``mesh_hints``.  Mesh density is how
#: we look at a device, not which device it is; it belongs to ``setup_delta`` in
#: the iteration record and must not force a re-approval.
TOPOLOGY_SECTIONS = (
    "schema_version",
    "units",
    "parameters",
    "materials",
    "stackup",
    "nets",
    "ports",
    "boundaries",
    "design_rules",
)

#: Sections whose numbers are part of the topology.
#:
#: ``design_rules`` is here for a specific reason.  The audit gate is cheap
#: because ``topology_hash`` ignores dimensions, and DRC is what makes that safe:
#: it catches the case where a gap is driven to zero and two conductors merge, a
#: real topology change the hash cannot see.  If rule thresholds were dropped
#: along with every other number, that safety net could be loosened -- lower
#: ``min_spacing`` to 0.001, drive the gap to 0.002 -- without invalidating the
#: approval.  The strictness of the net is part of what was approved.
#:
#: ``schema_version`` is an integer and has to survive for the same reason it is
#: in the identity digest.
TOPOLOGY_NUMERIC_SECTIONS = ("schema_version", "design_rules")

#: Per-item keys that annotate rather than describe.  Dropped from the topology
#: digest so that re-labelling a parameter's provenance, correcting a note, or
#: recolouring a material does not force a new attempt.  ``provenance`` is
#: included deliberately: it is reviewed by a human reading ``audit.html``, and
#: the audit is re-run when the interpretation changes, but a provenance edit on
#: its own does not change what the model *is*.
TOPOLOGY_ANNOTATION_KEYS = frozenset(
    {
        "color",
        "description",
        "label",
        "note",
        "notes",
        "provenance",
        "source",
        "tunable",
        "unit",
    }
)

#: Stands in for every number the topology digest discards.  A placeholder rather
#: than deletion so that a *missing* key is still distinguishable from a key that
#: merely holds a different number.
_NUMBER_PLACEHOLDER = "\x00num"


class IRError(ValueError):
    """Raised when an IR document is structurally invalid."""


def canonical_number(value: float | int) -> str:
    """Render a number as a canonical decimal string.

    Rounding to :data:`FLOAT_DECIMALS` collapses accumulated float noise so
    that ``15.299999999999999`` and ``15.3`` hash identically, which is what
    lets two DSL scripts that reach the same geometry by different arithmetic
    routes produce the same ``model_intent_id``.
    """
    if isinstance(value, bool):  # bool is an int subclass; keep it a boolean
        raise IRError("booleans must not be normalized as numbers")
    number = float(value)
    if not math.isfinite(number):
        raise IRError(f"non-finite number in IR: {value!r}")
    rounded = round(number, FLOAT_DECIMALS)
    if rounded == 0.0:
        rounded = 0.0  # collapse -0.0
    return repr(rounded)


def _sort_key(collection: str) -> Any:
    keys = {
        "parameters": lambda item: str(item.get("name", "")),
        "materials": lambda item: str(item.get("name", "")),
        "stackup": lambda item: str(item.get("name", "")),
        "nets": lambda item: str(item.get("name", "")),
        "solids": lambda item: str(item.get("id", "")),
        "ports": lambda item: (int(item.get("number", 0)), str(item.get("name", ""))),
        "design_rules": lambda item: str(item.get("id", "")),
        "local_refinements": lambda item: str(item.get("target", "")),
        "monitors": lambda item: str(item.get("name", "")),
    }
    return keys.get(collection)


def _canonicalize(value: Any, collection: str | None = None) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value):
            if key.startswith("_") or key in EXCLUDED_SECTIONS:
                continue
            item = value[key]
            if item is None:
                continue
            result[key] = _canonicalize(item, collection=key)
        return result
    if isinstance(value, (list, tuple)):
        sorter = _sort_key(collection or "")
        # Sort the raw items before normalizing: the sort keys are names and
        # integers, which are easier to read here than canonical number tokens.
        source = sorted(value, key=sorter) if sorter is not None else list(value)
        return [_canonicalize(item, collection=None) for item in source]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _CanonicalNumber(canonical_number(value))
    if isinstance(value, str):
        return value
    raise IRError(f"unsupported IR value type: {type(value).__name__}")


class _CanonicalNumber:
    """A number already rendered to its canonical decimal string."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return self.text


def _serialize(value: Any) -> str:
    if isinstance(value, _CanonicalNumber):
        return value.text
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        body = ",".join(f"{json.dumps(k, ensure_ascii=False)}:{_serialize(v)}" for k, v in value.items())
        return "{" + body + "}"
    if isinstance(value, list):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    raise IRError(f"unsupported canonical value: {value!r}")


def canonical_text(document: dict[str, Any]) -> str:
    """Return the canonical serialization used for the identity digest."""
    identity = {key: document[key] for key in IDENTITY_SECTIONS if key in document and document[key] is not None}
    return _serialize(_canonicalize(identity))


def model_intent_id(document: dict[str, Any]) -> str:
    """Return the SHA-256 identity of the physical model intent."""
    return hashlib.sha256(canonical_text(document).encode("utf-8")).hexdigest()


def _strip_numbers(value: Any, collection: str | None = None, keep_numbers: bool = False) -> Any:
    """Canonicalize while replacing every number with a placeholder.

    Strings survive untouched, and that is the whole trick: the IR puts CST
    parameter expressions in the same slots as numbers -- ``"epsilon": "er_sub"``,
    ``"ymax": "open_space"``, ``expressions.x0 = "src_probe_x0+probe_w"`` -- so
    dropping numbers and keeping strings drops the dimensions and keeps the
    expression graph, which is exactly the topology.
    """
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value):
            if key.startswith("_") or key in EXCLUDED_SECTIONS:
                continue
            if key in TOPOLOGY_ANNOTATION_KEYS:
                continue
            item = value[key]
            if item is None:
                continue
            result[key] = _strip_numbers(item, collection=key, keep_numbers=keep_numbers)
        return result
    if isinstance(value, (list, tuple)):
        sorter = _sort_key(collection or "")
        source = sorted(value, key=sorter) if sorter is not None else list(value)
        return [_strip_numbers(item, collection=None, keep_numbers=keep_numbers) for item in source]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if keep_numbers:
            return _CanonicalNumber(canonical_number(value))
        return _NUMBER_PLACEHOLDER
    if isinstance(value, str):
        return value
    raise IRError(f"unsupported IR value type: {type(value).__name__}")


def topology_text(document: dict[str, Any]) -> str:
    """Return the canonical serialization used for the topology digest."""
    topology = {
        key: _strip_numbers(
            document[key],
            collection=key,
            keep_numbers=key in TOPOLOGY_NUMERIC_SECTIONS,
        )
        for key in TOPOLOGY_SECTIONS
        if key in document and document[key] is not None
    }
    return _serialize(topology)


def topology_hash(document: dict[str, Any]) -> str:
    """Return the SHA-256 digest of the model's topology.

    Companion to :func:`model_intent_id`, and deliberately coarser.  Changing a
    dimension changes the intent id but not the topology hash, which is what lets
    an approved attempt keep iterating on parameters without a human looking at
    every step.  Adding or removing a solid, renaming a net, repointing a port,
    or changing an expression changes both, and the iteration loop refuses to
    continue inside an attempt whose approval was granted for a different
    topology.

    Two things this digest cannot see, both covered elsewhere:

    * a gap driven to zero, which merges two conductors and therefore changes the
      topology while every expression stays put -- caught by the ``min_spacing``
      and ``no_cross_net_short`` DRC rules, which is why DRC is a structural
      requirement and not a convention;
    * a dimension walked so far that the geometry no longer resembles the figure
      it was approved against -- caught by the approved parameter ranges recorded
      in ``attempt.json``.
    """
    return hashlib.sha256(topology_text(document).encode("utf-8")).hexdigest()


def short_topology_hash(document_or_digest: dict[str, Any] | str) -> str:
    digest = document_or_digest if isinstance(document_or_digest, str) else topology_hash(document_or_digest)
    return f"topo-{digest[:12]}"


def short_intent_id(document_or_digest: dict[str, Any] | str) -> str:
    digest = document_or_digest if isinstance(document_or_digest, str) else model_intent_id(document_or_digest)
    return f"intent-{digest[:12]}"


def stamp(document: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the document with a freshly computed identity."""
    stamped = json.loads(json.dumps(document, ensure_ascii=False))
    stamped["model_intent_id"] = model_intent_id(stamped)
    return stamped


def load_schema(paths: CadPaths | None = None) -> dict[str, Any]:
    resolved = paths or CadPaths.resolve()
    return json.loads(resolved.geometry_ir_schema.read_text(encoding="utf-8"))


def validate(document: dict[str, Any], paths: CadPaths | None = None) -> list[str]:
    """Validate against the JSON Schema plus cross-reference rules.

    Returns a list of human-readable problems; empty means valid. Schema
    validation alone cannot catch dangling references between nets, layers,
    materials and ports, so those are checked here.
    """
    import jsonschema

    problems: list[str] = []
    validator = jsonschema.Draft202012Validator(load_schema(paths))
    for error in sorted(validator.iter_errors(document), key=lambda e: list(e.path)):
        location = "/".join(str(part) for part in error.path) or "<root>"
        problems.append(f"schema: {location}: {error.message}")

    expected = model_intent_id(document)
    actual = document.get("model_intent_id")
    if actual != expected:
        problems.append(f"identity: model_intent_id is {actual!r} but canonical digest is {expected!r}")

    material_names = {material["name"] for material in document.get("materials", []) if "name" in material}
    layer_names = {layer["name"] for layer in document.get("stackup", []) if "name" in layer}
    net_names = {net["name"] for net in document.get("nets", []) if "name" in net}

    for layer in document.get("stackup", []):
        if layer.get("material") not in material_names:
            problems.append(f"reference: stackup layer {layer.get('name')!r} uses unknown material {layer.get('material')!r}")
        if layer.get("z1") is not None and layer.get("z0") is not None and layer["z1"] <= layer["z0"]:
            problems.append(f"geometry: stackup layer {layer.get('name')!r} has z1 <= z0")

    seen_solid_ids: set[tuple[str, str]] = set()
    for net in document.get("nets", []):
        if net.get("layer") not in layer_names:
            problems.append(f"reference: net {net.get('name')!r} uses unknown layer {net.get('layer')!r}")
        if net.get("material") is not None and net["material"] not in material_names:
            problems.append(f"reference: net {net.get('name')!r} uses unknown material {net['material']!r}")
        for solid in net.get("solids", []):
            key = (net.get("name", ""), solid.get("id", ""))
            if key in seen_solid_ids:
                problems.append(f"identity: duplicate solid id {solid.get('id')!r} in net {net.get('name')!r}")
            seen_solid_ids.add(key)
            if solid.get("material") is not None and solid["material"] not in material_names:
                problems.append(f"reference: solid {key} uses unknown material {solid['material']!r}")
            box = solid.get("box")
            if box is not None:
                for low, high in (("x0", "x1"), ("y0", "y1"), ("z0", "z1")):
                    if box[high] <= box[low]:
                        problems.append(f"geometry: solid {key} has {high} <= {low}")

    port_numbers: set[int] = set()
    for port in document.get("ports", []):
        if port.get("net") not in net_names:
            problems.append(f"reference: port {port.get('name')!r} attaches to unknown net {port.get('net')!r}")
        reference_net = port.get("reference_net")
        if reference_net is not None and reference_net not in net_names:
            problems.append(f"reference: port {port.get('name')!r} references unknown net {reference_net!r}")
        number = port.get("number")
        if number in port_numbers:
            problems.append(f"identity: duplicate port number {number}")
        port_numbers.add(number)

    for refinement in document.get("mesh_hints", {}).get("local_refinements", []):
        kind, _, target = str(refinement.get("target", "")).partition(":")
        if kind == "net" and target not in net_names:
            problems.append(f"reference: mesh refinement targets unknown net {target!r}")
        if kind == "layer" and target not in layer_names:
            problems.append(f"reference: mesh refinement targets unknown layer {target!r}")

    return problems


def require_valid(document: dict[str, Any], paths: CadPaths | None = None) -> None:
    problems = validate(document, paths)
    if problems:
        raise IRError("invalid geometry IR:\n  " + "\n  ".join(problems))


def dumps(document: dict[str, Any]) -> str:
    """Serialize an IR document for storage: stable key order, readable."""
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write(document: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps(document), encoding="utf-8")
    return target


def read(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def layer_index(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {layer["name"]: layer for layer in document.get("stackup", [])}


def net_index(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {net["name"]: net for net in document.get("nets", [])}


def solid_material(document: dict[str, Any], net: dict[str, Any], solid: dict[str, Any]) -> str:
    """Resolve the effective material: solid override, then net, then layer."""
    if solid.get("material"):
        return str(solid["material"])
    if net.get("material"):
        return str(net["material"])
    return str(layer_index(document)[net["layer"]]["material"])


def footprint(solid: dict[str, Any]) -> list[tuple[float, float]] | None:
    """Return the xy footprint polygon of a solid, or None if unsupported.

    Boxes and extruded polygons both reduce to a closed 2D ring, which is what
    the DRC engine needs for spacing, connectivity and short checks.
    """
    kind = solid.get("kind")
    if kind == "box":
        box = solid["box"]
        return [
            (box["x0"], box["y0"]),
            (box["x1"], box["y0"]),
            (box["x1"], box["y1"]),
            (box["x0"], box["y1"]),
        ]
    if kind == "extrude_polygon":
        return [(float(x), float(y)) for x, y in solid["extrude_polygon"]["points"]]
    return None


def z_range(solid: dict[str, Any]) -> tuple[float, float] | None:
    kind = solid.get("kind")
    if kind == "box":
        return float(solid["box"]["z0"]), float(solid["box"]["z1"])
    if kind == "extrude_polygon":
        return float(solid["extrude_polygon"]["z0"]), float(solid["extrude_polygon"]["z1"])
    return None


def bounding_box(solid: dict[str, Any]) -> tuple[float, float, float, float, float, float] | None:
    ring = footprint(solid)
    zs = z_range(solid)
    if ring is None or zs is None:
        return None
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return (min(xs), min(ys), zs[0], max(xs), max(ys), zs[1])


def net_bounding_box(net: dict[str, Any]) -> tuple[float, float, float, float, float, float] | None:
    boxes = [bounding_box(solid) for solid in net.get("solids", [])]
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        min(box[2] for box in boxes),
        max(box[3] for box in boxes),
        max(box[4] for box in boxes),
        max(box[5] for box in boxes),
    )


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key in sorted(value):
            _flatten(f"{prefix}.{key}" if prefix else key, value[key], out)
    elif isinstance(value, list):
        for position, item in enumerate(value):
            _flatten(f"{prefix}[{position}]", item, out)
    else:
        out[prefix] = value


def diff(left: dict[str, Any], right: dict[str, Any], tolerance: float = 1e-9) -> dict[str, Any]:
    """Structural diff between two IR documents, tolerant of float noise."""
    left_flat: dict[str, Any] = {}
    right_flat: dict[str, Any] = {}
    _flatten("", left, left_flat)
    _flatten("", right, right_flat)

    changed: list[dict[str, Any]] = []
    for key in sorted(set(left_flat) | set(right_flat)):
        if key not in left_flat:
            changed.append({"path": key, "change": "added", "right": right_flat[key]})
            continue
        if key not in right_flat:
            changed.append({"path": key, "change": "removed", "left": left_flat[key]})
            continue
        a, b = left_flat[key], right_flat[key]
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
            if abs(float(a) - float(b)) > tolerance:
                changed.append({"path": key, "change": "modified", "left": a, "right": b, "delta": float(b) - float(a)})
        elif a != b:
            changed.append({"path": key, "change": "modified", "left": a, "right": b})

    return {
        "left_model_intent_id": left.get("model_intent_id"),
        "right_model_intent_id": right.get("model_intent_id"),
        "identical_intent": left.get("model_intent_id") == right.get("model_intent_id"),
        "tolerance": tolerance,
        "difference_count": len(changed),
        "differences": changed,
    }


def provenance_summary(document: dict[str, Any]) -> dict[str, int]:
    counts = {value: 0 for value in PROVENANCE_VALUES}
    for parameter in document.get("parameters", []):
        provenance = parameter.get("provenance")
        if provenance in counts:
            counts[provenance] += 1
    return counts
