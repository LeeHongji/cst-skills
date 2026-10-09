"""Promote selected run evidence into a durable research-topic package.

``cst_runs`` is the execution plane.  A topic branch is the archive.  This
module copies only the material needed to understand, review, and reopen a
selected result; it deliberately refuses solver caches and never modifies the
solved source project.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping
from .paths import LabPaths


CURVE_SUFFIXES = frozenset({".s1p", ".s2p", ".s4p", ".csv"})
BANNED_DIRECTORY_NAMES = frozenset({"result", "temp", "modelcache"})
BANNED_SUFFIXES = frozenset(
    {
        ".lok",
        ".lck",
        ".rom",
        ".m3t",
        ".m3d",
        ".fsf",
        ".scf",
        ".sct",
        ".slim",
        ".slv",
        ".sdb",
        ".tet",
        ".tmp",
        ".bak",
    }
)


@dataclass(frozen=True)
class PromotionArtifact:
    role: str
    source: Path


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_relative(path: Path) -> None:
    lowered = {part.casefold() for part in path.parts[:-1]}
    if lowered & BANNED_DIRECTORY_NAMES:
        raise ValueError(f"{path.as_posix()} is inside a forbidden cache directory")
    if path.suffix.casefold() in BANNED_SUFFIXES:
        raise ValueError(f"{path.as_posix()} has forbidden cache/lock suffix {path.suffix}")


def _copy_file(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"refusing to overwrite promoted evidence: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def model_snapshot(project: Path) -> list[dict[str, object]]:
    """Content identity of a closed CST plus Model; independent of its basename."""
    project=Path(project).absolute()
    for parent in (project,*project.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('model snapshot must not traverse links or junctions')
    if project.suffix.casefold()!='.cst' or not project.is_file() or not project.stat().st_size:
        raise ValueError('model snapshot requires a nonempty CST project')
    companion=project.with_suffix('');model=companion/'Model'
    locks=list(companion.rglob('*.lok'))+list(companion.rglob('*.lck'))
    locks += [p for p in (project.with_suffix('.lok'),project.with_suffix('.lck')) if p.exists()]
    if locks:
        raise RuntimeError('source project has locks; Locks are never deleted by promotion')
    if not model.is_dir(): raise ValueError('source project has no companion Model directory')
    records=[dict(path='project.cst',bytes=project.stat().st_size,sha256=_sha256(project))]
    for path in sorted(model.rglob('*')):
        if path.is_symlink() or path.is_junction(): raise ValueError('model companion contains a link')
        relative=path.relative_to(companion)
        if any(part.casefold() in BANNED_DIRECTORY_NAMES for part in relative.parts):
            raise ValueError('model companion contains a forbidden cache directory')
        _clean_relative(relative)
        if path.is_file():records.append(dict(path=relative.as_posix(),bytes=path.stat().st_size,sha256=_sha256(path)))
    if len(records)==1: raise ValueError('source companion Model is empty')
    return records


def copy_clean_model(workspace_root: Path, source: Path, target: Path) -> list[dict[str, object]]:
    """Stage/promote only CST+Model and verify source and copied bytes.

    Both temporary reopen copies and durable promotion use this same policy.
    No cache, lock deletion or native CST API call occurs here.
    """
    root=Path(workspace_root).resolve();source=Path(source).absolute();target=Path(target).absolute()
    if not _inside(source,LabPaths.resolve(root).runs_root):raise ValueError('source project must be inside cst_runs')
    if not any(_inside(target,p) for p in (LabPaths.resolve(root).runs_root,root/'projects')):
        raise ValueError('model target must be inside cst_runs or projects')
    for path in (target,*target.parents):
        if path.is_symlink() or path.is_junction():raise ValueError('model target must not traverse links')
    if target.suffix.casefold()!='.cst':raise ValueError('model target must be a CST file')
    if target.exists() or target.with_suffix('').exists():raise FileExistsError('refusing to overwrite a model copy')
    snapshot=model_snapshot(source)
    _copy_file(source,target)
    shutil.copytree(source.with_suffix('')/'Model',target.with_suffix('')/'Model')
    if model_snapshot(source)!=snapshot or model_snapshot(target)!=snapshot:
        raise ValueError('model changed during copy; partial staging retained')
    return snapshot


def validate_package(evidence_dir: Path) -> list[str]:
    """Return package problems; an empty list means the static archive is clean."""
    root = Path(evidence_dir)
    problems: list[str] = []
    if not root.is_dir():
        return [f"missing evidence directory: {root}"]
    manifests = list(root.glob("manifest.json"))
    if len(manifests) != 1:
        problems.append(f"expected one manifest.json, found {len(manifests)}")
    cst_files = list(root.glob("*.cst"))
    if len(cst_files) != 1:
        problems.append(f"expected one selected .cst, found {len(cst_files)}")
    elif not (cst_files[0].with_suffix("") / "Model").is_dir():
        problems.append("missing selected CST companion Model directory")
    if not any(path.suffix.casefold() in CURVE_SUFFIXES for path in root.rglob("*") if path.is_file()):
        problems.append("missing typed curve evidence (.s1p/.s2p/.s4p/.csv)")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        try:
            _clean_relative(relative)
        except ValueError as exc:
            problems.append(str(exc))
    return problems


def promote_project_package(
    *,
    workspace_root: Path,
    source_project: Path,
    evidence_dir: Path,
    artifacts: Iterable[PromotionArtifact],
    origin_run_uri: str,
    topic_id: str,
    design_id: str,
    attempt_id: str,
    source_commit: str | None = None,
) -> dict[str, object]:
    """Copy a result-free CST model and selected evidence into ``projects``.

    The solved source must be below ``cst_runs`` and the destination below
    ``projects``.  Only the companion ``Model/`` directory is copied:
    ``Result/`` contains recomputable solver output, ``Temp/`` is scratch, and
    ``ModelCache/`` is regenerated by CST.  The source is read-only throughout.
    """
    root = Path(workspace_root).resolve()
    source = Path(source_project).resolve()
    target = Path(evidence_dir).resolve()
    runs_root = LabPaths.resolve(root).runs_root
    projects_root = root / "projects"

    if not _inside(source, runs_root):
        raise ValueError(f"source project must be inside {runs_root}, got {source}")
    if not _inside(target, projects_root):
        raise ValueError(f"evidence directory must be inside {projects_root}, got {target}")
    if source.suffix.casefold() != ".cst" or not source.is_file():
        raise ValueError(f"source project is not an existing .cst: {source}")
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing evidence package: {target}")

    companion = source.with_suffix("")
    locks = list(companion.rglob("*.lok")) + list(companion.rglob("*.lck"))
    if locks:
        raise RuntimeError(
            f"source project has {len(locks)} lock file(s); close its owning CST project "
            "before promotion.  Locks are never deleted by this command."
        )
    model = companion / "Model"
    if not model.is_dir():
        raise ValueError(f"source project has no companion Model directory: {model}")

    supplied = list(artifacts)
    if not supplied:
        raise ValueError("at least one exported artifact is required")
    if not any(item.source.suffix.casefold() in CURVE_SUFFIXES for item in supplied):
        raise ValueError("promotion requires Touchstone or CSV curve evidence")
    roles = [item.role for item in supplied]
    if len(roles) != len(set(roles)):
        raise ValueError(f"artifact roles must be unique, got {roles}")
    for item in supplied:
        artifact = item.source.resolve()
        if not artifact.is_file():
            raise ValueError(f"artifact does not exist: {artifact}")
        if not _inside(artifact, runs_root):
            raise ValueError(f"artifact must come from cst_runs: {artifact}")
        _clean_relative(Path(item.source.name))

    target.mkdir(parents=True)
    selected_name = "selected.cst"
    copy_clean_model(root,source,target / selected_name)

    copied: list[dict[str, object]] = []
    for item in supplied:
        destination = target / "artifacts" / item.role / item.source.name
        _copy_file(item.source.resolve(), destination)
        copied.append(
            {
                "role": item.role,
                "path": destination.relative_to(target).as_posix(),
                "source_run_path": item.source.resolve().relative_to(runs_root).as_posix(),
            }
        )

    files = []
    for path in sorted((item for item in target.rglob("*") if item.is_file())):
        relative = path.relative_to(target)
        _clean_relative(relative)
        files.append(
            {
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    manifest = {
        "schema_version": 1,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "topic_id": topic_id,
        "design_id": design_id,
        "attempt_id": attempt_id,
        "origin_run_uri": origin_run_uri,
        "source_project_run_path": source.relative_to(runs_root).as_posix(),
        "source_commit": source_commit,
        "selected_project": selected_name,
        "companion_policy": "Model only; Result, Temp, and ModelCache excluded",
        "artifacts": copied,
        "files": files,
        "verification": {
            "static_package": "pass",
            "cst_reopen": "pending",
            "ir_comparison": "pending",
        },
    }
    manifest_path = target / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    problems = validate_package(target)
    if problems:
        raise RuntimeError(f"promoted package failed validation: {problems}")
    return {
        "status": "promoted",
        "evidence_dir": str(target),
        "manifest": str(manifest_path),
        "files": len(files) + 1,
        "bytes": sum(int(item["bytes"]) for item in files) + manifest_path.stat().st_size,
        "verification": manifest["verification"],
    }


def parse_artifacts(values: Iterable[str]) -> list[PromotionArtifact]:
    """Parse repeatable ``ROLE=PATH`` command-line values."""
    result = []
    for value in values:
        role, separator, path = value.partition("=")
        if not separator or not role.strip() or not path.strip():
            raise ValueError(f"artifact must be ROLE=PATH, got {value!r}")
        result.append(PromotionArtifact(role.strip(), Path(path.strip())))
    return result
