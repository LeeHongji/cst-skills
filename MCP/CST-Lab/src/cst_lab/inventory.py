"""Read-only legacy inventory for ``cst_runs``.

Clusters the historical top-level run directories into real project families,
maps each one to the Lab lifecycle records that produced it, and emits a stable
``run://`` URI per directory. This command never moves, merges, or deletes
anything: it is the input for the later revision-lineage consolidation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .files import atomic_write_json
from .paths import LabPaths
from .registry import LabRegistry
from .retention import (
    EVIDENCE,
    FAMILY_RULES,
    REGENERABLE,
    SCRATCH,
    UNASSIGNED_FAMILY,
    UNCLASSIFIED,
    FamilyRule,
    RetentionPolicy,
)
from .artifacts import TRACE_DIRECTORY, run_uri

PREFIX_WEIGHT = 5
SOURCE_ROOT_WEIGHT = 4
DIRECTORY_TOKEN_WEIGHT = 3
MODEL_TOKEN_WEIGHT = 2


@dataclass
class DirectorySignals:
    run_directory: str
    cst_basenames: list[str]
    experiment_titles: list[str]
    project_names: list[str]
    project_source_paths: list[str]


def score_family(rule: FamilyRule, signals: DirectorySignals) -> tuple[int, list[str]]:
    directory = signals.run_directory.casefold()
    evidence: list[str] = []
    score = 0
    for prefix in rule.directory_prefixes:
        if directory.startswith(prefix):
            score += PREFIX_WEIGHT
            evidence.append(f"directory-prefix:{prefix}")
            break
    for token in rule.directory_tokens:
        if token in directory:
            score += DIRECTORY_TOKEN_WEIGHT
            evidence.append(f"directory-token:{token}")
            break
    haystack = " ".join(
        item.casefold()
        for item in signals.cst_basenames + signals.experiment_titles + signals.project_names
    )
    for token in rule.model_tokens:
        if token in haystack:
            score += MODEL_TOKEN_WEIGHT
            evidence.append(f"model-token:{token}")
            break
    for root in rule.source_roots:
        if any(path.casefold().startswith(root) for path in signals.project_source_paths):
            score += SOURCE_ROOT_WEIGHT
            evidence.append(f"source-root:{root}")
            break
    return score, evidence


def classify_family(signals: DirectorySignals) -> dict[str, Any]:
    ranked: list[tuple[int, FamilyRule, list[str]]] = []
    for rule in FAMILY_RULES:
        score, evidence = score_family(rule, signals)
        if score > 0:
            ranked.append((score, rule, evidence))
    if not ranked:
        return {
            "project_family": UNASSIGNED_FAMILY,
            "family_title": "Unassigned legacy run directory",
            "family_score": 0,
            "family_evidence": [],
            "family_runner_up": None,
        }
    ranked.sort(key=lambda item: (-item[0], FAMILY_RULES.index(item[1])))
    best_score, best_rule, best_evidence = ranked[0]
    runner_up = None
    if len(ranked) > 1:
        runner_up = {"project_family": ranked[1][1].family_id, "family_score": ranked[1][0]}
    return {
        "project_family": best_rule.family_id,
        "family_title": best_rule.title,
        "family_score": best_score,
        "family_evidence": best_evidence,
        "family_runner_up": runner_up,
    }


class LegacyInventoryBuilder:
    def __init__(
        self,
        paths: LabPaths,
        registry: LabRegistry,
        policy: RetentionPolicy,
        *,
        clock: Callable[[], Any] | None = None,
    ) -> None:
        self.paths = paths
        self.registry = registry
        self.policy = policy
        self.clock = clock

    @property
    def runs_root(self) -> Path:
        return self.paths.runs_root

    def _now(self) -> str:
        return self.registry.now()

    def build(self, *, write: bool = True) -> dict[str, Any]:
        runs_root = self.runs_root
        lifecycle = self.registry.lifecycle_run_paths()
        projects = {item["project_id"]: item for item in self.registry.all_projects()}

        experiments_by_directory: dict[str, list[dict[str, Any]]] = {}
        experiment_directory: dict[str, str] = {}
        for record in lifecycle["experiments"]:
            directory = self._top_level(record["run_path"])
            if directory is None:
                continue
            experiment_directory[record["experiment_id"]] = directory
            experiments_by_directory.setdefault(directory, []).append(record)

        trials_by_experiment: dict[str, list[dict[str, Any]]] = {}
        for record in lifecycle["trials"]:
            trials_by_experiment.setdefault(record["experiment_id"], []).append(record)

        catalog = self._catalog_by_directory()

        directories = sorted(
            (entry.name for entry in runs_root.iterdir() if entry.is_dir()),
            key=str.casefold,
        )

        entries: list[dict[str, Any]] = []
        reserved: list[str] = []
        for name in directories:
            if name == "_registry":
                continue
            if self.policy.is_reserved(name):
                reserved.append(name)
                continue
            entries.append(
                self._describe_directory(
                    name,
                    experiments_by_directory.get(name, []),
                    trials_by_experiment,
                    projects,
                    catalog.get(name, {}),
                )
            )

        families = self._summarize_families(entries)
        reregistered = self._reregistered_projects(projects, entries)

        document = {
            "schema_version": 1,
            "generated_at": self._now(),
            "runs_root": str(runs_root),
            "policy_version": self.policy.policy_version,
            "reserved_directories": reserved,
            "totals": {
                "run_directories": len(entries),
                "families": len(families),
                "evidence_bytes": sum(item["bytes"][EVIDENCE] for item in entries),
                "regenerable_bytes": sum(item["bytes"][REGENERABLE] for item in entries),
                "scratch_bytes": sum(item["bytes"][SCRATCH] for item in entries),
                "unclassified_bytes": sum(item["bytes"][UNCLASSIFIED] for item in entries),
                "total_bytes": sum(item["bytes"]["total"] for item in entries),
            },
            "families": families,
            "run_directories": entries,
            "reregistered_trial_products": reregistered,
        }
        path = self.paths.registry_root / "legacy-inventory.json"
        if write:
            atomic_write_json(path, document)
        return {**document, "inventory_path": str(path)}

    # ------------------------------------------------------------------ helpers

    def _top_level(self, raw: str | None) -> str | None:
        if not raw:
            return None
        try:
            relative = Path(raw).relative_to(self.runs_root)
        except ValueError:
            return None
        parts = relative.parts
        return parts[0] if parts else None

    def _catalog_by_directory(self) -> dict[str, dict[str, Any]]:
        connection = self.registry.connect()
        try:
            rows = connection.execute(
                """
                SELECT run_directory, retention_class, COUNT(*) AS files,
                       SUM(size_bytes) AS bytes
                FROM artifacts GROUP BY run_directory, retention_class
                """
            ).fetchall()
            cst_rows = connection.execute(
                """
                SELECT run_directory, run_path, sha256, size_bytes
                FROM artifacts WHERE artifact_type = 'cst-project' ORDER BY run_path
                """
            ).fetchall()
        finally:
            connection.close()
        catalog: dict[str, dict[str, Any]] = {}
        for row in rows:
            bucket = catalog.setdefault(
                row["run_directory"], {"classes": {}, "cst_projects": []}
            )
            bucket["classes"][row["retention_class"]] = {
                "files": row["files"],
                "bytes": row["bytes"] or 0,
            }
        for row in cst_rows:
            bucket = catalog.setdefault(
                row["run_directory"], {"classes": {}, "cst_projects": []}
            )
            bucket["cst_projects"].append(
                {
                    "run_path": row["run_path"],
                    "basename": PurePosixPath(row["run_path"]).stem,
                    "sha256": row["sha256"],
                    "size_bytes": row["size_bytes"],
                }
            )
        return catalog

    def _describe_directory(
        self,
        name: str,
        experiments: list[dict[str, Any]],
        trials_by_experiment: dict[str, list[dict[str, Any]]],
        projects: dict[str, dict[str, Any]],
        catalog: dict[str, Any],
    ) -> dict[str, Any]:
        cst_projects = catalog.get("cst_projects", [])
        classes = catalog.get("classes", {})

        titles: list[str] = []
        project_ids: list[str] = []
        revision_ids: list[str] = []
        lifecycle: list[dict[str, Any]] = []
        for record in sorted(experiments, key=lambda item: item["experiment_id"]):
            try:
                spec = json.loads(record["spec_json"]) if record["spec_json"] else {}
            except json.JSONDecodeError:
                spec = {}
            title = spec.get("title") or ""
            if title:
                titles.append(title)
            project_ids.append(record["project_id"])
            revision_ids.append(record["revision_id"])
            trials = sorted(
                trials_by_experiment.get(record["experiment_id"], []),
                key=lambda item: item["sequence"],
            )
            lifecycle.append(
                {
                    "experiment_id": record["experiment_id"],
                    "experiment_status": record["status"],
                    "experiment_title": title,
                    "project_id": record["project_id"],
                    "revision_id": record["revision_id"],
                    "trials": [
                        {
                            "trial_id": trial["trial_id"],
                            "sequence": trial["sequence"],
                            "status": trial["status"],
                            "run_uri": run_uri(
                                Path(trial["run_path"]).relative_to(self.runs_root).as_posix()
                            )
                            if trial.get("run_path")
                            else None,
                        }
                        for trial in trials
                    ],
                }
            )

        signals = DirectorySignals(
            run_directory=name,
            cst_basenames=[item["basename"] for item in cst_projects],
            experiment_titles=titles,
            project_names=[projects[pid]["name"] for pid in project_ids if pid in projects],
            project_source_paths=[
                projects[pid]["source_path"] for pid in project_ids if pid in projects
            ],
        )
        family = classify_family(signals)

        def bytes_for(retention_class: str) -> int:
            return int(classes.get(retention_class, {}).get("bytes", 0) or 0)

        def files_for(retention_class: str) -> int:
            return int(classes.get(retention_class, {}).get("files", 0) or 0)

        totals_bytes = sum(bytes_for(item) for item in (EVIDENCE, REGENERABLE, SCRATCH, UNCLASSIFIED))
        totals_files = sum(files_for(item) for item in (EVIDENCE, REGENERABLE, SCRATCH, UNCLASSIFIED))

        return {
            "run_directory": name,
            "run_uri": run_uri(name),
            "kind": "mcp-trace-store" if name == TRACE_DIRECTORY else "run-workspace",
            **family,
            "lab_registered": bool(experiments),
            "lifecycle": lifecycle,
            "project_ids": sorted(set(project_ids)),
            "revision_ids": sorted(set(revision_ids)),
            "experiment_ids": [item["experiment_id"] for item in lifecycle],
            "trial_ids": [
                trial["trial_id"] for item in lifecycle for trial in item["trials"]
            ],
            "cst_projects": cst_projects,
            "files": {
                EVIDENCE: files_for(EVIDENCE),
                REGENERABLE: files_for(REGENERABLE),
                SCRATCH: files_for(SCRATCH),
                UNCLASSIFIED: files_for(UNCLASSIFIED),
                "total": totals_files,
            },
            "bytes": {
                EVIDENCE: bytes_for(EVIDENCE),
                REGENERABLE: bytes_for(REGENERABLE),
                SCRATCH: bytes_for(SCRATCH),
                UNCLASSIFIED: bytes_for(UNCLASSIFIED),
                "total": totals_bytes,
            },
        }

    def _summarize_families(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for entry in entries:
            bucket = buckets.setdefault(
                entry["project_family"],
                {
                    "project_family": entry["project_family"],
                    "family_title": entry["family_title"],
                    "run_directory_count": 0,
                    "lab_registered_count": 0,
                    "cst_project_count": 0,
                    "evidence_bytes": 0,
                    "regenerable_bytes": 0,
                    "scratch_bytes": 0,
                    "unclassified_bytes": 0,
                    "total_bytes": 0,
                    "project_ids": set(),
                    "run_directories": [],
                },
            )
            bucket["run_directory_count"] += 1
            bucket["lab_registered_count"] += 1 if entry["lab_registered"] else 0
            bucket["cst_project_count"] += len(entry["cst_projects"])
            bucket["evidence_bytes"] += entry["bytes"][EVIDENCE]
            bucket["regenerable_bytes"] += entry["bytes"][REGENERABLE]
            bucket["scratch_bytes"] += entry["bytes"][SCRATCH]
            bucket["unclassified_bytes"] += entry["bytes"][UNCLASSIFIED]
            bucket["total_bytes"] += entry["bytes"]["total"]
            bucket["project_ids"].update(entry["project_ids"])
            bucket["run_directories"].append(entry["run_directory"])
        summaries = []
        for bucket in buckets.values():
            bucket["project_ids"] = sorted(bucket["project_ids"])
            summaries.append(bucket)
        summaries.sort(key=lambda item: (-item["total_bytes"], item["project_family"]))
        return summaries

    def _reregistered_projects(
        self, projects: dict[str, dict[str, Any]], entries: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Projects whose registered source is itself a previous run product.

        These are the false projects: a parameter change was registered as a new
        project instead of a new revision of the same project. Phase 3 consumes
        this list to build the real revision chains.
        """

        family_by_directory = {item["run_directory"]: item for item in entries}
        trial_owner: dict[str, dict[str, Any]] = {}
        for entry in entries:
            for item in entry["lifecycle"]:
                for trial in item["trials"]:
                    if trial["run_uri"]:
                        trial_owner[trial["run_uri"].removeprefix("run://").casefold()] = {
                            "run_directory": entry["run_directory"],
                            "experiment_id": item["experiment_id"],
                            "trial_id": trial["trial_id"],
                            "trial_status": trial["status"],
                        }

        results: list[dict[str, Any]] = []
        for project in projects.values():
            source = Path(project["source_path"])
            try:
                relative = source.relative_to(self.runs_root)
            except ValueError:
                continue
            parts = relative.parts
            directory = parts[0]
            entry = family_by_directory.get(directory)
            producing_trial = None
            probe = relative.parent.as_posix().casefold()
            while probe and probe != ".":
                if probe in trial_owner:
                    producing_trial = trial_owner[probe]
                    break
                probe = PurePosixPath(probe).parent.as_posix()
                if probe == ".":
                    break
            results.append(
                {
                    "project_id": project["project_id"],
                    "project_name": project["name"],
                    "source_path": project["source_path"],
                    "source_run_uri": run_uri(relative.as_posix()),
                    "source_run_directory": directory,
                    "revision_ids": (project.get("revision_ids") or "").split(",")
                    if project.get("revision_ids")
                    else [],
                    "inferred_project_family": entry["project_family"]
                    if entry
                    else UNASSIGNED_FAMILY,
                    "produced_by": producing_trial,
                    "classification": "trial-product-reregistered-as-project"
                    if producing_trial
                    else "run-workspace-product-reregistered-as-project",
                }
            )
        results.sort(key=lambda item: (item["inferred_project_family"], item["project_id"]))
        return results
