from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

SCHEMA_VERSION = 2

ARTIFACTS_DDL_V2 = """
CREATE TABLE IF NOT EXISTS artifacts_v2 (
    artifact_id TEXT PRIMARY KEY,
    experiment_id TEXT REFERENCES experiments(experiment_id),
    trial_id TEXT REFERENCES trials(trial_id),
    owner_kind TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    run_path TEXT NOT NULL UNIQUE,
    run_directory TEXT NOT NULL,
    retention_class TEXT NOT NULL,
    classification_reason TEXT NOT NULL,
    producing_tool TEXT,
    sha256 TEXT,
    size_bytes INTEGER NOT NULL,
    mtime TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

ARTIFACTS_INDEXES_V2 = """
CREATE INDEX IF NOT EXISTS idx_artifacts_run_directory ON artifacts(run_directory);
CREATE INDEX IF NOT EXISTS idx_artifacts_retention ON artifacts(retention_class);
CREATE INDEX IF NOT EXISTS idx_artifacts_trial ON artifacts(trial_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_experiment ON artifacts(experiment_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_sha256 ON artifacts(sha256);
"""

EXPERIMENT_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"prepared", "blocked", "cancelled"},
    "prepared": {"queued", "blocked", "cancelled"},
    "queued": {"running", "paused", "blocked", "cancelled"},
    "running": {"validating", "paused", "failed", "partial", "cancelled"},
    "validating": {"completed", "invalid", "failed", "partial"},
    "paused": {"queued", "cancelled", "blocked"},
    "blocked": {"planned", "prepared", "queued", "cancelled"},
    "failed": {"queued", "cancelled"},
    "invalid": {"queued", "cancelled"},
    "partial": {"queued", "validating", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

TRIAL_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"queued", "cancelled"},
    "queued": {"running", "cancelled", "pruned"},
    "running": {"validating", "failed", "partial", "cancelled", "pruned"},
    "validating": {"completed", "invalid", "failed", "partial"},
    "failed": {"queued", "cancelled"},
    "invalid": {"queued", "cancelled"},
    "partial": {"queued", "validating", "cancelled"},
    "completed": set(),
    "pruned": set(),
    "cancelled": set(),
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key in (
        "manifest_json",
        "snapshot_json",
        "spec_json",
        "parameters_json",
        "objectives_json",
        "constraints_json",
        "error_json",
        "payload_json",
    ):
        if key in result:
            result[key.removesuffix("_json")] = json.loads(result.pop(key)) if result[key] else None
    return result


class LabRegistry:
    def __init__(
        self,
        database: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = Path(database)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def now(self) -> str:
        return self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    companion_path TEXT,
                    companion_sha256 TEXT,
                    manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_revisions (
                    revision_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    snapshot_sha256 TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, snapshot_sha256)
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    revision_id TEXT NOT NULL REFERENCES model_revisions(revision_id),
                    status TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    run_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trials (
                    trial_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
                    sequence INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    objectives_json TEXT,
                    constraints_json TEXT,
                    error_json TEXT,
                    run_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(experiment_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    experiment_id TEXT REFERENCES experiments(experiment_id),
                    trial_id TEXT REFERENCES trials(trial_id),
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    aggregate_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_locks (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id),
                    owner TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_revisions_project ON model_revisions(project_id);
                CREATE INDEX IF NOT EXISTS idx_experiments_revision ON experiments(revision_id);
                CREATE INDEX IF NOT EXISTS idx_trials_experiment ON trials(experiment_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_events_aggregate ON events(aggregate_type, aggregate_id);
                """
            )
        self._migrate()

    def _migrate(self) -> None:
        """Apply forward-compatible schema migrations.

        Migration 2 widens the artifact catalog: it adds the relative ``run_path``,
        retention class, producing tool, mtime and indexing timestamps, and makes
        ``sha256`` nullable so that recomputable solver caches can be tracked by
        size and mtime without paying for a digest.
        """

        connection = self.connect()
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version >= SCHEMA_VERSION:
                return
            columns = {row[1] for row in connection.execute("PRAGMA table_info(artifacts)")}
            if "run_path" not in columns:
                connection.commit()
                connection.execute("PRAGMA foreign_keys = OFF")
                connection.execute("BEGIN IMMEDIATE")
                connection.executescript(ARTIFACTS_DDL_V2)
                if columns:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO artifacts_v2(
                            artifact_id, experiment_id, trial_id, owner_kind, artifact_type,
                            path, run_path, run_directory, retention_class,
                            classification_reason, producing_tool, sha256, size_bytes,
                            mtime, policy_version, indexed_at, created_at
                        )
                        SELECT
                            artifact_id, experiment_id, trial_id, 'legacy', kind,
                            path, path, '', 'unclassified',
                            'migrated from schema version 1', NULL, sha256, size,
                            created_at, 'legacy', created_at, created_at
                        FROM artifacts
                        """
                    )
                    connection.execute("DROP TABLE artifacts")
                connection.execute("ALTER TABLE artifacts_v2 RENAME TO artifacts")
                connection.executescript(ARTIFACTS_INDEXES_V2)
                connection.execute(
                    "INSERT OR REPLACE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                    (SCHEMA_VERSION, "artifact-catalog-retention-classes", self.now()),
                )
                connection.commit()
                connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
        finally:
            connection.close()

    def schema_state(self) -> dict[str, Any]:
        connection = self.connect()
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            migrations = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM schema_migrations ORDER BY version"
                )
            ]
            columns = [row[1] for row in connection.execute("PRAGMA table_info(artifacts)")]
        finally:
            connection.close()
        return {
            "user_version": version,
            "expected_version": SCHEMA_VERSION,
            "migrations": migrations,
            "artifact_columns": columns,
        }

    # ---------------------------------------------------------------- artifacts

    def artifact_fingerprints(self) -> dict[str, tuple[int, str, str | None]]:
        """Return ``run_path -> (size_bytes, mtime, sha256)`` for incremental indexing."""

        connection = self.connect()
        try:
            return {
                row["run_path"]: (row["size_bytes"], row["mtime"], row["sha256"])
                for row in connection.execute(
                    "SELECT run_path, size_bytes, mtime, sha256 FROM artifacts"
                )
            }
        finally:
            connection.close()

    def upsert_artifacts(self, records: Sequence[dict[str, Any]]) -> int:
        if not records:
            return 0
        rows = [
            (
                record["artifact_id"],
                record.get("experiment_id"),
                record.get("trial_id"),
                record["owner_kind"],
                record["artifact_type"],
                record["path"],
                record["run_path"],
                record["run_directory"],
                record["retention_class"],
                record["classification_reason"],
                record.get("producing_tool"),
                record.get("sha256"),
                record["size_bytes"],
                record["mtime"],
                record["policy_version"],
                record["indexed_at"],
                record["created_at"],
            )
            for record in records
        ]
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO artifacts(
                    artifact_id, experiment_id, trial_id, owner_kind, artifact_type,
                    path, run_path, run_directory, retention_class, classification_reason,
                    producing_tool, sha256, size_bytes, mtime, policy_version,
                    indexed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    experiment_id=excluded.experiment_id, trial_id=excluded.trial_id,
                    owner_kind=excluded.owner_kind, artifact_type=excluded.artifact_type,
                    path=excluded.path, run_path=excluded.run_path,
                    run_directory=excluded.run_directory,
                    retention_class=excluded.retention_class,
                    classification_reason=excluded.classification_reason,
                    producing_tool=excluded.producing_tool, sha256=excluded.sha256,
                    size_bytes=excluded.size_bytes, mtime=excluded.mtime,
                    policy_version=excluded.policy_version, indexed_at=excluded.indexed_at
                """,
                rows,
            )
        return len(rows)

    def delete_missing_artifacts(self, run_directories: Sequence[str], keep: Sequence[str]) -> int:
        """Drop rows for files that vanished from the scanned run directories."""

        if not run_directories:
            return 0
        keep_set = set(keep)
        removed = 0
        with self.transaction() as connection:
            placeholders = ",".join("?" for _ in run_directories)
            existing = [
                row["run_path"]
                for row in connection.execute(
                    f"SELECT run_path FROM artifacts WHERE run_directory IN ({placeholders})",
                    tuple(run_directories),
                )
            ]
            stale = [path for path in existing if path not in keep_set]
            for index in range(0, len(stale), 500):
                chunk = stale[index : index + 500]
                marks = ",".join("?" for _ in chunk)
                connection.execute(
                    f"DELETE FROM artifacts WHERE run_path IN ({marks})", tuple(chunk)
                )
                removed += len(chunk)
        return removed

    def artifact_summary(self) -> dict[str, Any]:
        connection = self.connect()
        try:
            by_class = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT retention_class, COUNT(*) AS files,
                           SUM(size_bytes) AS bytes,
                           SUM(CASE WHEN sha256 IS NOT NULL THEN 1 ELSE 0 END) AS hashed
                    FROM artifacts GROUP BY retention_class ORDER BY bytes DESC
                    """
                )
            ]
            by_type = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT artifact_type, retention_class, COUNT(*) AS files,
                           SUM(size_bytes) AS bytes
                    FROM artifacts GROUP BY artifact_type, retention_class
                    ORDER BY bytes DESC
                    """
                )
            ]
            totals = dict(
                connection.execute(
                    "SELECT COUNT(*) AS files, COALESCE(SUM(size_bytes), 0) AS bytes FROM artifacts"
                ).fetchone()
            )
            owners = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT owner_kind, COUNT(*) AS files, SUM(size_bytes) AS bytes
                    FROM artifacts GROUP BY owner_kind ORDER BY bytes DESC
                    """
                )
            ]
        finally:
            connection.close()
        return {
            "totals": totals,
            "by_retention_class": by_class,
            "by_artifact_type": by_type,
            "by_owner_kind": owners,
        }

    def artifacts_for_run_directory(self, run_directory: str) -> list[dict[str, Any]]:
        connection = self.connect()
        try:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM artifacts WHERE run_directory = ? ORDER BY run_path",
                    (run_directory,),
                )
            ]
        finally:
            connection.close()

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        return dict(row)

    # -------------------------------------------------------------- lifecycle

    def lifecycle_run_paths(self) -> dict[str, list[dict[str, Any]]]:
        """Return the registered run_path of every experiment and trial."""

        connection = self.connect()
        try:
            experiments = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT e.experiment_id, e.status, e.run_path, e.updated_at,
                           e.spec_json, r.project_id, r.revision_id
                    FROM experiments e
                    JOIN model_revisions r ON r.revision_id = e.revision_id
                    """
                )
            ]
            trials = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT trial_id, experiment_id, sequence, status, run_path,
                           updated_at, objectives_json
                    FROM trials WHERE run_path IS NOT NULL
                    """
                )
            ]
        finally:
            connection.close()
        return {"experiments": experiments, "trials": trials}

    def all_projects(self) -> list[dict[str, Any]]:
        connection = self.connect()
        try:
            return [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT p.project_id, p.name, p.source_path, p.source_sha256,
                           p.companion_path, p.created_at,
                           (SELECT GROUP_CONCAT(revision_id) FROM model_revisions
                            WHERE project_id = p.project_id) AS revision_ids
                    FROM projects p ORDER BY p.created_at, p.project_id
                    """
                )
            ]
        finally:
            connection.close()

    def last_event_at(self, aggregate_type: str, aggregate_id: str) -> str | None:
        connection = self.connect()
        try:
            row = connection.execute(
                """
                SELECT created_at FROM events
                WHERE aggregate_type = ? AND aggregate_id = ?
                ORDER BY event_id DESC LIMIT 1
                """,
                (aggregate_type, aggregate_id),
            ).fetchone()
        finally:
            connection.close()
        return row["created_at"] if row else None

    def list_locks(self) -> list[dict[str, Any]]:
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute("SELECT * FROM project_locks")]
        finally:
            connection.close()

    def purge_expired_locks(self) -> list[dict[str, Any]]:
        """Remove every lock whose TTL already elapsed and return what was removed."""

        now = self.now()
        with self.transaction() as connection:
            expired = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM project_locks WHERE expires_at <= ?", (now,)
                )
            ]
            if expired:
                connection.execute("DELETE FROM project_locks WHERE expires_at <= ?", (now,))
                for lock in expired:
                    self._event(
                        connection,
                        "project-lock",
                        lock["project_id"],
                        "held",
                        "expired-purged",
                        {
                            "owner": lock["owner"],
                            "acquired_at": lock["acquired_at"],
                            "expires_at": lock["expires_at"],
                            "purged_at": now,
                        },
                    )
        return expired

    def upsert_project(self, manifest: dict[str, Any]) -> dict[str, Any]:
        now = self.now()
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT created_at FROM projects WHERE project_id = ?", (manifest["project_id"],)
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            connection.execute(
                """
                INSERT INTO projects(
                    project_id, name, source_path, source_sha256, companion_path,
                    companion_sha256, manifest_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    name=excluded.name, source_path=excluded.source_path,
                    source_sha256=excluded.source_sha256, companion_path=excluded.companion_path,
                    companion_sha256=excluded.companion_sha256,
                    manifest_json=excluded.manifest_json, updated_at=excluded.updated_at
                """,
                (
                    manifest["project_id"], manifest["name"], manifest["source_path"],
                    manifest["source_sha256"], manifest.get("companion_path"),
                    manifest.get("companion", {}).get("sha256") if manifest.get("companion") else None,
                    _json(manifest), created_at, now,
                ),
            )
        return self.get_project(manifest["project_id"])

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown project: {project_id}")
        return _decode(row)  # type: ignore[return-value]

    def add_revision(self, revision: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO model_revisions(
                    revision_id, project_id, snapshot_sha256, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    revision["revision_id"], revision["project_id"], revision["snapshot_sha256"],
                    _json(revision), revision["created_at"],
                ),
            )
        return self.get_revision(revision["revision_id"])

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM model_revisions WHERE revision_id = ?", (revision_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown model revision: {revision_id}")
        return _decode(row)  # type: ignore[return-value]

    def create_experiment(self, experiment: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO experiments(
                    experiment_id, revision_id, status, spec_json, run_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment["experiment_id"], experiment["revision_id"], "planned",
                    _json(experiment["spec"]), experiment["run_path"],
                    experiment["created_at"], experiment["created_at"],
                ),
            )
            self._event(connection, "experiment", experiment["experiment_id"], None, "planned", {})
        return self.get_experiment(experiment["experiment_id"])

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown experiment: {experiment_id}")
        return _decode(row)  # type: ignore[return-value]

    def list_experiments(self, project_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT e.* FROM experiments e
            JOIN model_revisions r ON r.revision_id = e.revision_id
        """
        params: tuple[Any, ...] = ()
        if project_id:
            query += " WHERE r.project_id = ?"
            params = (project_id,)
        query += " ORDER BY e.created_at, e.experiment_id"
        with self.connect() as connection:
            return [_decode(row) for row in connection.execute(query, params).fetchall()]  # type: ignore[misc]

    def transition_experiment(
        self, experiment_id: str, new_status: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown experiment: {experiment_id}")
            current = row["status"]
            if new_status == current:
                return self.get_experiment(experiment_id)
            if new_status not in EXPERIMENT_TRANSITIONS.get(current, set()):
                raise ValueError(f"Invalid experiment transition: {current} -> {new_status}")
            now = self.now()
            connection.execute(
                "UPDATE experiments SET status = ?, updated_at = ? WHERE experiment_id = ?",
                (new_status, now, experiment_id),
            )
            self._event(connection, "experiment", experiment_id, current, new_status, payload or {})
        return self.get_experiment(experiment_id)

    def create_trial(self, trial: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO trials(
                    trial_id, experiment_id, sequence, status, parameters_json,
                    objectives_json, constraints_json, error_json, run_path, created_at, updated_at
                ) VALUES (?, ?, ?, 'planned', ?, NULL, NULL, NULL, ?, ?, ?)
                """,
                (
                    trial["trial_id"], trial["experiment_id"], trial["sequence"],
                    _json(trial["parameters"]), trial.get("run_path"),
                    trial["created_at"], trial["created_at"],
                ),
            )
            self._event(connection, "trial", trial["trial_id"], None, "planned", {})
        return self.get_trial(trial["trial_id"])

    def get_trial(self, trial_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM trials WHERE trial_id = ?", (trial_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown trial: {trial_id}")
        return _decode(row)  # type: ignore[return-value]

    def list_trials(self, experiment_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trials WHERE experiment_id = ? ORDER BY sequence", (experiment_id,)
            ).fetchall()
        return [_decode(row) for row in rows]  # type: ignore[misc]

    def transition_trial(
        self,
        trial_id: str,
        new_status: str,
        *,
        objectives: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute("SELECT status FROM trials WHERE trial_id = ?", (trial_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown trial: {trial_id}")
            current = row["status"]
            if new_status != current and new_status not in TRIAL_TRANSITIONS.get(current, set()):
                raise ValueError(f"Invalid trial transition: {current} -> {new_status}")
            if new_status == "completed" and objectives is None:
                raise ValueError("Completed trials require objective values")
            now = self.now()
            connection.execute(
                """
                UPDATE trials SET status = ?, objectives_json = COALESCE(?, objectives_json),
                    constraints_json = COALESCE(?, constraints_json),
                    error_json = COALESCE(?, error_json), updated_at = ?
                WHERE trial_id = ?
                """,
                (
                    new_status,
                    _json(objectives) if objectives is not None else None,
                    _json(constraints) if constraints is not None else None,
                    _json(error) if error is not None else None,
                    now,
                    trial_id,
                ),
            )
            if new_status != current:
                self._event(connection, "trial", trial_id, current, new_status, error or {})
        return self.get_trial(trial_id)

    def acquire_lock(self, project_id: str, owner: str, expires_at: str) -> dict[str, Any]:
        now = self.now()
        with self.transaction() as connection:
            expired = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM project_locks WHERE expires_at <= ?", (now,)
                )
            ]
            connection.execute("DELETE FROM project_locks WHERE expires_at <= ?", (now,))
            for stale in expired:
                self._event(
                    connection,
                    "project-lock",
                    stale["project_id"],
                    "held",
                    "expired-purged",
                    {
                        "owner": stale["owner"],
                        "acquired_at": stale["acquired_at"],
                        "expires_at": stale["expires_at"],
                        "purged_at": now,
                        "trigger": "acquire",
                    },
                )
            try:
                connection.execute(
                    "INSERT INTO project_locks(project_id, owner, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
                    (project_id, owner, now, expires_at),
                )
            except sqlite3.IntegrityError as exc:
                holder = connection.execute(
                    "SELECT owner, expires_at FROM project_locks WHERE project_id = ?", (project_id,)
                ).fetchone()
                if holder:
                    raise ValueError(
                        f"Project {project_id} is locked by {holder['owner']} until {holder['expires_at']}"
                    ) from exc
                raise
        return {"project_id": project_id, "owner": owner, "acquired_at": now, "expires_at": expires_at}

    def release_lock(self, project_id: str, owner: str) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM project_locks WHERE project_id = ? AND owner = ?", (project_id, owner)
            )
        return cursor.rowcount == 1

    def events(self, aggregate_type: str, aggregate_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM events WHERE aggregate_type = ? AND aggregate_id = ?
                ORDER BY event_id
                """,
                (aggregate_type, aggregate_id),
            ).fetchall()
        return [_decode(row) for row in rows]  # type: ignore[misc]

    def _event(
        self,
        connection: sqlite3.Connection,
        aggregate_type: str,
        aggregate_id: str,
        from_status: str | None,
        to_status: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO events(aggregate_type, aggregate_id, from_status, to_status, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (aggregate_type, aggregate_id, from_status, to_status, _json(payload), self.now()),
        )

