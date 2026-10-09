"""Artifact catalog for ``cst_runs``.

The indexer walks run workspaces once and writes one row per file into the Lab
``artifacts`` table. Digests are computed only for the classes named by the
retention policy, because hashing ~98 GB of recomputable solver cache buys
nothing: nobody restores a cache by content address, they re-solve it.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator

from .paths import LabPaths, long_path
from .registry import LabRegistry
from .retention import EVIDENCE, RetentionPolicy

TRACE_DIRECTORY = "_mcp_traces"
REGISTRY_DIRECTORY = "_registry"

# Synthetic run directory for files dropped straight into cst_runs/ with no run
# workspace around them. They are still artifacts and must be catalogued.
LOOSE_FILES_DIRECTORY = "_loose_files"

PLOTTING_FILENAMES = frozenset(
    {"filter-response.csv", "filter-response.png", "filter-response-summary.json"}
)
LAB_FILENAMES = frozenset(
    {"trial.json", "experiment.json", "case-handoff.json", "validation.json"}
)


def artifact_id_for(run_path: str) -> str:
    """Path-stable artifact identity so repeated indexing is idempotent."""

    digest = hashlib.sha256(run_path.casefold().encode("utf-8")).hexdigest()
    return f"artifact-{digest[:16]}"


def run_uri(run_path: str) -> str:
    return f"run://{run_path}"


def _iso(timestamp: float) -> str:
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with long_path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ScannedFile:
    absolute: Path
    run_path: str
    run_directory: str
    size_bytes: int
    mtime: str


def walk_run_files(
    runs_root: Path, policy: RetentionPolicy, *, include_traces: bool = True
) -> Iterator[ScannedFile]:
    """Yield every file under ``cst_runs`` except the registry and reserved trees."""

    for entry in sorted(os.scandir(runs_root), key=lambda item: item.name.casefold()):
        name = entry.name
        if not entry.is_dir(follow_symlinks=False):
            # A stray file at the root of cst_runs still needs a catalog row, so
            # attribute it to a synthetic run directory instead of dropping it.
            try:
                stat_result = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            yield ScannedFile(
                absolute=Path(entry.path),
                run_path=name,
                run_directory=LOOSE_FILES_DIRECTORY,
                size_bytes=stat_result.st_size,
                mtime=_iso(stat_result.st_mtime),
            )
            continue
        if name == REGISTRY_DIRECTORY:
            continue
        if name == TRACE_DIRECTORY and not include_traces:
            continue
        if policy.is_reserved(name):
            continue
        # Descend using extended-length paths and carry the run-relative prefix
        # explicitly. CST export trees routinely pass the Windows 260-character
        # limit, where a plain scandir fails and would silently hide the subtree.
        stack: list[tuple[Path, str]] = [(long_path(Path(entry.path)), name)]
        while stack:
            current, prefix = stack.pop()
            try:
                children = list(os.scandir(current))
            except OSError:
                continue
            for child in children:
                child_relative = f"{prefix}/{child.name}"
                try:
                    if child.is_dir(follow_symlinks=False):
                        stack.append((Path(child.path), child_relative))
                        continue
                    if not child.is_file(follow_symlinks=False):
                        continue
                    stat = child.stat(follow_symlinks=False)
                except OSError:
                    continue
                yield ScannedFile(
                    absolute=runs_root / child_relative,
                    run_path=child_relative,
                    run_directory=name,
                    size_bytes=stat.st_size,
                    mtime=_iso(stat.st_mtime),
                )


class LifecycleOwnership:
    """Maps a path under ``cst_runs`` to its owning trial or experiment."""

    def __init__(self, runs_root: Path, lifecycle: dict[str, list[dict[str, Any]]]) -> None:
        self.runs_root = runs_root
        self.trials: dict[str, dict[str, Any]] = {}
        self.experiments: dict[str, dict[str, Any]] = {}
        for record in lifecycle["experiments"]:
            key = self._relative(record["run_path"])
            if key is not None:
                self.experiments[key] = record
        for record in lifecycle["trials"]:
            key = self._relative(record["run_path"])
            if key is not None:
                self.trials[key] = record

    def _relative(self, raw: str | None) -> str | None:
        if not raw:
            return None
        try:
            candidate = Path(raw)
            relative = candidate.relative_to(self.runs_root)
        except ValueError:
            marker = f"{os.sep}cst_runs{os.sep}"
            lowered = str(raw).casefold()
            position = lowered.find(marker.casefold())
            if position < 0:
                return None
            relative = Path(str(raw)[position + len(marker) :])
        return relative.as_posix().casefold()

    def resolve(self, run_path: str) -> dict[str, Any]:
        """Nearest-ancestor lookup: trial wins over experiment."""

        parts = PurePosixPath(run_path).parts
        for depth in range(len(parts) - 1, 0, -1):
            key = "/".join(parts[:depth]).casefold()
            trial = self.trials.get(key)
            if trial is not None:
                return {
                    "owner_kind": "trial",
                    "trial_id": trial["trial_id"],
                    "experiment_id": trial["experiment_id"],
                    "owner_status": trial["status"],
                    "owner_run_path": key,
                }
            experiment = self.experiments.get(key)
            if experiment is not None:
                return {
                    "owner_kind": "experiment",
                    "trial_id": None,
                    "experiment_id": experiment["experiment_id"],
                    "owner_status": experiment["status"],
                    "owner_run_path": key,
                }
        if run_path.casefold().startswith(f"{TRACE_DIRECTORY}/"):
            return {
                "owner_kind": "trace",
                "trial_id": None,
                "experiment_id": None,
                "owner_status": None,
                "owner_run_path": TRACE_DIRECTORY,
            }
        return {
            "owner_kind": "orphan",
            "trial_id": None,
            "experiment_id": None,
            "owner_status": None,
            "owner_run_path": None,
        }


def infer_producing_tool(relative: PurePosixPath) -> str | None:
    name = relative.name.casefold()
    suffix = relative.suffix.casefold()
    parts = [part.casefold() for part in relative.parts]
    if parts and parts[0] == TRACE_DIRECTORY:
        return "cst-mcp-trace-recorder"
    if name in LAB_FILENAMES:
        return "cst-lab"
    if name in PLOTTING_FILENAMES:
        return "cst-result-plotting"
    if "result" in parts:
        return "cst-solver"
    if suffix in {".s1p", ".s2p", ".s4p"}:
        return "cst-result-export"
    if suffix in {".vba", ".bas"}:
        return "cst-vba-modeling"
    if suffix == ".cst" or "model" in parts or "modelcache" in parts or "ds" in parts:
        return "cst-studio-suite"
    if suffix == ".py":
        return "repository-script"
    if suffix in {".md", ".png", ".svg"}:
        return "agent-analysis"
    return None


@dataclass
class IndexStats:
    scanned_files: int = 0
    scanned_bytes: int = 0
    written: int = 0
    unchanged: int = 0
    hashed_files: int = 0
    hashed_bytes: int = 0
    hash_skipped_too_large: int = 0
    hash_errors: int = 0
    removed_stale: int = 0
    by_class: dict[str, dict[str, int]] = field(default_factory=dict)
    by_run_directory: dict[str, dict[str, int]] = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    def record(self, retention_class: str, run_directory: str, size_bytes: int) -> None:
        bucket = self.by_class.setdefault(retention_class, {"files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += size_bytes
        directory = self.by_run_directory.setdefault(
            run_directory, {"files": 0, "bytes": 0}
        )
        directory["files"] += 1
        directory["bytes"] += size_bytes

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned_files": self.scanned_files,
            "scanned_bytes": self.scanned_bytes,
            "written": self.written,
            "unchanged": self.unchanged,
            "hashed_files": self.hashed_files,
            "hashed_bytes": self.hashed_bytes,
            "hash_skipped_too_large": self.hash_skipped_too_large,
            "hash_errors": self.hash_errors,
            "removed_stale": self.removed_stale,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "by_retention_class": self.by_class,
        }


class ArtifactIndexer:
    def __init__(
        self,
        paths: LabPaths,
        registry: LabRegistry,
        policy: RetentionPolicy,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.paths = paths
        self.registry = registry
        self.policy = policy
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def runs_root(self) -> Path:
        return self.paths.runs_root

    def now(self) -> str:
        return self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def index(
        self,
        *,
        run_directory: str | None = None,
        rehash: bool = False,
        include_traces: bool = True,
        prune: bool = True,
        batch_size: int = 2000,
        progress: Callable[[IndexStats], None] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        runs_root = self.runs_root
        if not runs_root.is_dir():
            raise FileNotFoundError(f"cst_runs root not found: {runs_root}")

        ownership = LifecycleOwnership(runs_root, self.registry.lifecycle_run_paths())
        fingerprints = self.registry.artifact_fingerprints()
        stats = IndexStats()
        indexed_at = self.now()
        batch: list[dict[str, Any]] = []
        seen: list[str] = []
        directories: set[str] = set()

        for scanned in walk_run_files(runs_root, self.policy, include_traces=include_traces):
            if run_directory and scanned.run_directory.casefold() != run_directory.casefold():
                continue
            relative = PurePosixPath(scanned.run_path)
            classification = self.policy.classify(relative, size_bytes=scanned.size_bytes)
            stats.scanned_files += 1
            stats.scanned_bytes += scanned.size_bytes
            stats.record(classification.retention_class, scanned.run_directory, scanned.size_bytes)
            seen.append(scanned.run_path)
            directories.add(scanned.run_directory)

            previous = fingerprints.get(scanned.run_path)
            unchanged = (
                previous is not None
                and previous[0] == scanned.size_bytes
                and previous[1] == scanned.mtime
            )
            if unchanged and not rehash:
                stats.unchanged += 1
                continue

            digest: str | None = None
            if classification.hash_required:
                if scanned.size_bytes > self.policy.hash_max_bytes:
                    stats.hash_skipped_too_large += 1
                else:
                    try:
                        digest = sha256_file(scanned.absolute)
                        stats.hashed_files += 1
                        stats.hashed_bytes += scanned.size_bytes
                    except OSError:
                        stats.hash_errors += 1
            elif unchanged and previous is not None:
                digest = previous[2]

            owner = ownership.resolve(scanned.run_path)
            batch.append(
                {
                    "artifact_id": artifact_id_for(scanned.run_path),
                    "experiment_id": owner["experiment_id"],
                    "trial_id": owner["trial_id"],
                    "owner_kind": owner["owner_kind"],
                    "artifact_type": classification.artifact_type,
                    "path": str(scanned.absolute),
                    "run_path": scanned.run_path,
                    "run_directory": scanned.run_directory,
                    "retention_class": classification.retention_class,
                    "classification_reason": classification.reason,
                    "producing_tool": infer_producing_tool(relative),
                    "sha256": digest,
                    "size_bytes": scanned.size_bytes,
                    "mtime": scanned.mtime,
                    "policy_version": self.policy.policy_version,
                    "indexed_at": indexed_at,
                    "created_at": scanned.mtime,
                }
            )
            if len(batch) >= batch_size:
                stats.written += self.registry.upsert_artifacts(batch)
                batch.clear()
                if progress is not None:
                    progress(stats)

        if batch:
            stats.written += self.registry.upsert_artifacts(batch)

        if prune:
            stats.removed_stale = self.registry.delete_missing_artifacts(
                sorted(directories), seen
            )

        stats.elapsed_seconds = time.perf_counter() - started
        return {
            "runs_root": str(runs_root),
            "policy": self.policy.describe(),
            "stats": stats.as_dict(),
            "catalog": self.registry.artifact_summary(),
            "indexed_at": indexed_at,
        }
