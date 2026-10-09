from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .artifacts import ArtifactIndexer
from .collector import RetentionCollector
from .diagnostics import LabDiagnostics
from .files import (
    atomic_write_json,
    companion_inventory,
    read_json_if_present,
    sha256_file,
    sha256_json,
)
from .inventory import LegacyInventoryBuilder
from .paths import LabPaths
from .registry import LabRegistry
from .retention import RetentionPolicy
from .validation import load_schema, validate_document


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").lower()
    return cleaned[:48] or "experiment"


def _find_companion(source: Path) -> Path | None:
    candidates = [
        source.with_suffix(""),
        Path(f"{source}.results"),
        source.parent / f"{source.stem}.cst.results",
        source.parent / f"{source.stem}_files",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _find_json(companion: Path | None, name: str) -> tuple[Path | None, Any | None]:
    if companion is None:
        return None, None
    direct = companion / "Model" / name
    if direct.is_file():
        return direct, read_json_if_present(direct)
    matches = sorted(companion.rglob(name))
    if not matches:
        return None, None
    return matches[0], read_json_if_present(matches[0])


class LabOperations:
    def __init__(
        self,
        paths: LabPaths | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        policy: RetentionPolicy | None = None,
    ) -> None:
        self.paths = paths or LabPaths.resolve()
        self.paths.ensure()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.registry = LabRegistry(self.paths.database, clock=self.clock)
        self.policy = policy or RetentionPolicy.default()

    # ------------------------------------------------- storage governance plane

    @property
    def indexer(self) -> ArtifactIndexer:
        return ArtifactIndexer(self.paths, self.registry, self.policy, clock=self.clock)

    @property
    def collector(self) -> RetentionCollector:
        return RetentionCollector(self.paths, self.registry, self.policy)

    @property
    def diagnostics(self) -> LabDiagnostics:
        return LabDiagnostics(self.paths, self.registry, self.policy)

    def index_artifacts(
        self,
        *,
        run_directory: str | None = None,
        rehash: bool = False,
        include_traces: bool = True,
        prune: bool = True,
    ) -> dict[str, Any]:
        return self.indexer.index(
            run_directory=run_directory,
            rehash=rehash,
            include_traces=include_traces,
            prune=prune,
        )

    def legacy_inventory(self, *, write: bool = True) -> dict[str, Any]:
        builder = LegacyInventoryBuilder(self.paths, self.registry, self.policy)
        return builder.build(write=write)

    def plan_retention(
        self,
        *,
        families: list[str] | None = None,
        run_directory: str | None = None,
        max_bytes: int | None = None,
        protect_best_per_experiment: bool = False,
        write_reports: bool = True,
    ) -> dict[str, Any]:
        plan = self.collector.plan(
            families=families,
            run_directory=run_directory,
            max_bytes=max_bytes,
            protect_best_per_experiment=protect_best_per_experiment,
        )
        if write_reports:
            plan["reports"] = self.collector.write_reports(plan)
        return plan

    def execute_retention(
        self,
        *,
        families: list[str] | None = None,
        run_directory: str | None = None,
        max_bytes: int | None = None,
        protect_best_per_experiment: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        plan = self.collector.plan(
            families=families,
            run_directory=run_directory,
            max_bytes=max_bytes,
            protect_best_per_experiment=protect_best_per_experiment,
        )
        reports = self.collector.write_reports(plan, label="gc-execute-plan")
        result = self.collector.execute(plan, confirm=confirm)
        return {**result, "reports": reports}

    def triage_experiments(self, *, statuses: list[str] | None = None) -> dict[str, Any]:
        report = self.diagnostics.triage_experiments(
            statuses=tuple(statuses) if statuses else None
        )
        atomic_write_json(
            self.paths.registry_root / "reports" / "stale-experiment-triage-latest.json", report
        )
        return report

    def lock_inventory(self, *, probe: bool = True, stale_after_hours: int = 24) -> dict[str, Any]:
        report = self.diagnostics.lock_inventory(
            probe=probe, stale_after_hours=stale_after_hours
        )
        atomic_write_json(
            self.paths.registry_root / "reports" / "lock-inventory-latest.json", report
        )
        return report

    def workspace_governance(self) -> dict[str, Any]:
        report = self.diagnostics.workspace_governance()
        atomic_write_json(
            self.paths.registry_root / "reports" / "workspace-governance-latest.json", report
        )
        return report

    def purge_expired_locks(self) -> dict[str, Any]:
        purged = self.registry.purge_expired_locks()
        return {
            "purged_count": len(purged),
            "purged": purged,
            "remaining": self.registry.list_locks(),
        }

    def schema_state(self) -> dict[str, Any]:
        return self.registry.schema_state()

    def now(self) -> str:
        return self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def register_project(self, source_path: str) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"CST project does not exist: {source}")
        if source.suffix.lower() != ".cst":
            raise ValueError(f"Expected a .cst project: {source}")
        source_hash = sha256_file(source)
        path_identity = sha256_json({"source_path": str(source).casefold()})
        project_id = f"project-{path_identity[:12]}"
        companion = _find_companion(source)
        manifest = {
            "schema_version": 2,
            "project_id": project_id,
            "name": source.stem,
            "source_path": str(source),
            "source_sha256": source_hash,
            "companion_path": str(companion) if companion else None,
            "companion": companion_inventory(companion),
            "registered_at": self.now(),
        }
        validate_document(
            manifest,
            load_schema(self.paths.schemas_root, "project-manifest.schema.json"),
            self.paths.schemas_root,
        )
        stored = self.registry.upsert_project(manifest)
        portable = self.paths.registry_root / "projects" / project_id / "project.json"
        atomic_write_json(portable, manifest)
        return {**stored, "portable_manifest": str(portable)}

    def snapshot_model(self, project_id: str) -> dict[str, Any]:
        project = self.registry.get_project(project_id)
        source = Path(project["source_path"])
        if not source.is_file():
            raise FileNotFoundError(f"Registered source is missing: {source}")
        current_hash = sha256_file(source)
        if current_hash != project["source_sha256"]:
            raise ValueError("Source changed after registration; register it again before snapshotting")
        companion_value = project.get("companion_path")
        companion = Path(companion_value) if companion_value else None
        parameter_path, parameters = _find_json(companion, "Parameters.json")
        properties_path, simulation_properties = _find_json(companion, "simulationproperties.json")
        history_candidates: list[dict[str, Any]] = []
        if companion and companion.is_dir():
            for item in sorted(companion.rglob("*")):
                if not item.is_file():
                    continue
                lowered = item.name.lower()
                if "history" in lowered or lowered in {"schematic.xml", "model.xml"}:
                    history_candidates.append(
                        {
                            "path": str(item),
                            "size": item.stat().st_size,
                            "sha256": sha256_file(item),
                        }
                    )
        evidence = [{"kind": "cst-project", "path": str(source), "sha256": current_hash}]
        for kind, path in (("parameters", parameter_path), ("simulation-properties", properties_path)):
            if path:
                evidence.append({"kind": kind, "path": str(path), "sha256": sha256_file(path)})
        snapshot = {
            "parameters": parameters,
            "simulation_properties": simulation_properties,
            "history": {"candidates": history_candidates, "live_export_required": True},
            "evidence": evidence,
        }
        snapshot_hash = sha256_json({"source_sha256": current_hash, "snapshot": snapshot})
        revision = {
            "schema_version": 2,
            "revision_id": f"revision-{snapshot_hash[:12]}",
            "project_id": project_id,
            "snapshot_sha256": snapshot_hash,
            "source_sha256": current_hash,
            "snapshot": snapshot,
            "created_at": self.now(),
        }
        validate_document(
            revision,
            load_schema(self.paths.schemas_root, "model-revision.schema.json"),
            self.paths.schemas_root,
        )
        stored = self.registry.add_revision(revision)
        portable = self.paths.registry_root / "projects" / project_id / "revisions" / revision["revision_id"] / "revision.json"
        atomic_write_json(portable, revision)
        return {**stored, "portable_manifest": str(portable)}

    def create_experiment(self, spec: dict[str, Any]) -> dict[str, Any]:
        validate_document(
            spec,
            load_schema(self.paths.schemas_root, "experiment.schema.json"),
            self.paths.schemas_root,
        )
        revision = self.registry.get_revision(spec["project_revision_id"])
        experiment_id = f"experiment-{uuid.uuid4().hex[:12]}"
        created_at = self.now()
        date_stamp = self.clock().astimezone(timezone.utc).strftime("%Y%m%d")
        run_path = (
            self.paths.runs_root
            / f"{_slug(spec['title'])}_{date_stamp}_{experiment_id.removeprefix('experiment-')}"
        )
        run_path.mkdir(parents=True, exist_ok=False)
        experiment = {
            "experiment_id": experiment_id,
            "revision_id": revision["revision_id"],
            "spec": spec,
            "run_path": str(run_path),
            "created_at": created_at,
        }
        atomic_write_json(run_path / "experiment.json", {**experiment, "status": "planned"})
        stored = self.registry.create_experiment(experiment)
        return stored

    def validate_experiment(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.registry.get_experiment(experiment_id)
        spec = experiment["spec"]
        validate_document(
            spec,
            load_schema(self.paths.schemas_root, "experiment.schema.json"),
            self.paths.schemas_root,
        )
        self.registry.get_revision(experiment["revision_id"])
        checks = [
            {"name": "experiment-schema", "status": "pass", "evidence": [str(Path(experiment["run_path"]) / "experiment.json")]},
            {"name": "model-revision-exists", "status": "pass", "evidence": [experiment["revision_id"]]},
            {"name": "objective-defined", "status": "pass", "evidence": [item["name"] for item in spec["objectives"]]},
        ]
        report = {
            "schema_version": 2,
            "subject_type": "experiment",
            "subject_id": experiment_id,
            "status": "valid",
            "checks": checks,
            "validated_at": self.now(),
        }
        validate_document(
            report,
            load_schema(self.paths.schemas_root, "validation-report.schema.json"),
            self.paths.schemas_root,
        )
        atomic_write_json(Path(experiment["run_path"]) / "validation.json", report)
        updated = self.registry.transition_experiment(experiment_id, "prepared", {"validation": report})
        return {"experiment": updated, "validation": report}

    def transition_experiment(
        self, experiment_id: str, new_status: str, reason: str | None = None
    ) -> dict[str, Any]:
        return self.registry.transition_experiment(
            experiment_id, new_status, {"reason": reason} if reason else {}
        )

    def create_trial(self, experiment_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        experiment = self.registry.get_experiment(experiment_id)
        if experiment["status"] not in {"prepared", "queued", "running", "paused", "failed", "invalid", "partial"}:
            raise ValueError(f"Cannot add a trial while experiment is {experiment['status']}")
        existing = self.registry.list_trials(experiment_id)
        sequence = max((item["sequence"] for item in existing), default=-1) + 1
        trial_id = f"trial-{experiment_id.removeprefix('experiment-')}-{sequence:04d}"
        trial_path = Path(experiment["run_path"]) / "trials" / f"{sequence:04d}"
        trial_path.mkdir(parents=True, exist_ok=False)
        trial = {
            "trial_id": trial_id,
            "experiment_id": experiment_id,
            "sequence": sequence,
            "parameters": parameters,
            "run_path": str(trial_path),
            "created_at": self.now(),
        }
        stored = self.registry.create_trial(trial)
        atomic_write_json(trial_path / "trial.json", self._portable_trial(stored))
        return stored

    def transition_trial(
        self,
        trial_id: str,
        new_status: str,
        *,
        objectives: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stored = self.registry.transition_trial(
            trial_id,
            new_status,
            objectives=objectives,
            constraints=constraints,
            error=error,
        )
        if stored.get("run_path"):
            atomic_write_json(Path(stored["run_path"]) / "trial.json", self._portable_trial(stored))
        return stored

    def list_trials(self, experiment_id: str) -> list[dict[str, Any]]:
        self.registry.get_experiment(experiment_id)
        return self.registry.list_trials(experiment_id)

    def compare_trials(self, experiment_id: str, trial_ids: list[str] | None = None) -> dict[str, Any]:
        experiment = self.registry.get_experiment(experiment_id)
        trials = self.registry.list_trials(experiment_id)
        if trial_ids:
            selected = set(trial_ids)
            trials = [trial for trial in trials if trial["trial_id"] in selected]
            missing = selected - {trial["trial_id"] for trial in trials}
            if missing:
                raise KeyError(f"Unknown trials in experiment: {sorted(missing)}")
        completed = [trial for trial in trials if trial["status"] == "completed"]
        objective_names = [item["name"] for item in experiment["spec"]["objectives"]]
        matrix = []
        for trial in completed:
            matrix.append(
                {
                    "trial_id": trial["trial_id"],
                    "sequence": trial["sequence"],
                    "parameters": trial["parameters"],
                    "objectives": {name: (trial.get("objectives") or {}).get(name) for name in objective_names},
                    "constraints": trial.get("constraints"),
                }
            )
        return {
            "experiment_id": experiment_id,
            "objective_definitions": experiment["spec"]["objectives"],
            "completed_trial_count": len(completed),
            "trials": matrix,
        }

    def compile_case_handoff(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.registry.get_experiment(experiment_id)
        trials = self.registry.list_trials(experiment_id)
        payload = {
            "schema_version": 2,
            "experiment": experiment,
            "trials": trials,
            "events": self.registry.events("experiment", experiment_id),
            "compiled_at": self.now(),
            "brain_action": "Run cst-trace-compile after validating referenced solver evidence.",
        }
        path = Path(experiment["run_path"]) / "case-handoff.json"
        atomic_write_json(path, payload)
        return {"path": str(path), "experiment_status": experiment["status"], "trial_count": len(trials)}

    def acquire_project_lock(self, project_id: str, owner: str, ttl_minutes: int = 60) -> dict[str, Any]:
        if ttl_minutes < 1 or ttl_minutes > 1440:
            raise ValueError("ttl_minutes must be between 1 and 1440")
        self.registry.get_project(project_id)
        expires = self.clock().astimezone(timezone.utc) + timedelta(minutes=ttl_minutes)
        expires_at = expires.isoformat().replace("+00:00", "Z")
        return self.registry.acquire_lock(project_id, owner, expires_at)

    def release_project_lock(self, project_id: str, owner: str) -> dict[str, Any]:
        return {"released": self.registry.release_lock(project_id, owner), "project_id": project_id, "owner": owner}

    @staticmethod
    def _portable_trial(stored: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "trial_id": stored["trial_id"],
            "experiment_id": stored["experiment_id"],
            "sequence": stored["sequence"],
            "status": stored["status"],
            "parameters": stored["parameters"],
            "objectives": stored.get("objectives"),
            "constraints": stored.get("constraints"),
            "error": stored.get("error"),
            "run_path": stored.get("run_path"),
            "created_at": stored["created_at"],
            "updated_at": stored["updated_at"],
        }

