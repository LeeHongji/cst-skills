"""Parametric modelling DSL that produces geometry IR documents.

A design script declares parameters with explicit provenance, a stackup, named
electrical nets and their primitives. Every dimension carries two faces at
once: a Python float used by DRC and by geometry comparison, and a CST
parameter expression used by the VBA backend so the emitted model stays
sweepable instead of being frozen into literals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from . import ir

_ATOM = 3
_MUL = 2
_ADD = 1
# Unary minus and negative literals sit below every binary operator so that they
# are parenthesised whenever they are combined, and never glue onto a preceding
# operator to form CST-hostile text such as "a*-2.0".
_NEG = 0


@dataclass(frozen=True)
class Expr:
    """A CST parameter expression paired with its evaluated value."""

    text: str
    value: float
    precedence: int = _ATOM

    def _wrap(self, minimum: int) -> str:
        return f"({self.text})" if self.precedence < minimum else self.text

    def __float__(self) -> float:
        return float(self.value)

    def __add__(self, other: "Expr | float | int") -> "Expr":
        rhs = as_expr(other)
        return Expr(f"{self._wrap(_ADD)}+{rhs._wrap(_ADD)}", self.value + rhs.value, _ADD)

    def __radd__(self, other: "Expr | float | int") -> "Expr":
        return as_expr(other) + self

    def __sub__(self, other: "Expr | float | int") -> "Expr":
        rhs = as_expr(other)
        return Expr(f"{self._wrap(_ADD)}-{rhs._wrap(_MUL)}", self.value - rhs.value, _ADD)

    def __rsub__(self, other: "Expr | float | int") -> "Expr":
        return as_expr(other) - self

    def __mul__(self, other: "Expr | float | int") -> "Expr":
        rhs = as_expr(other)
        return Expr(f"{self._wrap(_MUL)}*{rhs._wrap(_MUL)}", self.value * rhs.value, _MUL)

    def __rmul__(self, other: "Expr | float | int") -> "Expr":
        return as_expr(other) * self

    def __truediv__(self, other: "Expr | float | int") -> "Expr":
        rhs = as_expr(other)
        return Expr(f"{self._wrap(_MUL)}/{rhs._wrap(_ATOM)}", self.value / rhs.value, _MUL)

    def __rtruediv__(self, other: "Expr | float | int") -> "Expr":
        return as_expr(other) / self

    def __neg__(self) -> "Expr":
        return Expr(f"-{self._wrap(_ATOM)}", -self.value, _NEG)


def as_expr(value: "Expr | float | int") -> Expr:
    if isinstance(value, Expr):
        return value
    number = float(value)
    return Expr(repr(number), number, _ATOM if number >= 0 else _NEG)


Numeric = Expr | float | int


def _value(item: Numeric) -> float:
    return float(item.value) if isinstance(item, Expr) else float(item)


def _text(item: Numeric) -> str:
    return as_expr(item).text


class NetBuilder:
    """Collects the primitives that make up one named electrical net."""

    def __init__(self, model: "ModelBuilder", record: dict[str, Any], layer: dict[str, Any]) -> None:
        self._model = model
        self._record = record
        self._layer = layer

    @property
    def name(self) -> str:
        return str(self._record["name"])

    def _next_id(self, solid_id: str | None) -> str:
        if solid_id is not None:
            return solid_id
        return f"s{len(self._record['solids']) + 1:03d}"

    def box(
        self,
        x0: Numeric,
        y0: Numeric,
        x1: Numeric,
        y1: Numeric,
        z0: Numeric | None = None,
        z1: Numeric | None = None,
        solid_id: str | None = None,
        material: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Add an axis-aligned box. z defaults to the net's layer extent."""
        low_z = self._layer["z0_expr"] if z0 is None else z0
        high_z = self._layer["z1_expr"] if z1 is None else z1
        corners = {"x0": x0, "y0": y0, "z0": low_z, "x1": x1, "y1": y1, "z1": high_z}
        solid = {
            "id": self._next_id(solid_id),
            "kind": "box",
            "box": {key: _value(item) for key, item in corners.items()},
            "expressions": {key: _text(item) for key, item in corners.items()},
        }
        if material is not None:
            solid["material"] = material
        if note is not None:
            solid["note"] = note
        self._record["solids"].append(solid)
        return solid

    def rect(
        self,
        x0: Numeric,
        y0: Numeric,
        width: Numeric,
        height: Numeric,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Add a footprint rectangle given as origin plus width and height."""
        return self.box(x0, y0, as_expr(x0) + width, as_expr(y0) + height, **kwargs)

    def polygon(
        self,
        points: Sequence[tuple[Numeric, Numeric]],
        z0: Numeric | None = None,
        z1: Numeric | None = None,
        solid_id: str | None = None,
        material: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        low_z = self._layer["z0_expr"] if z0 is None else z0
        high_z = self._layer["z1_expr"] if z1 is None else z1
        solid = {
            "id": self._next_id(solid_id),
            "kind": "extrude_polygon",
            "extrude_polygon": {
                "points": [[_value(px), _value(py)] for px, py in points],
                "z0": _value(low_z),
                "z1": _value(high_z),
            },
            "expressions": {
                "z0": _text(low_z),
                "z1": _text(high_z),
                **{f"p{index}x": _text(px) for index, (px, _) in enumerate(points)},
                **{f"p{index}y": _text(py) for index, (_, py) in enumerate(points)},
            },
        }
        if material is not None:
            solid["material"] = material
        if note is not None:
            solid["note"] = note
        self._record["solids"].append(solid)
        return solid


class ModelBuilder:
    """Builds a geometry IR document from a parametric design script."""

    def __init__(
        self,
        model_id: str,
        title: str | None = None,
        description: str | None = None,
        source: dict[str, Any] | None = None,
        overrides: Mapping[str, Numeric] | None = None,
    ) -> None:
        self._model_id = model_id
        self._title = title
        self._description = description
        self._source = source or {}
        self._overrides = dict(overrides or {})
        self._overridden: dict[str, float] = {}
        self._units: dict[str, str] = {"length": "mm", "frequency": "GHz"}
        self._parameters: list[dict[str, Any]] = []
        self._parameter_names: set[str] = set()
        self._materials: list[dict[str, Any]] = []
        self._stackup: list[dict[str, Any]] = []
        self._layers: dict[str, dict[str, Any]] = {}
        self._nets: list[dict[str, Any]] = []
        self._ports: list[dict[str, Any]] = []
        self._boundaries: dict[str, Any] = {}
        self._mesh_hints: dict[str, Any] = {}
        self._design_rules: list[dict[str, Any]] = []
        self._simulation: dict[str, Any] = {}
        self._derived: dict[str, Any] = {}

    # ---------------------------------------------------------------- units

    def units(
        self,
        length: str = "mm",
        frequency: str = "GHz",
        time: str | None = None,
        temperature: str | None = None,
    ) -> None:
        self._units = {"length": length, "frequency": frequency}
        if time is not None:
            self._units["time"] = time
        if temperature is not None:
            self._units["temperature"] = temperature

    # ----------------------------------------------------------- parameters

    def param(
        self,
        name: str,
        value: Numeric,
        provenance: str = "assumption",
        source: str | None = None,
        unit: str | None = None,
        minimum: float | None = None,
        maximum: float | None = None,
        tunable: bool = False,
        description: str | None = None,
    ) -> Expr:
        """Declare a named parameter and return an expression referencing it.

        Passing an :class:`Expr` makes this a derived parameter: the numeric
        value is the evaluated result and the CST side keeps the expression, so
        changing an upstream parameter in CST still moves this one.
        """
        if provenance not in ir.PROVENANCE_VALUES:
            raise ValueError(f"unknown provenance {provenance!r}; expected one of {ir.PROVENANCE_VALUES}")
        if name in self._parameter_names:
            raise ValueError(f"parameter {name!r} declared twice")
        if name in self._overrides:
            value = self._override_for(name, value, tunable, minimum, maximum)
        record: dict[str, Any] = {
            "name": name,
            "value": _value(value),
            "provenance": provenance,
            "tunable": tunable,
        }
        if isinstance(value, Expr) and value.text != name:
            record["expression"] = value.text
        if unit is not None:
            record["unit"] = unit
        elif not isinstance(value, Expr):
            record["unit"] = self._units.get("length")
        if source is not None:
            record["source"] = source
        if minimum is not None:
            record["min"] = float(minimum)
        if maximum is not None:
            record["max"] = float(maximum)
        if description is not None:
            record["description"] = description
        self._parameters.append(record)
        self._parameter_names.add(name)
        return Expr(name, record["value"], _ATOM)

    def _override_for(
        self,
        name: str,
        declared: Numeric,
        tunable: bool,
        minimum: float | None,
        maximum: float | None,
    ) -> float:
        """Substitute a caller-supplied value for a declared parameter's default.

        A tuning candidate is the same device with different numbers, not a different
        device: ``topology_hash`` replaces parameter values with placeholders, so a model
        built through here still hashes to the intent it was screened as.  That is what
        makes an override the right way to freeze a swept candidate, rather than editing
        the literal in the model script and losing the connection to the printed board.

        The three refusals below are the reason this lives in the builder instead of in
        each model script.  Only the builder sees a parameter's declared range, so only
        it can tell a candidate inside the approved envelope from one outside it; and
        only it knows which names exist, so only it can tell a real override from a
        typo that would otherwise silently build the default and be reported as tuned.
        """
        supplied = self._overrides[name]
        if isinstance(declared, Expr):
            raise ValueError(
                f"cannot override {name!r}: it is derived from "
                f"{declared.text!r}, so overriding it would leave the expression CST "
                f"evaluates disagreeing with the value recorded here.  Override the "
                f"parameters it is derived from instead."
            )
        if isinstance(supplied, Expr):
            raise ValueError(f"override for {name!r} must be a number, not an expression")
        if not tunable:
            raise ValueError(
                f"cannot override {name!r}: it is not declared tunable.  A value fixed by "
                f"the substrate, the source document, or the port definition is not a "
                f"tuning knob, and changing it silently would misreport what was tuned."
            )
        supplied = float(supplied)
        if minimum is not None and supplied < minimum:
            raise ValueError(
                f"override {name}={supplied} is below the declared minimum {minimum}"
            )
        if maximum is not None and supplied > maximum:
            raise ValueError(
                f"override {name}={supplied} is above the declared maximum {maximum}"
            )
        self._overridden[name] = supplied
        return supplied

    def derived_param(self, name: str, value: Expr, **kwargs: Any) -> Expr:
        kwargs.setdefault("provenance", "synthesized")
        return self.param(name, value, **kwargs)

    # ------------------------------------------------------------ materials

    def material(
        self,
        name: str,
        kind: str = "normal",
        epsilon: Numeric | str | None = None,
        mu: Numeric | str | None = None,
        tan_delta: Numeric | str | None = None,
        conductivity: Numeric | str | None = None,
        color: tuple[int, int, int] | None = None,
        note: str | None = None,
    ) -> str:
        def encode(item: Any) -> Any:
            if item is None or isinstance(item, str):
                return item
            return as_expr(item).text if isinstance(item, Expr) else float(item)

        record: dict[str, Any] = {"name": name, "kind": kind}
        for key, item in (
            ("epsilon", epsilon),
            ("mu", mu),
            ("tan_delta", tan_delta),
            ("conductivity", conductivity),
        ):
            encoded = encode(item)
            if encoded is not None:
                record[key] = encoded
        if color is not None:
            record["color"] = list(color)
        if note is not None:
            record["note"] = note
        self._materials.append(record)
        return name

    # -------------------------------------------------------------- stackup

    def layer(
        self,
        name: str,
        z0: Numeric,
        z1: Numeric,
        material: str,
        role: str = "signal",
        note: str | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "name": name,
            "z0": _value(z0),
            "z1": _value(z1),
            "material": material,
            "role": role,
        }
        if note is not None:
            record["note"] = note
        self._stackup.append(record)
        self._layers[name] = {**record, "z0_expr": as_expr(z0), "z1_expr": as_expr(z1)}
        return record

    # ----------------------------------------------------------------- nets

    def net(
        self,
        name: str,
        layer: str,
        net_class: str = "signal",
        material: str | None = None,
        color: tuple[int, int, int] | None = None,
        note: str | None = None,
    ) -> NetBuilder:
        if layer not in self._layers:
            raise ValueError(f"layer {layer!r} must be declared before net {name!r}")
        record: dict[str, Any] = {
            "name": name,
            "layer": layer,
            "net_class": net_class,
            "solids": [],
        }
        if material is not None:
            record["material"] = material
        if color is not None:
            record["color"] = list(color)
        if note is not None:
            record["note"] = note
        self._nets.append(record)
        return NetBuilder(self, record, self._layers[layer])

    # ---------------------------------------------------------------- ports

    def port(
        self,
        name: str,
        number: int,
        net: str,
        orientation: str,
        x0: Numeric,
        y0: Numeric,
        z0: Numeric,
        x1: Numeric,
        y1: Numeric,
        z1: Numeric,
        kind: str = "waveguide",
        reference_net: str | None = None,
        impedance: float | None = 50.0,
        modes: int = 1,
        on_boundary: bool = True,
        label: str | None = None,
    ) -> dict[str, Any]:
        corners = {"x0": x0, "y0": y0, "z0": z0, "x1": x1, "y1": y1, "z1": z1}
        record: dict[str, Any] = {
            "name": name,
            "number": int(number),
            "kind": kind,
            "net": net,
            "orientation": orientation,
            "on_boundary": on_boundary,
            "modes": int(modes),
            "extent": {key: _value(item) for key, item in corners.items()},
            "expressions": {key: _text(item) for key, item in corners.items()},
        }
        if reference_net is not None:
            record["reference_net"] = reference_net
        if impedance is not None:
            record["impedance"] = float(impedance)
        if label is not None:
            record["label"] = label
        self._ports.append(record)
        return record

    # ----------------------------------------------------------- boundaries

    def boundaries(
        self,
        xmin: str = "open",
        xmax: str = "open",
        ymin: str = "open",
        ymax: str = "open",
        zmin: str = "open",
        zmax: str = "open",
        symmetry: dict[str, str] | None = None,
        open_space: dict[str, Numeric] | None = None,
        background: dict[str, Any] | None = None,
    ) -> None:
        self._boundaries = {
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
            "zmin": zmin,
            "zmax": zmax,
        }
        if symmetry:
            self._boundaries["symmetry"] = dict(symmetry)
        if open_space:
            self._boundaries["open_space"] = {
                key: (item.text if isinstance(item, Expr) else float(item)) for key, item in open_space.items()
            }
        if background:
            self._boundaries["background"] = dict(background)

    # ----------------------------------------------------------------- mesh

    def mesh(
        self,
        kind: str = "tetrahedral",
        steps_per_wavelength_near: float | None = None,
        cells_per_max_cell_near: float | None = None,
        min_cell_fraction: float | None = None,
        local_refinements: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        record: dict[str, Any] = {"kind": kind}
        if steps_per_wavelength_near is not None:
            record["steps_per_wavelength_near"] = float(steps_per_wavelength_near)
        if cells_per_max_cell_near is not None:
            record["cells_per_max_cell_near"] = float(cells_per_max_cell_near)
        if min_cell_fraction is not None:
            record["min_cell_fraction"] = float(min_cell_fraction)
        if local_refinements is not None:
            record["local_refinements"] = [dict(item) for item in local_refinements]
        self._mesh_hints = record

    # ---------------------------------------------------------- design rules

    def rule(
        self,
        rule_id: str,
        rule: str,
        scope: str,
        severity: str = "error",
        note: str | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {"id": rule_id, "rule": rule, "scope": scope, "severity": severity}
        if params:
            record["params"] = {
                key: (item.value if isinstance(item, Expr) else item) for key, item in params.items()
            }
        if note is not None:
            record["note"] = note
        self._design_rules.append(record)
        return record

    # ------------------------------------------------------------ simulation

    def simulation(
        self,
        solver: str,
        frequency_min: Numeric,
        frequency_max: Numeric,
        frequency_center: Numeric | None = None,
        convergence: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
        monitors: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        def encode(item: Numeric | None) -> Any:
            if item is None:
                return None
            return item.text if isinstance(item, Expr) else float(item)

        record: dict[str, Any] = {
            "solver": solver,
            "frequency": {"min": encode(frequency_min), "max": encode(frequency_max)},
        }
        center = encode(frequency_center)
        if center is not None:
            record["frequency"]["center"] = center
        if convergence:
            record["convergence"] = dict(convergence)
        if settings:
            record["settings"] = dict(settings)
        if monitors:
            record["monitors"] = [dict(item) for item in monitors]
        self._simulation = record

    # --------------------------------------------------------------- derived

    def derive(self, key: str, value: Any) -> None:
        self._derived[key] = _value(value) if isinstance(value, Expr) else value

    # ----------------------------------------------------------------- build

    def build(self) -> dict[str, Any]:
        unused = sorted(set(self._overrides) - set(self._overridden))
        if unused:
            raise ValueError(
                f"overrides name parameters this model never declares: {unused}.  "
                f"Declared parameters are: {sorted(self._parameter_names)}"
            )
        document: dict[str, Any] = {
            "schema_version": ir.SCHEMA_VERSION,
            "model_intent_id": "0" * 64,
            "model_id": self._model_id,
            "units": dict(self._units),
            "parameters": list(self._parameters),
            "materials": list(self._materials),
            "stackup": [{k: v for k, v in layer.items()} for layer in self._stackup],
            "nets": list(self._nets),
        }
        if self._title is not None:
            document["title"] = self._title
        if self._description is not None:
            document["description"] = self._description
        if self._source:
            document["source"] = dict(self._source)
        if self._ports:
            document["ports"] = list(self._ports)
        if self._boundaries:
            document["boundaries"] = dict(self._boundaries)
        if self._mesh_hints:
            document["mesh_hints"] = dict(self._mesh_hints)
        if self._design_rules:
            document["design_rules"] = list(self._design_rules)
        if self._simulation:
            document["simulation"] = dict(self._simulation)
        if self._derived:
            document["derived"] = dict(self._derived)
        return ir.stamp(document)
