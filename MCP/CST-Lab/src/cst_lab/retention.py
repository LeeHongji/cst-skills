"""Declarative storage-retention policy for CST run workspaces.

Every rule that decides "is this file permanent evidence, a recomputable solver
cache, or disposable scratch" lives in this module. Callers must not re-derive
classification from suffixes inline; they ask :class:`RetentionPolicy`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Any, Iterable

EVIDENCE = "evidence"
REGENERABLE = "regenerable"
SCRATCH = "scratch"
UNCLASSIFIED = "unclassified"

RETENTION_CLASSES = (EVIDENCE, REGENERABLE, SCRATCH, UNCLASSIFIED)

# Run workspaces owned by another concurrent workstream. They are excluded from
# indexing, inventory, and every reclamation decision.
RESERVED_RUN_DIRECTORIES: frozenset[str] = frozenset()
RESERVED_RUN_PREFIXES: tuple[str, ...] = ("cst-cad-phase1-verification",)

TERMINAL_TRIAL_STATUSES = frozenset(
    {"completed", "partial", "invalid", "failed", "pruned", "cancelled"}
)
TERMINAL_EXPERIMENT_STATUSES = frozenset(
    {"completed", "partial", "invalid", "failed", "cancelled"}
)

# Suffix -> semantic artifact type. Used for reporting and for Brain/case links.
ARTIFACT_TYPES: dict[str, str] = {
    ".cst": "cst-project",
    ".s2p": "touchstone",
    ".s1p": "touchstone",
    ".s4p": "touchstone",
    ".csv": "curve-export",
    ".txt": "text-export",
    ".json": "structured-record",
    ".png": "plot-image",
    ".svg": "plot-image",
    ".pdf": "document",
    ".md": "report-markdown",
    ".py": "analysis-script",
    ".vba": "history-script",
    ".bas": "history-script",
    ".err": "solver-error-log",
    ".tra": "solver-trace-log",
    ".out": "solver-log",
    ".log": "solver-log",
    ".rom": "solver-matrix-cache",
    ".m3t": "field-monitor-cache",
    ".m3d": "field-monitor-cache",
    ".fsf": "field-source-cache",
    ".scf": "solver-cache",
    ".sct": "solver-cache",
    ".slim": "solver-cache",
    ".slv": "solver-cache",
    ".sdb": "solver-database",
    ".db": "solver-database",
    ".dib": "preview-bitmap",
    ".tet": "mesh-cache",
    ".sab": "acis-geometry-cache",
    ".pmi": "solver-cache",
    ".parmap": "solver-cache",
    ".fmp": "solver-cache",
    ".fct": "solver-cache",
    ".docstore": "settings-store",
    ".mat": "solver-matrix-cache",
    ".lok": "lock",
    ".tmp": "scratch-temp",
    ".bak": "scratch-backup",
}


@dataclass(frozen=True)
class Classification:
    """Result of classifying one file inside a run workspace."""

    retention_class: str
    artifact_type: str
    reason: str
    hash_required: bool
    deletable: bool


@dataclass(frozen=True)
class RetentionPolicy:
    """Configurable retention rules. Construct via :meth:`default`."""

    policy_version: str

    evidence_suffixes: frozenset[str]
    evidence_filenames: frozenset[str]
    regenerable_suffixes: frozenset[str]
    regenerable_directories: frozenset[str]
    scratch_suffixes: frozenset[str]
    scratch_directories: frozenset[str]

    # Files that are never removed even when their class is otherwise disposable.
    never_delete_suffixes: frozenset[str]
    # Presence of any of these suffixes inside a unit blocks reclamation of that unit.
    lock_guard_suffixes: frozenset[str]

    # Only these classes are hashed; large recomputable caches are tracked by
    # (size, mtime) because a digest of a cache nobody will restore is waste.
    hash_classes: frozenset[str]
    hash_max_bytes: int

    reclaimable_classes: frozenset[str]

    # Evidence filenames that satisfy the "run has reviewable evidence" gate.
    evidence_gate_suffixes: frozenset[str]
    evidence_gate_filenames: frozenset[str]

    # Path tokens that mark a trial or working copy as a selected/confirmation
    # candidate whose solver results must be preserved.
    protected_path_tokens: frozenset[str]

    terminal_trial_statuses: frozenset[str] = TERMINAL_TRIAL_STATUSES
    terminal_experiment_statuses: frozenset[str] = TERMINAL_EXPERIMENT_STATUSES

    # Top-level cst_runs entries that this plane must not index, plan, or touch
    # because another workstream owns them.
    reserved_run_directories: frozenset[str] = field(default_factory=frozenset)
    reserved_run_prefixes: tuple[str, ...] = ()

    @classmethod
    def default(cls) -> "RetentionPolicy":
        return cls(
            policy_version="2026-09-10.1",
            evidence_suffixes=frozenset(
                {
                    ".cst",
                    ".s1p",
                    ".s2p",
                    ".s4p",
                    ".csv",
                    ".json",
                    ".png",
                    ".svg",
                    ".err",
                    ".tra",
                    ".vba",
                    ".bas",
                    ".md",
                    ".py",
                    ".txt",
                    ".pdf",
                }
            ),
            evidence_filenames=frozenset(
                {
                    "trial.json",
                    "experiment.json",
                    "case-handoff.json",
                    "validation.json",
                    "metrics.json",
                    "objectives.json",
                    "constraints.json",
                    "cases.json",
                    "parameters.json",
                    "modelhistory.json",
                }
            ),
            regenerable_suffixes=frozenset(
                {
                    ".rom",
                    ".m3t",
                    ".fsf",
                    ".scf",
                    ".slim",
                    ".sdb",
                    ".dib",
                    ".sct",
                    ".tet",
                    ".m3d",
                    ".slv",
                    ".sab",
                    ".db",
                    ".pmi",
                    ".parmap",
                    ".fmp",
                    ".fct",
                    ".docstore",
                    ".mat",
                }
            ),
            regenerable_directories=frozenset({"result"}),
            scratch_suffixes=frozenset({".lok", ".lck", ".tmp", ".bak"}),
            scratch_directories=frozenset({"temp"}),
            never_delete_suffixes=frozenset({".cst", ".lok", ".lck"}),
            lock_guard_suffixes=frozenset({".lok", ".lck"}),
            hash_classes=frozenset({EVIDENCE}),
            hash_max_bytes=64 * 1024 * 1024,
            reclaimable_classes=frozenset({REGENERABLE, SCRATCH}),
            evidence_gate_suffixes=frozenset({".s1p", ".s2p", ".s4p", ".csv"}),
            evidence_gate_filenames=frozenset(
                {"metrics.json", "filter-response-summary.json", "analysis.json"}
            ),
            protected_path_tokens=frozenset(
                {
                    "selected",
                    "confirm",
                    "confirmed",
                    "confirmation",
                    "best",
                    "golden",
                    "final",
                    "protected",
                    "reference",
                    "delivery",
                }
            ),
            reserved_run_directories=frozenset(RESERVED_RUN_DIRECTORIES),
            reserved_run_prefixes=RESERVED_RUN_PREFIXES,
        )

    def with_reserved(
        self, names: Iterable[str] = (), *, prefixes: Iterable[str] = ()
    ) -> "RetentionPolicy":
        merged = frozenset(self.reserved_run_directories) | {
            name.casefold() for name in names
        }
        merged_prefixes = tuple(
            dict.fromkeys(
                self.reserved_run_prefixes + tuple(item.casefold() for item in prefixes)
            )
        )
        return replace(
            self, reserved_run_directories=merged, reserved_run_prefixes=merged_prefixes
        )

    def is_reserved(self, top_level_name: str) -> bool:
        lowered = top_level_name.casefold()
        if lowered in self.reserved_run_directories:
            return True
        return any(lowered.startswith(prefix) for prefix in self.reserved_run_prefixes)

    def artifact_type(self, relative: PurePosixPath) -> str:
        return ARTIFACT_TYPES.get(relative.suffix.casefold(), "unknown")

    def classify(self, relative: PurePosixPath, *, size_bytes: int = 0) -> Classification:
        """Classify a file by its path relative to the ``cst_runs`` root."""

        suffix = relative.suffix.casefold()
        name = relative.name.casefold()
        parts = {part.casefold() for part in relative.parts[:-1]}
        artifact_type = self.artifact_type(relative)
        never_delete = suffix in self.never_delete_suffixes

        if suffix in self.scratch_suffixes:
            return Classification(
                SCRATCH,
                artifact_type,
                f"scratch suffix {suffix}",
                hash_required=False,
                deletable=not never_delete,
            )

        if parts & self.scratch_directories:
            return Classification(
                SCRATCH,
                artifact_type,
                "inside a solver Temp/ directory",
                hash_required=False,
                deletable=not never_delete,
            )

        if name in self.evidence_filenames or suffix in self.evidence_suffixes:
            reason = (
                f"evidence filename {name}"
                if name in self.evidence_filenames
                else f"evidence suffix {suffix}"
            )
            hash_required = (
                EVIDENCE in self.hash_classes and size_bytes <= self.hash_max_bytes
            )
            return Classification(
                EVIDENCE, artifact_type, reason, hash_required=hash_required, deletable=False
            )

        if suffix in self.regenerable_suffixes and (parts & self.regenerable_directories):
            return Classification(
                REGENERABLE,
                artifact_type,
                f"recomputable solver cache {suffix} under Result/",
                hash_required=REGENERABLE in self.hash_classes,
                deletable=not never_delete,
            )

        return Classification(
            UNCLASSIFIED,
            artifact_type,
            "no rule matched; retained by default",
            hash_required=UNCLASSIFIED in self.hash_classes,
            deletable=False,
        )

    def satisfies_evidence_gate(self, relative: PurePosixPath) -> bool:
        return (
            relative.suffix.casefold() in self.evidence_gate_suffixes
            or relative.name.casefold() in self.evidence_gate_filenames
        )

    def has_lock_guard(self, relative: PurePosixPath) -> bool:
        return relative.suffix.casefold() in self.lock_guard_suffixes

    def is_protected_path(self, text: str) -> str | None:
        lowered = text.casefold()
        for token in sorted(self.protected_path_tokens):
            if token in lowered:
                return token
        return None

    def describe(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "evidence_suffixes": sorted(self.evidence_suffixes),
            "evidence_filenames": sorted(self.evidence_filenames),
            "regenerable_suffixes": sorted(self.regenerable_suffixes),
            "regenerable_directories": sorted(self.regenerable_directories),
            "scratch_suffixes": sorted(self.scratch_suffixes),
            "scratch_directories": sorted(self.scratch_directories),
            "never_delete_suffixes": sorted(self.never_delete_suffixes),
            "hash_classes": sorted(self.hash_classes),
            "hash_max_bytes": self.hash_max_bytes,
            "reclaimable_classes": sorted(self.reclaimable_classes),
            "terminal_trial_statuses": sorted(self.terminal_trial_statuses),
            "terminal_experiment_statuses": sorted(self.terminal_experiment_statuses),
            "reserved_run_directories": sorted(self.reserved_run_directories),
        }


# Ordered, data-driven project-family rules. First match wins.
@dataclass(frozen=True)
class FamilyRule:
    family_id: str
    title: str
    directory_prefixes: tuple[str, ...] = ()
    directory_tokens: tuple[str, ...] = ()
    model_tokens: tuple[str, ...] = ()
    source_roots: tuple[str, ...] = ()


FAMILY_RULES: tuple[FamilyRule, ...] = (
    FamilyRule(
        family_id="fig15-filter-d-dual-mode-microstrip",
        title="Fig. 15 Filter D dual-mode microstrip bandpass filter",
        directory_prefixes=("fig15", "fig-15", "dual_mode_open_loop_fig15"),
        directory_tokens=("fig15", "filter-d", "filter_d"),
        model_tokens=("fig15", "fourgap", "four_mode", "four_pole", "output_finger"),
    ),
    FamilyRule(
        family_id="fig7-filter-a-dual-mode-open-loop",
        title="Fig. 7 Filter A dual-mode open-loop resonator filter",
        directory_prefixes=("dual_mode_open_loop_fig7", "fig7", "fig-7"),
        directory_tokens=("fig7", "filter-a", "filter_a"),
        model_tokens=("fig7", "filter_a"),
    ),
    FamilyRule(
        family_id="phase-shifter-3ghz-filtering",
        title="3 GHz filtering differential phase shifter",
        directory_prefixes=("3-ghz", "3ghz", "90deg-filtering-phase-shifter"),
        directory_tokens=("phase-shifter", "phase_shifter", "filtering-phase"),
        model_tokens=(
            "phase_shifter",
            "four_port",
            "folded_four_port",
            "tri_pole",
            "dual_branch",
            "combined_four_port",
        ),
    ),
    FamilyRule(
        family_id="hairpin-5p8ghz-three-pole",
        title="5.8 GHz three-pole planar hairpin filter",
        directory_prefixes=("5-8-ghz", "5p8ghz", "official-cst-2026-bandpass-filter-hairpin"),
        directory_tokens=("hairpin", "three-pole", "three_pole"),
        model_tokens=("hairpin", "three_pole", "5p8"),
    ),
    FamilyRule(
        family_id="oam-uca-3p5ghz",
        title="3.5 GHz OAM uniform circular array reproduction",
        directory_prefixes=(
            "oam-uca",
            "four-element-3-5-ghz-oam",
            "eight-element-3-5-ghz-oam",
            "3-5-ghz-paper-patch-calibration",
        ),
        directory_tokens=("oam", "uca"),
        model_tokens=("oam", "uca"),
    ),
    FamilyRule(
        family_id="golden-corpus-cst-samples",
        title="Golden corpus: CST Studio Suite official sample projects",
        directory_prefixes=(
            "axial-mode-helix",
            "corporate-fed-patch-array",
            "pin-fed-patch-antenna",
            "planar-filter",
            "planar_filter_reconstruction",
        ),
        directory_tokens=("baseline-validation", "fresh-solve", "resonance-move"),
        model_tokens=(
            "helix",
            "patch",
            "planar_filter",
            "planar filter",
            "bandpass filter quadruplet",
            "planar_phase_shifter",
        ),
        source_roots=("c:\\cst-program",),
    ),
)

UNASSIGNED_FAMILY = "unassigned"
