"""Read-only diagnostics: stale lifecycle triage, lock inventory, workspace governance.

Nothing in this module mutates experiment or trial state. Status changes append
irreversible events, so the triage output is a recommendation table for a human,
not an action.
"""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .artifacts import run_uri, sha256_file
from .paths import LabPaths, long_path
from .registry import EXPERIMENT_TRANSITIONS, LabRegistry
from .retention import RetentionPolicy

NON_TERMINAL_EXPERIMENT_STATUSES = ("prepared", "queued", "running", "paused", "blocked")

# Paths under tmp/ and output/ that belong to the concurrent CST-CAD workstream.
# They are reported but must not be proposed for deletion until that migration
# lands, because they are its migration sources.
OTHER_WORKSTREAM_PATHS = frozenset(
    {
        "cadquery_deps",
        "fig15_filter_d_cad_review",
        "fig7_filter_a_cad_review",
        "fig15_best_output_finger_visualization",
    }
)

RECOMMEND_COMPLETED = "completed"
RECOMMEND_CANCELLED = "cancelled"
RECOMMEND_REVIEW = "needs-human-review"


def transition_path(current: str, target: str) -> list[str] | None:
    """Shortest legal state-machine path, since paused cannot reach completed directly."""

    if current == target:
        return []
    queue: deque[tuple[str, list[str]]] = deque([(current, [])])
    seen = {current}
    while queue:
        state, path = queue.popleft()
        for candidate in sorted(EXPERIMENT_TRANSITIONS.get(state, set())):
            if candidate in seen:
                continue
            walked = path + [candidate]
            if candidate == target:
                return walked
            seen.add(candidate)
            queue.append((candidate, walked))
    return None


