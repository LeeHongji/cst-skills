"""The four data contracts of the topic-driven architecture.

``topic.md``       a research theme, bounded by shared physics
``design.md``      one device, with machine-readable acceptance gates
``attempt.json``   one approved topology, with approved parameter ranges
``iterations.jsonl`` append-only single source of truth for what was run

Two of them are Markdown with YAML frontmatter and two are JSON, and the split is
deliberate: topics and designs are written and read by people, so their prose body
matters and lives beside the machine-readable header; attempts and iterations are
written by the loop and read by tooling.

Together these replace eight of the nine schemas the project accumulated
(``geometry-ir`` stays, as the design-first source of truth for geometry).  The
old schema files are still present because their writers are still live -- the
experiment/trial/validation records are produced by :mod:`cst_lab.operations`,
which the tool facade replaces in step 4.  Removing the schemas before their
writers would break the running plane, so supersession is recorded in the schema
files themselves and the deletion happens with the writers.
"""

from __future__ import annotations

from .attempt import (
    ApprovalError,
    RangeViolation,
    TopologyMismatch,
    check_parameters,
    check_topology,
    default_ranges,
    load_attempt,
    require_approval,
    write_attempt,
)
from .design import DERIVED_METRICS, Derived, Gate, load_design, parse_gates, write_design
from .frontmatter import FrontmatterError, read_frontmatter, split_frontmatter, write_frontmatter
from .gates import GateReport, GateResult, evaluate_gate, evaluate_gates
from .iterations import append_iteration, iteration_line, next_iteration_number, read_iterations
from .topic import load_topic, write_topic
from .touchstone import (
    Touchstone,
    amplitude_imbalance_db,
    curve,
    phase_difference_deg,
    read_touchstone,
)

__all__ = [
    "DERIVED_METRICS",
    "ApprovalError",
    "Derived",
    "FrontmatterError",
    "Gate",
    "GateReport",
    "GateResult",
    "RangeViolation",
    "TopologyMismatch",
    "Touchstone",
    "amplitude_imbalance_db",
    "append_iteration",
    "check_parameters",
    "check_topology",
    "curve",
    "default_ranges",
    "evaluate_gate",
    "evaluate_gates",
    "iteration_line",
    "load_attempt",
    "load_design",
    "load_topic",
    "next_iteration_number",
    "parse_gates",
    "phase_difference_deg",
    "read_frontmatter",
    "read_iterations",
    "read_touchstone",
    "require_approval",
    "split_frontmatter",
    "write_attempt",
    "write_design",
    "write_frontmatter",
    "write_topic",
]
