"""Design rule checking over the geometry IR.

This automates what the one-off CAD review scripts did by hand: the
``self_checks`` dictionary, the "NO bridge" annotations drawn between coupling
gaps, and the visual confirmation that each electrical network is actually one
connected piece of copper.

The report is deterministic and carries no timestamp so that its SHA-256 can be
bound to an approval record later.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

from . import ir

Point = tuple[float, float]
Ring = list[Point]

REPORT_SCHEMA_VERSION = 1

#: Coordinates closer than this are the same point. Chosen to match the IR
#: canonicalization resolution so DRC and identity agree on what "equal" means.
EPS = 1e-9


# --------------------------------------------------------------------- geometry


def _segment_distance(p1: Point, p2: Point, p3: Point, p4: Point) -> float:
    """Minimum distance between segments p1p2 and p3p4."""
    if _segments_intersect(p1, p2, p3, p4):
        return 0.0
    return min(
        _point_segment_distance(p1, p3, p4),
        _point_segment_distance(p2, p3, p4),
        _point_segment_distance(p3, p1, p2),
        _point_segment_distance(p4, p1, p2),
    )


def _point_segment_distance(point: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    px, py = point
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared <= EPS * EPS:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _orientation(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Point, b: Point, point: Point) -> bool:
    return (
        min(a[0], b[0]) - EPS <= point[0] <= max(a[0], b[0]) + EPS
        and min(a[1], b[1]) - EPS <= point[1] <= max(a[1], b[1]) + EPS
    )


def _segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    d1 = _orientation(p3, p4, p1)
    d2 = _orientation(p3, p4, p2)
    d3 = _orientation(p1, p2, p3)
    d4 = _orientation(p1, p2, p4)
    if ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and (
        (d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)
    ):
        return True
    for d, (a, b, point) in (
        (d1, (p3, p4, p1)),
        (d2, (p3, p4, p2)),
        (d3, (p1, p2, p3)),
        (d4, (p1, p2, p4)),
    ):
        if abs(d) <= EPS and _on_segment(a, b, point):
            return True
    return False


def _point_in_ring(point: Point, ring: Ring) -> bool:
    px, py = point
    inside = False
    count = len(ring)
    for index in range(count):
        ax, ay = ring[index]
        bx, by = ring[(index + 1) % count]
        if _point_segment_distance(point, (ax, ay), (bx, by)) <= EPS:
            return True
        if (ay > py) != (by > py):
            crossing = ax + (py - ay) * (bx - ax) / (by - ay)
            if crossing > px:
                inside = not inside
    return inside


def _edges(ring: Ring) -> Iterable[tuple[Point, Point]]:
    count = len(ring)
    for index in range(count):
        yield ring[index], ring[(index + 1) % count]


def ring_distance(left: Ring, right: Ring) -> float:
    """Distance between two simple polygons; 0 when they touch or overlap."""
    for point in left:
        if _point_in_ring(point, right):
            return 0.0
    for point in right:
        if _point_in_ring(point, left):
            return 0.0
    best = math.inf
    for a, b in _edges(left):
        for c, d in _edges(right):
            best = min(best, _segment_distance(a, b, c, d))
            if best <= EPS:
                return 0.0
    return best


def ring_min_width(ring: Ring) -> float:
    """Local width proxy: smallest distance between non-adjacent edges.

    For a rectangle this returns ``min(width, height)``, which is exactly the
    narrowest etched feature. For rectilinear L and U shapes it returns the
    narrowest arm, which is the quantity a fabrication rule cares about.
    """
    edges = list(_edges(ring))
    count = len(edges)
    if count < 4:
        return math.inf
    best = math.inf
    for i in range(count):
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue  # adjacent edges always meet at a shared vertex
            a, b = edges[i]
            c, d = edges[j]
            best = min(best, _segment_distance(a, b, c, d))
    return best


def ring_bounds(ring: Ring) -> tuple[float, float, float, float]:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def ring_centroid(ring: Ring) -> Point:
    x0, y0, x1, y1 = ring_bounds(ring)
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _z_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    # Conductors sharing a face at z=0 are electrically connected even though
    # their volume overlap is zero. This also matters for stacked-net continuity.
    return min(a[1], b[1]) - max(a[0], b[0]) >= -EPS


# ------------------------------------------------------------------ IR shapes


class Shape:
    """One IR primitive reduced to the 2.5D form the DRC rules operate on."""

    __slots__ = ("net", "layer", "solid_id", "ring", "zs")

    def __init__(self, net: str, layer: str, solid_id: str, ring: Ring, zs: tuple[float, float]) -> None:
        self.net = net
        self.layer = layer
        self.solid_id = solid_id
        self.ring = ring
        self.zs = zs

    @property
    def key(self) -> str:
        return f"{self.net}:{self.solid_id}"

    def location(self) -> dict[str, float]:
        x0, y0, x1, y1 = ring_bounds(self.ring)
        return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "z0": self.zs[0], "z1": self.zs[1]}


def collect_shapes(document: dict[str, Any]) -> list[Shape]:
    shapes: list[Shape] = []
    for net in document.get("nets", []):
        for solid in net.get("solids", []):
            ring = ir.footprint(solid)
            zs = ir.z_range(solid)
            if ring is None or zs is None:
                continue  # reserved primitive kinds are not checkable yet
            shapes.append(Shape(net["name"], net["layer"], solid["id"], list(ring), zs))
    return shapes


def _scope_matches(scope: str, *, net: str | None = None, layer: str | None = None, port: str | None = None) -> bool:
    if "|" in scope:
        return any(_scope_matches(part.strip(), net=net, layer=layer, port=port) for part in scope.split("|"))
    if scope == "*":
        return True
    kind, _, target = scope.partition(":")
    if kind == "net":
        return net is not None and (target == "*" or target == net)
    if kind == "layer":
        return layer is not None and (target == "*" or target == layer)
    if kind == "port":
        return port is not None and (target == "*" or target == port)
    return False


def _check(rule: dict[str, Any], **fields: Any) -> dict[str, Any]:
    record = {
        "id": rule["id"],
        "rule": rule["rule"],
        "scope": rule["scope"],
        "severity": rule.get("severity", "error"),
    }
    record.update(fields)
    return record


# ----------------------------------------------------------------- rule bodies


def _rule_min_spacing(document: dict[str, Any], rule: dict[str, Any], shapes: list[Shape]) -> dict[str, Any]:
    params = rule.get("params", {})
    threshold = float(params.get("min_spacing", params.get("value", 0.0)))
    include_intra_net = bool(params.get("include_intra_net", False))
    scoped = [shape for shape in shapes if _scope_matches(rule["scope"], net=shape.net, layer=shape.layer)]

    measured = math.inf
    worst: dict[str, Any] | None = None
    violations: list[dict[str, Any]] = []
    pairs = 0
    for index, left in enumerate(scoped):
        for right in scoped[index + 1 :]:
            if left.net == right.net and not include_intra_net:
                continue
            if not _z_overlap(left.zs, right.zs):
                continue
            distance = ring_distance(left.ring, right.ring)
            if distance <= EPS:
                continue  # touching or overlapping is a short, not a spacing miss
            pairs += 1
            if distance < measured:
                measured = distance
                worst = {"a": left.key, "b": right.key, "distance": distance}
            if distance < threshold - EPS:
                violations.append(
                    {
                        "a": left.key,
                        "b": right.key,
                        "measured": distance,
                        "threshold": threshold,
                        "location": {
                            "a": left.location(),
                            "b": right.location(),
                        },
                    }
                )
    return _check(
        rule,
        status="fail" if violations else "pass",
        comparator="ge",
        threshold=threshold,
        measured=None if measured is math.inf else measured,
        unit=document.get("units", {}).get("length"),
        pairs_evaluated=pairs,
        closest_pair=worst,
        violations=violations,
    )


def _rule_min_width(document: dict[str, Any], rule: dict[str, Any], shapes: list[Shape]) -> dict[str, Any]:
    params = rule.get("params", {})
    threshold = float(params.get("min_width", params.get("value", 0.0)))
    scoped = [shape for shape in shapes if _scope_matches(rule["scope"], net=shape.net, layer=shape.layer)]

    measured = math.inf
    narrowest: dict[str, Any] | None = None
    violations: list[dict[str, Any]] = []
    for shape in scoped:
        width = ring_min_width(shape.ring)
        if width is math.inf:
            continue
        if width < measured:
            measured = width
            narrowest = {"solid": shape.key, "width": width}
        if width < threshold - EPS:
            violations.append(
                {
                    "solid": shape.key,
                    "measured": width,
                    "threshold": threshold,
                    "location": shape.location(),
                }
            )
    return _check(
        rule,
        status="fail" if violations else "pass",
        comparator="ge",
        threshold=threshold,
        measured=None if measured is math.inf else measured,
        unit=document.get("units", {}).get("length"),
        solids_evaluated=len(scoped),
        narrowest=narrowest,
        violations=violations,
    )


def _rule_net_connectivity(document: dict[str, Any], rule: dict[str, Any], shapes: list[Shape]) -> dict[str, Any]:
    params = rule.get("params", {})
    allowed_components = int(params.get("max_components", 1))
    results: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for net in document.get("nets", []):
        name = net["name"]
        if not _scope_matches(rule["scope"], net=name, layer=net.get("layer")):
            continue
        members = [shape for shape in shapes if shape.net == name]
        if not members:
            continue
        parent = list(range(len(members)))

        def find(node: int) -> int:
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                if not _z_overlap(members[i].zs, members[j].zs):
                    continue
                if ring_distance(members[i].ring, members[j].ring) <= EPS:
                    union(i, j)

        groups: dict[int, list[str]] = {}
        for index, shape in enumerate(members):
            groups.setdefault(find(index), []).append(shape.solid_id)
        components = [sorted(ids) for _, ids in sorted(groups.items())]
        results.append({"net": name, "solids": len(members), "components": len(components), "component_members": components})
        if len(components) > allowed_components:
            violations.append(
                {
                    "net": name,
                    "measured": len(components),
                    "threshold": allowed_components,
                    "components": components,
                    "location": {"net_bounding_box": ir.net_bounding_box(net)},
                }
            )

    measured = max((item["components"] for item in results), default=0)
    return _check(
        rule,
        status="fail" if violations else "pass",
        comparator="le",
        threshold=allowed_components,
        measured=measured,
        unit="components",
        nets_evaluated=len(results),
        per_net=results,
        violations=violations,
    )


def _rule_no_cross_net_short(document: dict[str, Any], rule: dict[str, Any], shapes: list[Shape]) -> dict[str, Any]:
    params = rule.get("params", {})
    tolerance = float(params.get("tolerance", EPS))
    allowed = {tuple(sorted(pair)) for pair in params.get("allowed_pairs", [])}
    scoped = [shape for shape in shapes if _scope_matches(rule["scope"], net=shape.net, layer=shape.layer)]

    violations: list[dict[str, Any]] = []
    pairs = 0
    for index, left in enumerate(scoped):
        for right in scoped[index + 1 :]:
            if left.net == right.net:
                continue
            if tuple(sorted((left.net, right.net))) in allowed:
                continue
            if not _z_overlap(left.zs, right.zs):
                continue
            pairs += 1
            distance = ring_distance(left.ring, right.ring)
            if distance <= tolerance:
                violations.append(
                    {
                        "net_a": left.net,
                        "net_b": right.net,
                        "a": left.key,
                        "b": right.key,
                        "measured": distance,
                        "threshold": tolerance,
                        "location": {"a": left.location(), "b": right.location()},
                    }
                )
    return _check(
        rule,
        status="fail" if violations else "pass",
        comparator="gt",
        threshold=tolerance,
        measured=len(violations),
        unit="shorted pairs",
        pairs_evaluated=pairs,
        violations=violations,
    )


def _rule_board_containment(document: dict[str, Any], rule: dict[str, Any], shapes: list[Shape]) -> dict[str, Any]:
    params = rule.get("params", {})
    reference_net = params.get("reference_net")
    if reference_net:
        box = ir.net_bounding_box(ir.net_index(document)[reference_net])
        if box is None:
            raise ValueError(f"board containment reference net {reference_net!r} has no measurable geometry")
        outline = {"x0": box[0], "y0": box[1], "x1": box[3], "y1": box[4]}
    else:
        outline = {key: float(params[key]) for key in ("x0", "y0", "x1", "y1")}
    margin = float(params.get("margin", 0.0))
    scoped = [
        shape
        for shape in shapes
        if _scope_matches(rule["scope"], net=shape.net, layer=shape.layer) and shape.net != reference_net
    ]

    violations: list[dict[str, Any]] = []
    worst = math.inf
    for shape in scoped:
        x0, y0, x1, y1 = ring_bounds(shape.ring)
        clearance = min(
            x0 - (outline["x0"] + margin),
            y0 - (outline["y0"] + margin),
            (outline["x1"] - margin) - x1,
            (outline["y1"] - margin) - y1,
        )
        worst = min(worst, clearance)
        if clearance < -EPS:
            violations.append(
                {
                    "solid": shape.key,
                    "measured": clearance,
                    "threshold": 0.0,
                    "outline": outline,
                    "location": shape.location(),
                }
            )
    return _check(
        rule,
        status="fail" if violations else "pass",
        comparator="ge",
        threshold=0.0,
        measured=None if worst is math.inf else worst,
        unit=document.get("units", {}).get("length"),
        outline=outline,
        solids_evaluated=len(scoped),
        violations=violations,
    )


_PLANE_AXIS = {"xmin": ("x", 0), "xmax": ("x", 1), "ymin": ("y", 0), "ymax": ("y", 1), "zmin": ("z", 0), "zmax": ("z", 1)}


def _rule_port_attachment(document: dict[str, Any], rule: dict[str, Any], shapes: list[Shape]) -> dict[str, Any]:
    params = rule.get("params", {})
    tolerance = float(params.get("tolerance", 1e-6))
    results: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for port in document.get("ports", []):
        if not _scope_matches(rule["scope"], port=port["name"], net=port.get("net")):
            continue
        axis, side = _PLANE_AXIS[port["orientation"]]
        extent = port["extent"]
        plane = extent[f"{axis}{side}"]
        members = [shape for shape in shapes if shape.net == port["net"]]
        gap = math.inf
        witness: str | None = None
        for shape in members:
            x0, y0, x1, y1 = ring_bounds(shape.ring)
            z0, z1 = shape.zs
            spans = {"x": (x0, x1), "y": (y0, y1), "z": (z0, z1)}
            low, high = spans[axis]
            distance = 0.0 if low - tolerance <= plane <= high + tolerance else min(abs(plane - low), abs(plane - high))
            # The conductor must also sit inside the port window on the other axes.
            inside_window = True
            for other in ("x", "y", "z"):
                if other == axis:
                    continue
                olow, ohigh = spans[other]
                if ohigh < extent[f"{other}0"] - tolerance or olow > extent[f"{other}1"] + tolerance:
                    inside_window = False
            if not inside_window:
                continue
            if distance < gap:
                gap = distance
                witness = shape.key
        results.append({"port": port["name"], "net": port["net"], "plane": {axis: plane}, "gap": None if gap is math.inf else gap, "conductor": witness})
        if gap is math.inf or gap > tolerance:
            violations.append(
                {
                    "port": port["name"],
                    "net": port["net"],
                    "measured": None if gap is math.inf else gap,
                    "threshold": tolerance,
                    "location": {"plane": {axis: plane}, "extent": extent},
                }
            )

    measured = max((item["gap"] for item in results if item["gap"] is not None), default=None)
    return _check(
        rule,
        status="fail" if violations else "pass",
        comparator="le",
        threshold=tolerance,
        measured=measured,
        unit=document.get("units", {}).get("length"),
        ports_evaluated=len(results),
        per_port=results,
        violations=violations,
    )


def _rule_symmetry(document: dict[str, Any], rule: dict[str, Any], shapes: list[Shape]) -> dict[str, Any]:
    params = rule.get("params", {})
    axis = str(params.get("axis", "x"))
    position = float(params["position"])
    tolerance = float(params.get("tolerance", 1e-9))
    nets = params.get("nets")
    scoped = [
        shape
        for shape in shapes
        if _scope_matches(rule["scope"], net=shape.net, layer=shape.layer) and (nets is None or shape.net in nets)
    ]

    def mirror(bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = bounds
        if axis == "x":
            return (2 * position - x1, y0, 2 * position - x0, y1)
        return (x0, 2 * position - y1, x1, 2 * position - y0)

    catalogue = [ring_bounds(shape.ring) for shape in scoped]
    violations: list[dict[str, Any]] = []
    worst = 0.0
    for shape, bounds in zip(scoped, catalogue):
        target = mirror(bounds)
        best = min(
            (max(abs(a - b) for a, b in zip(target, candidate)) for candidate in catalogue),
            default=math.inf,
        )
        worst = max(worst, 0.0 if best is math.inf else best)
        if best is math.inf or best > tolerance:
            violations.append(
                {
                    "solid": shape.key,
                    "measured": None if best is math.inf else best,
                    "threshold": tolerance,
                    "expected_mirror": {"x0": target[0], "y0": target[1], "x1": target[2], "y1": target[3]},
                    "location": shape.location(),
                }
            )
    return _check(
        rule,
        status="fail" if violations else "pass",
        comparator="le",
        threshold=tolerance,
        measured=worst,
        unit=document.get("units", {}).get("length"),
        axis=axis,
        position=position,
        solids_evaluated=len(scoped),
        violations=violations,
    )


RULES = {
    "min_spacing": _rule_min_spacing,
    "min_width": _rule_min_width,
    "net_connectivity": _rule_net_connectivity,
    "no_cross_net_short": _rule_no_cross_net_short,
    "board_containment": _rule_board_containment,
    "port_attachment": _rule_port_attachment,
    "symmetry": _rule_symmetry,
}


def run(document: dict[str, Any], rules: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run every design rule and return a deterministic DRC report."""
    shapes = collect_shapes(document)
    selected = list(rules if rules is not None else document.get("design_rules", []))

    checks: list[dict[str, Any]] = []
    for rule in sorted(selected, key=lambda item: str(item.get("id", ""))):
        body = RULES.get(rule.get("rule", ""))
        if body is None:
            checks.append(_check(rule, status="error", message=f"unknown rule {rule.get('rule')!r}", violations=[]))
            continue
        try:
            checks.append(body(document, rule, shapes))
        except Exception as exc:  # a broken rule must be visible, not silent
            checks.append(_check(rule, status="error", message=f"{type(exc).__name__}: {exc}", violations=[]))

    failed = [check for check in checks if check["status"] == "fail" and check["severity"] == "error"]
    warned = [check for check in checks if check["status"] == "fail" and check["severity"] == "warning"]
    errored = [check for check in checks if check["status"] == "error"]

    unsupported = sum(
        1
        for net in document.get("nets", [])
        for solid in net.get("solids", [])
        if ir.footprint(solid) is None
    )

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "model_intent_id": document.get("model_intent_id"),
        "model_id": document.get("model_id"),
        "status": "fail" if failed or errored else ("warn" if warned else "pass"),
        "summary": {
            "checks": len(checks),
            "passed": sum(1 for check in checks if check["status"] == "pass"),
            "failed": len(failed),
            "warnings": len(warned),
            "errors": len(errored),
            "shapes_evaluated": len(shapes),
            "shapes_unsupported": unsupported,
        },
        "checks": checks,
    }