class LabDiagnostics:
    def __init__(self, paths: LabPaths, registry: LabRegistry, policy: RetentionPolicy) -> None:
        self.paths = paths
        self.registry = registry
        self.policy = policy

    @property
    def runs_root(self) -> Path:
        return self.paths.runs_root

    # ------------------------------------------------------- experiment triage

    def triage_experiments(self, *, statuses: tuple[str, ...] | None = None) -> dict[str, Any]:
        wanted = set(statuses or NON_TERMINAL_EXPERIMENT_STATUSES)
        lifecycle = self.registry.lifecycle_run_paths()
        trials_by_experiment: dict[str, list[dict[str, Any]]] = {}
        for record in lifecycle["trials"]:
            trials_by_experiment.setdefault(record["experiment_id"], []).append(record)
        evidence = self._evidence_by_run_directory()

        rows: list[dict[str, Any]] = []
        for experiment in sorted(lifecycle["experiments"], key=lambda item: item["experiment_id"]):
            if experiment["status"] not in wanted:
                continue
            rows.append(
                self._triage_one(
                    experiment,
                    trials_by_experiment.get(experiment["experiment_id"], []),
                    evidence,
                )
            )

        counts: dict[str, int] = {}
        for row in rows:
            counts[row["recommended_status"]] = counts.get(row["recommended_status"], 0) + 1
        return {
            "schema_version": 1,
            "generated_at": self.registry.now(),
            "considered_statuses": sorted(wanted),
            "experiment_count": len(rows),
            "recommendation_counts": counts,
            "note": (
                "Report only. Applying a recommendation writes irreversible lifecycle "
                "events, and most paused experiments need a multi-hop transition path."
            ),
            "experiments": rows,
        }

    def _triage_one(
        self,
        experiment: dict[str, Any],
        trials: list[dict[str, Any]],
        evidence: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            spec = json.loads(experiment["spec_json"]) if experiment["spec_json"] else {}
        except json.JSONDecodeError:
            spec = {}
        objectives = spec.get("objectives") or []
        primary = objectives[0] if objectives else {}
        metric = primary.get("name")
        direction = primary.get("direction", "minimize")
        target = primary.get("target")

        by_status: dict[str, int] = {}
        best_value: float | None = None
        best_trial: str | None = None
        for trial in trials:
            by_status[trial["status"]] = by_status.get(trial["status"], 0) + 1
            if trial["status"] != "completed" or not trial.get("objectives_json"):
                continue
            try:
                values = json.loads(trial["objectives_json"])
            except json.JSONDecodeError:
                continue
            value = values.get(metric)
            if not isinstance(value, (int, float)):
                continue
            score = -float(value) if direction == "maximize" else float(value)
            if best_value is None or score < best_value:
                best_value = score
                best_trial = trial["trial_id"]
        best_actual = None
        if best_value is not None:
            best_actual = -best_value if direction == "maximize" else best_value

        run_directory = self._top_level(experiment["run_path"])
        evidence_record = evidence.get(run_directory or "", {"files": 0, "examples": []})
        has_evidence = evidence_record["files"] > 0
        completed = by_status.get("completed", 0)
        unsettled = sum(by_status.get(name, 0) for name in ("running", "queued", "planned"))

        target_met = None
        if best_actual is not None and isinstance(target, (int, float)):
            target_met = (
                best_actual >= float(target) if direction == "maximize" else best_actual <= float(target)
            )

        if unsettled:
            recommendation = RECOMMEND_REVIEW
            reason = (
                f"{unsettled} trial(s) are still in a non-terminal state; settle the trials "
                "before deciding the experiment outcome."
            )
        elif not trials:
            recommendation = RECOMMEND_CANCELLED
            reason = "No trials were ever created; the experiment was abandoned before execution."
        elif completed == 0:
            recommendation = RECOMMEND_CANCELLED
            reason = (
                f"No completed trials (statuses: {self._render(by_status)}); no usable result "
                "was produced."
            )
        elif not has_evidence:
            recommendation = RECOMMEND_REVIEW
            reason = (
                f"{completed} completed trial(s) but no exported curve evidence under "
                f"{run_directory}; objectives cannot be re-verified."
            )
        elif best_actual is None:
            recommendation = RECOMMEND_REVIEW
            reason = (
                f"{completed} completed trial(s) with exported evidence, but none recorded a "
                f"numeric value for the primary objective {metric}; the outcome cannot be "
                "judged from the registry alone."
            )
        elif not isinstance(target, (int, float)):
            recommendation = RECOMMEND_REVIEW
            reason = (
                f"{completed} completed trial(s) with exported evidence and best {metric} = "
                f"{best_actual}, but the experiment spec declares no numeric target to compare "
                "against."
            )
        elif target_met:
            recommendation = RECOMMEND_COMPLETED
            reason = (
                f"{completed} completed trial(s) with exported evidence; best {metric} = "
                f"{best_actual} meets the target {target} ({best_trial})."
            )
        else:
            recommendation = RECOMMEND_CANCELLED
            reason = (
                f"{completed} completed trial(s) with exported evidence, but best {metric} = "
                f"{best_actual} never reached the target {target}; this was a screening run "
                "superseded by later experiments. Evidence is retained either way."
            )

        path = transition_path(experiment["status"], recommendation) if recommendation != RECOMMEND_REVIEW else None
        return {
            "experiment_id": experiment["experiment_id"],
            "title": spec.get("title"),
            "current_status": experiment["status"],
            "recommended_status": recommendation,
            "reason": reason,
            "transition_path": path,
            "transition_hops": len(path) if path is not None else None,
            "project_id": experiment["project_id"],
            "revision_id": experiment["revision_id"],
            "run_directory": run_directory,
            "run_uri": run_uri(run_directory) if run_directory else None,
            "trial_count": len(trials),
            "trial_status_counts": by_status,
            "primary_objective": metric,
            "objective_direction": direction,
            "objective_target": target,
            "best_objective_value": best_actual,
            "best_trial_id": best_trial,
            "objective_target_met": target_met,
            "evidence_file_count": evidence_record["files"],
            "evidence_examples": evidence_record["examples"][:3],
            "experiment_updated_at": experiment["updated_at"],
            "last_event_at": self.registry.last_event_at(
                "experiment", experiment["experiment_id"]
            ),
        }

    @staticmethod
    def _render(counts: dict[str, int]) -> str:
        return ", ".join(f"{name}={value}" for name, value in sorted(counts.items())) or "none"

    def _top_level(self, raw: str | None) -> str | None:
        if not raw:
            return None
        try:
            return Path(raw).relative_to(self.runs_root).parts[0]
        except (ValueError, IndexError):
            return None

    def _evidence_by_run_directory(self) -> dict[str, dict[str, Any]]:
        connection = self.registry.connect()
        try:
            rows = connection.execute(
                """
                SELECT run_directory, run_path, artifact_type
                FROM artifacts
                WHERE retention_class = 'evidence'
                  AND (artifact_type IN ('touchstone', 'curve-export')
                       OR run_path LIKE '%metrics.json'
                       OR run_path LIKE '%filter-response-summary.json')
                ORDER BY run_path
                """
            ).fetchall()
        finally:
            connection.close()
        summary: dict[str, dict[str, Any]] = {}
        for row in rows:
            bucket = summary.setdefault(row["run_directory"], {"files": 0, "examples": []})
            bucket["files"] += 1
            if len(bucket["examples"]) < 5:
                bucket["examples"].append(run_uri(row["run_path"]))
        return summary

    # ---------------------------------------------------------- lock inventory

    @staticmethod
    def _held_by_process(path: Path) -> bool | None:
        """Read-only share probe: can this file be opened for reading right now?

        A running CST session opens its project and lock files without read
        sharing, so a denied read is strong evidence that the file is live. The
        probe opens nothing for writing and modifies nothing, so it cannot
        disturb the CST session.
        """

        try:
            with long_path(path).open("rb"):
                return False
        except PermissionError:
            return True
        except OSError:
            return None

    def lock_inventory(self, *, probe: bool = True, stale_after_hours: int = 24) -> dict[str, Any]:
        """List CST ``.lok`` files. Never deletes: CST may hold the project open."""

        connection = self.registry.connect()
        try:
            rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT run_path, run_directory, size_bytes, mtime, trial_id,
                           experiment_id, owner_kind, path
                    FROM artifacts WHERE artifact_type = 'lock' ORDER BY run_path
                    """
                )
            ]
        finally:
            connection.close()

        now = datetime.now(timezone.utc)
        entries: list[dict[str, Any]] = []
        for row in rows:
            mtime = datetime.fromisoformat(row["mtime"].replace("Z", "+00:00"))
            age_hours = (now - mtime).total_seconds() / 3600.0
            companion = PurePosixPath(row["run_path"]).parent
            held: bool | None = None
            if probe:
                held = self._held_by_process(self.runs_root / row["run_path"])
                if held is False:
                    project = self.runs_root / f"{companion.as_posix()}.cst"
                    if long_path(project).is_file() and self._held_by_process(project):
                        held = True
            if held:
                staleness = "live-held-by-a-process"
            elif age_hours > stale_after_hours:
                staleness = "orphan-candidate"
            else:
                staleness = "recent-review-manually"
            entries.append(
                {
                    "run_path": row["run_path"],
                    "run_uri": run_uri(row["run_path"]),
                    "run_directory": row["run_directory"],
                    "companion_directory": companion.as_posix(),
                    "size_bytes": row["size_bytes"],
                    "mtime": row["mtime"],
                    "age_hours": round(age_hours, 1),
                    "trial_id": row["trial_id"],
                    "experiment_id": row["experiment_id"],
                    "owner_kind": row["owner_kind"],
                    "held_by_process": held,
                    "staleness": staleness,
                }
            )

        by_directory: dict[str, int] = {}
        by_staleness: dict[str, int] = {}
        for entry in entries:
            by_directory[entry["run_directory"]] = by_directory.get(entry["run_directory"], 0) + 1
            by_staleness[entry["staleness"]] = by_staleness.get(entry["staleness"], 0) + 1
        return {
            "schema_version": 1,
            "generated_at": self.registry.now(),
            "lock_file_count": len(entries),
            "probe_enabled": probe,
            "staleness_counts": by_staleness,
            "live_count": by_staleness.get("live-held-by-a-process", 0),
            "orphan_candidate_count": by_staleness.get("orphan-candidate", 0),
            "affected_run_directories": len(by_directory),
            "newest_lock_mtime": max((item["mtime"] for item in entries), default=None),
            "oldest_lock_mtime": min((item["mtime"] for item in entries), default=None),
            "locks_per_run_directory": dict(
                sorted(by_directory.items(), key=lambda item: -item[1])
            ),
            "policy": (
                "Report only; this command never deletes a .lok file. 'held_by_process' comes "
                "from a read-only share probe: a denied read means a live process holds the "
                "file. 'orphan-candidate' means the probe succeeded and the lock is older than "
                f"{stale_after_hours} h, which makes it a leftover from an earlier CST session "
                "rather than proof that removal is safe."
            ),
            "locks": entries,
        }

    # ---------------------------------------------------- workspace governance

    def workspace_governance(self) -> dict[str, Any]:
        connection = self.registry.connect()
        try:
            catalog_hashes = {
                row["sha256"]: row["run_path"]
                for row in connection.execute(
                    "SELECT sha256, run_path FROM artifacts WHERE sha256 IS NOT NULL"
                )
            }
        finally:
            connection.close()

        return {
            "schema_version": 1,
            "generated_at": self.registry.now(),
            "tmp": self._directory_report(
                self.paths.workspace_root / "tmp", catalog_hashes, probe_files=True
            ),
            "output": self._directory_report(
                self.paths.workspace_root / "output", catalog_hashes, probe_files=False
            ),
        }

    def _directory_report(
        self, root: Path, catalog_hashes: dict[str, str], *, probe_files: bool
    ) -> dict[str, Any]:
        if not root.is_dir():
            return {"path": str(root), "exists": False, "entries": []}
        entries: list[dict[str, Any]] = []
        for item in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
            if item.is_dir():
                files = 0
                size = 0
                latest = 0.0
                for child in item.rglob("*"):
                    try:
                        if not child.is_file():
                            continue
                        stat = child.stat()
                    except OSError:
                        continue
                    files += 1
                    size += stat.st_size
                    latest = max(latest, stat.st_mtime)
                entries.append(
                    {
                        "name": item.name,
                        "kind": "directory",
                        "file_count": files,
                        "size_bytes": size,
                        "last_modified": datetime.fromtimestamp(latest, tz=timezone.utc)
                        .isoformat(timespec="seconds")
                        .replace("+00:00", "Z")
                        if latest
                        else None,
                        "reserved_for_other_owner": self.policy.is_reserved(item.name)
                        or item.name.casefold() in OTHER_WORKSTREAM_PATHS,
                    }
                )
                continue
            try:
                stat = item.stat()
            except OSError:
                continue
            record: dict[str, Any] = {
                "name": item.name,
                "kind": "file",
                "size_bytes": stat.st_size,
                "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            }
            if probe_files and stat.st_size <= 8 * 1024 * 1024:
                try:
                    digest = sha256_file(item)
                except OSError:
                    digest = None
                if digest:
                    duplicate = catalog_hashes.get(digest)
                    record["sha256"] = digest
                    record["duplicate_of_run_artifact"] = (
                        run_uri(duplicate) if duplicate else None
                    )
                    record["disposition"] = (
                        "safe-to-delete-duplicate" if duplicate else "needs-placement-decision"
                    )
            entries.append(record)
        total = sum(item["size_bytes"] for item in entries)
        return {
            "path": str(root),
            "exists": True,
            "entry_count": len(entries),
            "total_bytes": total,
            "entries": entries,
        }
