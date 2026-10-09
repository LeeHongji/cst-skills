"""Retention engine: plan and (only when explicitly authorised) execute reclamation.

The planner is the product here. It converts the artifact catalog plus Lab
lifecycle state into per-unit decisions with an auditable release reason, and it
refuses to release anything that cannot prove both of the hard preconditions:

1. the owning trial (or experiment, when a working copy sits outside a trial)
   reached a terminal state, and
2. at least one ``evidence`` class artifact exists in that lifecycle scope.

Selected / confirmation / best-objective candidates are force-retained, and any
unit containing a CST ``.lok`` file is skipped because the project may be open.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from .files import atomic_write_json
from .paths import LabPaths, long_path
from .registry import LabRegistry
from .retention import (
    EVIDENCE,
    REGENERABLE,
    SCRATCH,
    UNASSIGNED_FAMILY,
    UNCLASSIFIED,
    RetentionPolicy,
)
from .artifacts import run_uri

CST_RUNS_REFERENCE = re.compile(r"cst_runs[\\/]([^\s\"'`*?<>|\)\],;]+)", re.IGNORECASE)

BLOCK_NO_OWNER = "no-lab-lifecycle-owner"
BLOCK_NON_TERMINAL = "owner-not-in-terminal-state"
BLOCK_NO_EVIDENCE = "no-evidence-artifact-in-lifecycle-scope"
BLOCK_PROTECTED = "selected-or-confirmation-candidate"
BLOCK_LOCK = "cst-lock-file-present"

RELEASE_REASON = "terminal-owner-plus-exported-evidence"


def unit_key(run_path: str, policy: RetentionPolicy) -> str:
    """Reclaim unit for a file: the CST working copy that owns the cache."""

    parts = PurePosixPath(run_path).parts
    for index, part in enumerate(parts[:-1]):
        lowered = part.casefold()
        if lowered in policy.regenerable_directories or lowered in policy.scratch_directories:
            return "/".join(parts[:index])
    return "/".join(parts[:-1])


@dataclass
class ReclaimUnit:
    unit_path: str
    run_directory: str
    owner_kind: str
    trial_id: str | None
    experiment_id: str | None
    owner_status: str | None
    owner_scope: str | None
    project_family: str = UNASSIGNED_FAMILY
    reclaimable_files: list[dict[str, Any]] = field(default_factory=list)
    retained_bytes: int = 0
    retained_files: int = 0
    class_bytes: dict[str, int] = field(default_factory=dict)
    has_lock: bool = False
    lock_paths: list[str] = field(default_factory=list)
    protection: list[str] = field(default_factory=list)

    @property
    def reclaimable_bytes(self) -> int:
        return sum(item["size_bytes"] for item in self.reclaimable_files)


class RetentionCollector:
    def __init__(
        self,
        paths: LabPaths,
        registry: LabRegistry,
        policy: RetentionPolicy,
    ) -> None:
        self.paths = paths
        self.registry = registry
        self.policy = policy

    @property
    def runs_root(self) -> Path:
        return self.paths.runs_root

    # ----------------------------------------------------------------- planning

    def plan(
        self,
        *,
        families: Iterable[str] | None = None,
        run_directory: str | None = None,
        max_bytes: int | None = None,
        protect_best_per_experiment: bool = False,
    ) -> dict[str, Any]:
        rows = self._catalog_rows()
        if not rows:
            raise RuntimeError(
                "Artifact catalog is empty. Run 'cst-lab index-artifacts' before planning."
            )
        lifecycle = self.registry.lifecycle_run_paths()
        statuses = self._owner_statuses(lifecycle)
        families_by_directory = self._families_by_directory()
        protected = self._protected_scopes(
            rows, lifecycle, include_tier_b=protect_best_per_experiment
        )
        evidence_scopes = self._evidence_scopes(rows)

        units: dict[str, ReclaimUnit] = {}
        for row in rows:
            if self.policy.is_reserved(row["run_directory"]):
                continue
            key = unit_key(row["run_path"], self.policy)
            unit = units.get(key)
            if unit is None:
                unit = ReclaimUnit(
                    unit_path=key,
                    run_directory=row["run_directory"],
                    owner_kind=row["owner_kind"],
                    trial_id=row["trial_id"],
                    experiment_id=row["experiment_id"],
                    owner_status=None,
                    owner_scope=None,
                    project_family=families_by_directory.get(
                        row["run_directory"], UNASSIGNED_FAMILY
                    ),
                )
                units[key] = unit
            if unit.trial_id is None and row["trial_id"]:
                unit.trial_id = row["trial_id"]
                unit.owner_kind = "trial"
            if unit.experiment_id is None and row["experiment_id"]:
                unit.experiment_id = row["experiment_id"]

            relative = PurePosixPath(row["run_path"])
            retention_class = row["retention_class"]
            unit.class_bytes[retention_class] = (
                unit.class_bytes.get(retention_class, 0) + row["size_bytes"]
            )
            if self.policy.has_lock_guard(relative):
                unit.has_lock = True
                unit.lock_paths.append(row["run_path"])
            deletable = (
                retention_class in self.policy.reclaimable_classes
                and relative.suffix.casefold() not in self.policy.never_delete_suffixes
            )
            if deletable:
                unit.reclaimable_files.append(
                    {
                        "artifact_id": row["artifact_id"],
                        "run_path": row["run_path"],
                        "run_uri": run_uri(row["run_path"]),
                        "retention_class": retention_class,
                        "artifact_type": row["artifact_type"],
                        "size_bytes": row["size_bytes"],
                        "mtime": row["mtime"],
                        "sha256": row["sha256"],
                        "classification_reason": row["classification_reason"],
                    }
                )
            else:
                unit.retained_bytes += row["size_bytes"]
                unit.retained_files += 1

        decisions: list[dict[str, Any]] = []
        for key in sorted(units):
            unit = units[key]
            if not unit.reclaimable_files:
                continue
            if run_directory and unit.run_directory.casefold() != run_directory.casefold():
                continue
            if families and unit.project_family not in set(families):
                continue
            decisions.append(
                self._decide(unit, statuses, protected, evidence_scopes)
            )

        decisions.sort(key=lambda item: -item["reclaimable_bytes"])
        released, budget_deferred = self._apply_budget(decisions, max_bytes)
        summary = self._summarize(decisions, released, budget_deferred, max_bytes, families, rows)
        summary["filters"]["protect_best_per_experiment"] = protect_best_per_experiment
        return summary

    def _decide(
        self,
        unit: ReclaimUnit,
        statuses: dict[str, dict[str, Any]],
        protected: dict[str, list[str]],
        evidence_scopes: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        blocks: list[str] = []
        notes: list[str] = []

        owner_status: str | None = None
        owner_scope: str | None = None
        if unit.trial_id and unit.trial_id in statuses:
            record = statuses[unit.trial_id]
            owner_status = record["status"]
            owner_scope = record["scope"]
            if owner_status not in self.policy.terminal_trial_statuses:
                blocks.append(BLOCK_NON_TERMINAL)
        elif unit.experiment_id and unit.experiment_id in statuses:
            record = statuses[unit.experiment_id]
            owner_status = record["status"]
            owner_scope = record["scope"]
            if owner_status not in self.policy.terminal_experiment_statuses:
                blocks.append(BLOCK_NON_TERMINAL)
        else:
            blocks.append(BLOCK_NO_OWNER)

        evidence_key = owner_scope or unit.run_directory.casefold()
        evidence = evidence_scopes.get(evidence_key, [])
        if not evidence:
            fallback = evidence_scopes.get(unit.run_directory.casefold(), [])
            if fallback:
                evidence = fallback
                notes.append("evidence found at run-directory scope, not lifecycle scope")
        if not evidence:
            blocks.append(BLOCK_NO_EVIDENCE)

        protection = list(unit.protection)
        inner = unit.unit_path[len(unit.run_directory) :].lstrip("/")
        token = self.policy.is_protected_path(inner) if inner else None
        if token:
            protection.append(f"path-token:{token}")
        for scope, reasons in protected.items():
            if unit.unit_path.casefold() == scope or unit.unit_path.casefold().startswith(
                f"{scope}/"
            ):
                protection.extend(reasons)
        protection = sorted(set(protection))
        if protection:
            blocks.append(BLOCK_PROTECTED)

        if unit.has_lock:
            blocks.append(BLOCK_LOCK)

        blocks = sorted(set(blocks))
        return {
            "unit_path": unit.unit_path,
            "unit_uri": run_uri(unit.unit_path),
            "run_directory": unit.run_directory,
            "project_family": unit.project_family,
            "owner_kind": unit.owner_kind,
            "trial_id": unit.trial_id,
            "experiment_id": unit.experiment_id,
            "owner_status": owner_status,
            "owner_scope": owner_scope,
            "decision": "retain" if blocks else "release",
            "block_reasons": blocks,
            "release_reason": None if blocks else RELEASE_REASON,
            "protection_signals": protection,
            "lock_paths": unit.lock_paths,
            "notes": notes,
            "evidence_artifacts": [item["run_uri"] for item in evidence[:5]],
            "evidence_artifact_count": len(evidence),
            "reclaimable_bytes": unit.reclaimable_bytes,
            "reclaimable_files": len(unit.reclaimable_files),
            "retained_bytes": unit.retained_bytes,
            "retained_files": unit.retained_files,
            "class_bytes": unit.class_bytes,
            "regeneration_inputs": self._regeneration_inputs(unit),
            "files": unit.reclaimable_files,
        }

    def _apply_budget(
        self, decisions: list[dict[str, Any]], max_bytes: int | None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        released: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        spent = 0
        for decision in decisions:
            if decision["decision"] != "release":
                continue
            if max_bytes is not None and spent + decision["reclaimable_bytes"] > max_bytes:
                decision["decision"] = "deferred"
                decision["block_reasons"] = ["max-bytes-budget-exhausted"]
                deferred.append(decision)
                continue
            spent += decision["reclaimable_bytes"]
            released.append(decision)
        return released, deferred

    def _summarize(
        self,
        decisions: list[dict[str, Any]],
        released: list[dict[str, Any]],
        deferred: list[dict[str, Any]],
        max_bytes: int | None,
        families: Iterable[str] | None,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        retained = [item for item in decisions if item["decision"] == "retain"]
        blocked_counts: dict[str, int] = {}
        blocked_bytes: dict[str, int] = {}
        signal_counts: dict[str, int] = {}
        signal_bytes: dict[str, int] = {}
        for item in retained:
            for reason in item["block_reasons"]:
                blocked_counts[reason] = blocked_counts.get(reason, 0) + 1
                blocked_bytes[reason] = blocked_bytes.get(reason, 0) + item["reclaimable_bytes"]
            for signal in item["protection_signals"]:
                key = ":".join(signal.split(":")[:2])
                signal_counts[key] = signal_counts.get(key, 0) + 1
                signal_bytes[key] = signal_bytes.get(key, 0) + item["reclaimable_bytes"]

        by_family: dict[str, dict[str, Any]] = {}
        for item in decisions:
            bucket = by_family.setdefault(
                item["project_family"],
                {
                    "project_family": item["project_family"],
                    "units": 0,
                    "release_units": 0,
                    "retain_units": 0,
                    "releasable_bytes": 0,
                    "blocked_bytes": 0,
                },
            )
            bucket["units"] += 1
            if item["decision"] == "release":
                bucket["release_units"] += 1
                bucket["releasable_bytes"] += item["reclaimable_bytes"]
            else:
                bucket["retain_units"] += 1
                bucket["blocked_bytes"] += item["reclaimable_bytes"]

        catalog_bytes = sum(row["size_bytes"] for row in rows)
        releasable_bytes = sum(item["reclaimable_bytes"] for item in released)
        by_class: dict[str, int] = {}
        for item in released:
            for record in item["files"]:
                by_class[record["retention_class"]] = (
                    by_class.get(record["retention_class"], 0) + record["size_bytes"]
                )

        run_directories_touched = sorted({item["run_directory"] for item in released})
        return {
            "schema_version": 1,
            "generated_at": self.registry.now(),
            "runs_root": str(self.runs_root),
            "policy": self.policy.describe(),
            "filters": {
                "families": sorted(set(families)) if families else None,
                "max_bytes": max_bytes,
            },
            "totals": {
                "catalog_files": len(rows),
                "catalog_bytes": catalog_bytes,
                "units_considered": len(decisions),
                "units_released": len(released),
                "units_retained": len(retained),
                "units_deferred": len(deferred),
                "releasable_bytes": releasable_bytes,
                "releasable_files": sum(item["reclaimable_files"] for item in released),
                "blocked_reclaimable_bytes": sum(
                    item["reclaimable_bytes"] for item in retained
                ),
                "deferred_bytes": sum(item["reclaimable_bytes"] for item in deferred),
                "releasable_bytes_by_class": by_class,
                "projected_catalog_bytes_after": catalog_bytes - releasable_bytes,
                "run_directories_touched": len(run_directories_touched),
            },
            "block_reason_counts": blocked_counts,
            "block_reason_bytes": blocked_bytes,
            "protection_signal_counts": signal_counts,
            "protection_signal_bytes": signal_bytes,
            "by_project_family": sorted(
                by_family.values(), key=lambda item: -item["releasable_bytes"]
            ),
            "units": decisions,
        }

    # ------------------------------------------------------------------- inputs

    def _catalog_rows(self) -> list[dict[str, Any]]:
        connection = self.registry.connect()
        try:
            return [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT artifact_id, run_path, run_directory, retention_class,
                           artifact_type, size_bytes, mtime, sha256, owner_kind,
                           trial_id, experiment_id, classification_reason, path
                    FROM artifacts
                    """
                )
            ]
        finally:
            connection.close()

    def _owner_statuses(
        self, lifecycle: dict[str, list[dict[str, Any]]]
    ) -> dict[str, dict[str, Any]]:
        statuses: dict[str, dict[str, Any]] = {}
        for record in lifecycle["experiments"]:
            statuses[record["experiment_id"]] = {
                "status": record["status"],
                "scope": self._scope(record["run_path"]),
            }
        for record in lifecycle["trials"]:
            statuses[record["trial_id"]] = {
                "status": record["status"],
                "scope": self._scope(record["run_path"]),
            }
        return statuses

    def _scope(self, raw: str | None) -> str | None:
        if not raw:
            return None
        try:
            return Path(raw).relative_to(self.runs_root).as_posix().casefold()
        except ValueError:
            return None

    def _evidence_scopes(self, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Map every ancestor directory to the evidence artifacts beneath it."""

        scopes: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if row["retention_class"] != EVIDENCE:
                continue
            relative = PurePosixPath(row["run_path"])
            if not self.policy.satisfies_evidence_gate(relative):
                continue
            record = {"run_uri": run_uri(row["run_path"]), "artifact_type": row["artifact_type"]}
            parts = relative.parts[:-1]
            for depth in range(1, len(parts) + 1):
                key = "/".join(parts[:depth]).casefold()
                scopes.setdefault(key, []).append(record)
        return scopes

    def _families_by_directory(self) -> dict[str, str]:
        path = self.paths.registry_root / "legacy-inventory.json"
        if not path.is_file():
            return {}
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {
            item["run_directory"]: item["project_family"]
            for item in document.get("run_directories", [])
        }

    def _protected_scopes(
        self,
        rows: list[dict[str, Any]],
        lifecycle: dict[str, list[dict[str, Any]]],
        *,
        include_tier_b: bool,
    ) -> dict[str, list[str]]:
        """Scopes whose solver results must survive, with the signal that protects them.

        Tier A is always enforced: an explicit selection marker, a citation from a
        published Brain case page, or the best trial of an experiment that actually
        met its objective target. Tier B covers the best-of-batch trial of a
        screening experiment that never met its target; those runs are already
        represented by exported curves, so protecting their caches is opt-in.
        """

        protected: dict[str, list[str]] = {}

        def mark(scope: str | None, reason: str) -> None:
            if not scope:
                return
            protected.setdefault(scope.casefold(), []).append(reason)

        # Signal A1: paths cited by published Brain case pages.
        for reference in self._brain_case_references():
            mark(reference, "A:cited-by-brain-case-page")

        # Signal A2: working copies whose CST model basename carries a selection token.
        for row in rows:
            if row["artifact_type"] != "cst-project":
                continue
            relative = PurePosixPath(row["run_path"])
            token = self.policy.is_protected_path(relative.stem)
            if token:
                mark(relative.with_suffix("").as_posix(), f"A:model-basename-token:{token}")

        # Signal A3/B1: best-objective completed trial per experiment, split by
        # whether the experiment actually reached the declared target.
        trials_by_experiment: dict[str, list[dict[str, Any]]] = {}
        for record in lifecycle["trials"]:
            trials_by_experiment.setdefault(record["experiment_id"], []).append(record)
        for experiment in lifecycle["experiments"]:
            try:
                spec = json.loads(experiment["spec_json"]) if experiment["spec_json"] else {}
            except json.JSONDecodeError:
                spec = {}
            objectives = spec.get("objectives") or []
            if not objectives:
                continue
            primary = objectives[0]
            name = primary.get("name")
            direction = primary.get("direction", "minimize")
            target = primary.get("target")
            best: tuple[float, dict[str, Any]] | None = None
            for trial in trials_by_experiment.get(experiment["experiment_id"], []):
                if trial["status"] != "completed" or not trial.get("objectives_json"):
                    continue
                try:
                    values = json.loads(trial["objectives_json"])
                except json.JSONDecodeError:
                    continue
                value = values.get(name)
                if not isinstance(value, (int, float)):
                    continue
                score = -float(value) if direction == "maximize" else float(value)
                if best is None or score < best[0]:
                    best = (score, trial)
            if best is None:
                continue
            actual = -best[0] if direction == "maximize" else best[0]
            target_met = False
            if isinstance(target, (int, float)):
                target_met = (
                    actual >= float(target) if direction == "maximize" else actual <= float(target)
                )
            scope = self._scope(best[1]["run_path"])
            if target_met:
                mark(scope, f"A:best-trial-meeting-target:{best[1]['trial_id']}:{name}={actual}")
            elif include_tier_b:
                mark(scope, f"B:best-trial-below-target:{best[1]['trial_id']}:{name}={actual}")
        return {key: sorted(set(value)) for key, value in protected.items()}

    def _brain_case_references(self) -> list[str]:
        vault = self.paths.workspace_root / "brain" / "wiki" / "cases"
        if not vault.is_dir():
            return []
        found: set[str] = set()
        for path in sorted(vault.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in CST_RUNS_REFERENCE.finditer(text):
                candidate = match.group(1).replace("\\", "/").strip("/")
                if not candidate:
                    continue
                found.add(candidate.casefold())
                # A cited .cst implies its companion directory is the selected copy.
                if candidate.casefold().endswith(".cst"):
                    found.add(candidate[: -len(".cst")].casefold())
        return sorted(found)

    def _regeneration_inputs(self, unit: ReclaimUnit) -> dict[str, Any]:
        connection = self.registry.connect()
        try:
            rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT run_path, artifact_type, sha256, size_bytes
                    FROM artifacts
                    WHERE run_directory = ? AND retention_class = ?
                      AND artifact_type IN ('cst-project', 'history-script', 'structured-record')
                    ORDER BY run_path
                    """,
                    (unit.run_directory, EVIDENCE),
                )
            ]
        finally:
            connection.close()
        project = f"{unit.unit_path}.cst".casefold()
        inputs: list[dict[str, Any]] = []
        for row in rows:
            lowered = row["run_path"].casefold()
            relevant = (
                lowered == project
                or row["artifact_type"] == "history-script"
                or lowered.endswith("/parameters.json")
                or lowered.endswith("/modelhistory.json")
                or lowered.endswith("/simulationproperties.json")
                or lowered.endswith("/trial.json")
            )
            if not relevant:
                continue
            inputs.append(
                {
                    "run_uri": run_uri(row["run_path"]),
                    "artifact_type": row["artifact_type"],
                    "sha256": row["sha256"],
                    "size_bytes": row["size_bytes"],
                }
            )
        return {
            "recompute_action": "reopen the .cst working copy and re-run the recorded solver",
            "required_inputs": inputs[:12],
            "required_input_count": len(inputs),
        }

    # ------------------------------------------------------------------ reports

    def write_reports(self, plan: dict[str, Any], *, label: str = "gc-dry-run") -> dict[str, str]:
        reports = self.paths.registry_root / "reports"
        stamp = plan["generated_at"].replace(":", "").replace("-", "")
        json_path = reports / f"{label}-{stamp}.json"
        markdown_path = reports / f"{label}-{stamp}.md"
        atomic_write_json(json_path, plan)
        markdown_path.write_text(render_markdown(plan), encoding="utf-8", newline="\n")
        latest_json = reports / f"{label}-latest.json"
        latest_markdown = reports / f"{label}-latest.md"
        atomic_write_json(latest_json, plan)
        latest_markdown.write_text(render_markdown(plan), encoding="utf-8", newline="\n")
        return {
            "json": str(json_path),
            "markdown": str(markdown_path),
            "latest_json": str(latest_json),
            "latest_markdown": str(latest_markdown),
        }

    # ------------------------------------------------------------------ execute

    def execute(
        self,
        plan: dict[str, Any],
        *,
        confirm: bool = False,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Delete released files after writing an atomic reclamation manifest.

        Order matters: the manifest is fsynced to disk *before* the first unlink,
        so a crash mid-delete still leaves a record of what was removed and how
        to recompute it.
        """

        if not confirm:
            raise ValueError("execute() requires confirm=True; use --execute --confirm")
        released = [item for item in plan["units"] if item["decision"] == "release"]
        if not released:
            return {"status": "nothing-to-do", "removed_files": 0, "removed_bytes": 0}

        token = uuid.uuid4().hex[:12]
        manifest_path = (
            self.paths.registry_root / "gc-manifests" / f"{plan['generated_at'].replace(':', '')}-{token}.json"
        )
        manifest = {
            "schema_version": 1,
            "manifest_id": f"gc-{token}",
            "planned_at": plan["generated_at"],
            "executed_at": self.registry.now(),
            "runs_root": plan["runs_root"],
            "policy": plan["policy"],
            "filters": plan["filters"],
            "totals": plan["totals"],
            "units": [
                {
                    "unit_uri": item["unit_uri"],
                    "run_directory": item["run_directory"],
                    "project_family": item["project_family"],
                    "trial_id": item["trial_id"],
                    "experiment_id": item["experiment_id"],
                    "owner_status": item["owner_status"],
                    "release_reason": item["release_reason"],
                    "evidence_artifacts": item["evidence_artifacts"],
                    "regeneration_inputs": item["regeneration_inputs"],
                    "removed": item["files"],
                }
                for item in released
            ],
        }
        atomic_write_json(manifest_path, manifest)

        removed_files = 0
        removed_bytes = 0
        skipped: list[dict[str, Any]] = []
        removed_ids: list[str] = []
        total = sum(item["reclaimable_files"] for item in released)

        for item in released:
            unit_root = self.runs_root / item["unit_path"]
            if self._unit_has_lock(unit_root):
                skipped.append({"unit_uri": item["unit_uri"], "reason": BLOCK_LOCK})
                continue
            for record in item["files"]:
                target = long_path(self.runs_root / record["run_path"])
                try:
                    stat = target.stat()
                except OSError:
                    skipped.append({"run_path": record["run_path"], "reason": "missing"})
                    continue
                if stat.st_size != record["size_bytes"]:
                    skipped.append({"run_path": record["run_path"], "reason": "size-drift"})
                    continue
                try:
                    target.unlink()
                except OSError as exc:
                    skipped.append(
                        {"run_path": record["run_path"], "reason": type(exc).__name__}
                    )
                    continue
                removed_files += 1
                removed_bytes += record["size_bytes"]
                removed_ids.append(record["artifact_id"])
                if progress is not None and removed_files % 500 == 0:
                    progress(removed_files, total)
            self._prune_empty_directories(unit_root)

        self._drop_artifacts(removed_ids)
        manifest["result"] = {
            "removed_files": removed_files,
            "removed_bytes": removed_bytes,
            "skipped": skipped,
            "completed_at": self.registry.now(),
        }
        atomic_write_json(manifest_path, manifest)
        return {
            "status": "executed",
            "manifest_path": str(manifest_path),
            "removed_files": removed_files,
            "removed_bytes": removed_bytes,
            "skipped_count": len(skipped),
        }

    def _unit_has_lock(self, unit_root: Path) -> bool:
        if not unit_root.is_dir():
            return False
        for suffix in sorted(self.policy.lock_guard_suffixes):
            if next(unit_root.rglob(f"*{suffix}"), None) is not None:
                return True
        return False

    def _prune_empty_directories(self, unit_root: Path) -> None:
        if not unit_root.is_dir():
            return
        for current, directories, files in os.walk(unit_root, topdown=False):
            if files or directories:
                continue
            try:
                Path(current).rmdir()
            except OSError:
                continue

    def _drop_artifacts(self, artifact_ids: list[str]) -> None:
        if not artifact_ids:
            return
        with self.registry.transaction() as connection:
            for index in range(0, len(artifact_ids), 500):
                chunk = artifact_ids[index : index + 500]
                marks = ",".join("?" for _ in chunk)
                connection.execute(
                    f"DELETE FROM artifacts WHERE artifact_id IN ({marks})", tuple(chunk)
                )


def _gib(value: int) -> str:
    return f"{value / (1024 ** 3):.2f} GiB"


def _mib(value: int) -> str:
    return f"{value / (1024 ** 2):.1f} MiB"


def render_markdown(plan: dict[str, Any]) -> str:
    totals = plan["totals"]
    lines = [
        "# CST run retention plan (dry run)",
        "",
        f"- Generated: `{plan['generated_at']}`",
        f"- Runs root: `{plan['runs_root']}`",
        f"- Policy version: `{plan['policy']['policy_version']}`",
        f"- Filters: `{json.dumps(plan['filters'], ensure_ascii=False)}`",
        "",
        "## Totals",
        "",
        f"- Catalog: {totals['catalog_files']:,} files, {_gib(totals['catalog_bytes'])}",
        f"- Reclaim units considered: {totals['units_considered']:,}",
        f"- Units released: {totals['units_released']:,}",
        f"- Units retained: {totals['units_retained']:,}",
        f"- Units deferred by budget: {totals['units_deferred']:,}",
        f"- **Releasable: {totals['releasable_files']:,} files, {_gib(totals['releasable_bytes'])}**",
        f"- Reclaimable but blocked: {_gib(totals['blocked_reclaimable_bytes'])}",
        f"- Projected catalog size after reclamation: {_gib(totals['projected_catalog_bytes_after'])}",
        f"- Run directories touched: {totals['run_directories_touched']:,}",
        "",
        "### Releasable bytes by retention class",
        "",
        "| retention class | bytes |",
        "| --- | --- |",
    ]
    for name, value in sorted(
        totals["releasable_bytes_by_class"].items(), key=lambda item: -item[1]
    ):
        lines.append(f"| {name} | {_gib(value)} |")

    lines += [
        "",
        "## Blocking reasons",
        "",
        "| reason | units | reclaimable bytes held |",
        "| --- | --- | --- |",
    ]
    for reason, count in sorted(plan["block_reason_counts"].items(), key=lambda item: -item[1]):
        held = plan["block_reason_bytes"].get(reason, 0)
        lines.append(f"| {reason} | {count} | {_gib(held)} |")

    lines += [
        "",
        "### Protection signals (why a unit counts as a selected candidate)",
        "",
        "| signal | units | reclaimable bytes held |",
        "| --- | --- | --- |",
    ]
    for signal, count in sorted(
        plan.get("protection_signal_counts", {}).items(), key=lambda item: -item[1]
    ):
        held = plan.get("protection_signal_bytes", {}).get(signal, 0)
        lines.append(f"| {signal} | {count} | {_gib(held)} |")

    lines += [
        "",
        "## By project family",
        "",
        "| project family | units | release | retain | releasable | blocked |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for bucket in plan["by_project_family"]:
        lines.append(
            f"| {bucket['project_family']} | {bucket['units']} | {bucket['release_units']} | "
            f"{bucket['retain_units']} | {_gib(bucket['releasable_bytes'])} | "
            f"{_gib(bucket['blocked_bytes'])} |"
        )

    released = [item for item in plan["units"] if item["decision"] == "release"]
    lines += [
        "",
        f"## Released units ({len(released)})",
        "",
        "Each unit is a CST working copy whose owning trial reached a terminal state and",
        "whose lifecycle scope still holds exported curve evidence.",
        "",
        "| unit | family | owner | status | reclaim | retain | evidence |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in released[:400]:
        owner = item["trial_id"] or item["experiment_id"] or "-"
        lines.append(
            f"| `{item['unit_path']}` | {item['project_family']} | {owner} | "
            f"{item['owner_status']} | {_mib(item['reclaimable_bytes'])} | "
            f"{_mib(item['retained_bytes'])} | {item['evidence_artifact_count']} |"
        )
    if len(released) > 400:
        lines.append(f"| ??{len(released) - 400} more units in the JSON report | | | | | | |")

    retained = [item for item in plan["units"] if item["decision"] != "release"]
    lines += [
        "",
        f"## Retained units ({len(retained)})",
        "",
        "| unit | family | owner status | reclaimable held | block reasons |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in sorted(retained, key=lambda entry: -entry["reclaimable_bytes"])[:400]:
        lines.append(
            f"| `{item['unit_path']}` | {item['project_family']} | {item['owner_status']} | "
            f"{_mib(item['reclaimable_bytes'])} | {', '.join(item['block_reasons'])} |"
        )
    if len(retained) > 400:
        lines.append(f"| ??{len(retained) - 400} more units in the JSON report | | | | |")

    lines += [
        "",
        "## Recompute contract",
        "",
        "Every released unit records `regeneration_inputs` in the JSON report: the `.cst`",
        "working copy with its SHA-256, the History/VBA solver-settings blocks, and the",
        "parameter records needed to re-solve. Reclaiming a `Result/` tree therefore never",
        "destroys the ability to reproduce it, only the cached output of a past solve.",
        "",
    ]
    return "\n".join(lines) + "\n"
