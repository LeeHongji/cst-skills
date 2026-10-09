"""Create and validate uniform research-topic workspaces.

The four research contracts remain ``topic.md``, ``design.md``,
``attempt.json`` and ``iterations.jsonl``.  This module supplies the missing
operational layer around them: every new topic starts with the same files, and a
single validator checks identifiers, model/IR links, append-only history and
promoted evidence hashes.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import load_attempt, load_design, load_topic, read_iterations
from .contracts.design import write_design
from .contracts.topic import write_topic
from .project_package import validate_package

_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _require_id(value: str, label: str) -> str:
    if not _ID.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase kebab-case id, got {value!r}")
    return value


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _agent_instructions(topic_id: str) -> str:
    return f"""# Topic workspace: {topic_id}

Read in this order before changing the topic:

1. `README.md` for current state and next action.
2. `topic.md` for scope, shared physics, and source provenance.
3. The selected `designs/<design-id>/design.md` for machine-readable gates.
4. The selected attempt's `attempt.json`, `iterations.jsonl`, and latest evidence.

Keep all durable topic knowledge and selected evidence below this directory.
Use `cst_runs/` only for task-owned working copies and solver caches. Never edit
a source `.cst`, delete a `.lok`, or commit `Result/`, `Temp/`, `ModelCache/`,
meshes, or ROMs. A CST write must use the Guardian worker. Append iterations;
do not rewrite historical JSONL lines.
"""


def _operations(topic_id: str) -> str:
    return f"""# Operating environment

- Branch: `topic/{topic_id}`
- Durable root: `projects/{topic_id}/`
- Transient execution root: `cst_runs/`
- Python: 3.13, using the component-local virtual environments
- CST writes: task-owned project copy through the Guardian worker only
- Result evidence: exported Touchstone/CSV, plots, metrics, concise logs, IR,
  DRC, History/VBA, and a result-free reopenable CST package

## Validation

```powershell
MCP/CST-Lab/.venv/Scripts/python.exe -m cst_lab validate-topic projects/{topic_id}
```

Run this before and after a research session. A run is not durable until
promotion has produced and validated `evidence/manifest.json`.
"""


def init_topic(
    workspace_root: Path,
    *,
    topic_id: str,
    title: str,
    shared_physics: Iterable[str],
    sources: Iterable[Mapping[str, str]],
) -> Path:
    """Create one complete, valid topic-level workspace without overwriting."""
    topic_id = _require_id(topic_id, "topic_id")
    physics = [str(value).strip() for value in shared_physics if str(value).strip()]
    source_list = [dict(value) for value in sources]
    if not title.strip() or not physics or not source_list:
        raise ValueError("title, at least one shared-physics statement, and one source are required")

    projects = Path(workspace_root).resolve() / "projects"
    target = projects / topic_id
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing topic workspace: {target}")
    staging = projects / f".{topic_id}.initializing"
    if staging.exists():
        raise FileExistsError(f"stale initialization directory exists: {staging}")
    staging.mkdir(parents=True)
    try:
        write_topic(
            staging / "topic.md",
            {
                "schema_version": 1,
                "topic_id": topic_id,
                "title": title.strip(),
                "shared_physics": physics,
                "sources": source_list,
                "status": "active",
                "created": date.today().isoformat(),
                "notes_path": "notes.md",
            },
            f"# {title.strip()}\n\n## Scope\n\nDefine what belongs in this topic.\n\n"
            "## Shared physical basis\n\nExpand the transferable mechanisms listed in frontmatter.\n",
        )
        _write(
            staging / "README.md",
            f"# {title.strip()}\n\n"
            "## Current state\n\nNew topic; no design has been registered.\n\n"
            "## Best validated result\n\nNone.\n\n"
            "## Next action\n\nCreate a design with machine-readable acceptance gates.\n",
        )
        _write(staging / "notes.md", "# Topic notes\n\nNo promoted lessons yet.\n")
        _write(staging / "AGENTS.md", _agent_instructions(topic_id))
        _write(staging / "OPERATIONS.md", _operations(topic_id))
        _write(
            staging / "designs" / "README.md",
            "# Designs\n\nEach child is one device with `design.md`, `model.py`, and `attempts/`.\n",
        )
        staging.replace(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def init_design(
    topic_dir: Path,
    *,
    design_id: str,
    title: str,
    ports: int,
    acceptance: Iterable[Mapping[str, Any]],
    model: str = "model.py",
) -> Path:
    """Add a valid design skeleton; attempts wait until an IR exists."""
    topic_dir = Path(topic_dir).resolve()
    topic, _ = load_topic(topic_dir / "topic.md")
    design_id = _require_id(design_id, "design_id")
    gates = [dict(value) for value in acceptance]
    if not gates:
        raise ValueError("at least one machine-readable acceptance gate is required")
    target = topic_dir / "designs" / design_id
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing design: {target}")
    target.mkdir(parents=True)
    try:
        write_design(
            target / "design.md",
            {
                "schema_version": 1,
                "design_id": design_id,
                "topic_id": topic["topic_id"],
                "title": title.strip(),
                "model": model,
                "ports": int(ports),
                "acceptance": gates,
                "status": "open",
                "created": date.today().isoformat(),
            },
            f"# {title.strip()}\n\n## Goal\n\nState the device goal and interpretation decisions.\n\n"
            "## Known state\n\nNo attempt has been created.\n",
        )
        _write(
            target / model,
            '"""Parametric geometry source for this design."""\n\n'
            "def build(overrides=None):\n"
            '    raise NotImplementedError("define the geometry IR before creating an attempt")\n',
        )
        _write(
            target / "attempts" / "README.md",
            "# Attempts\n\nOne directory per topology. Generate `attempt.json` from its geometry IR.\n",
        )
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_manifest(evidence: Path, expected: Mapping[str, str]) -> list[str]:
    problems = validate_package(evidence)
    manifest_path = evidence / "manifest.json"
    if not manifest_path.is_file():
        return problems
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [*problems, f"{manifest_path}: invalid manifest: {exc}"]
    if not isinstance(manifest, dict):
        return [*problems, f"{manifest_path}: manifest must be an object"]
    for key, value in expected.items():
        if manifest.get(key) != value:
            problems.append(f"{manifest_path}: {key} is {manifest.get(key)!r}, expected {value!r}")
    verification = manifest.get("verification") or {}
    if not isinstance(verification, dict):
        verification = {}
    for check in ("static_package", "cst_reopen", "ir_comparison"):
        if verification.get(check) != "pass":
            problems.append(
                f"{manifest_path}: verification.{check} is "
                f"{verification.get(check)!r}, expected 'pass'"
            )
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        return [*problems, f"{manifest_path}: files must be a nonempty list"]
    covered: set[str] = set()
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            problems.append(f"{manifest_path}: invalid file entry")
            continue
        relative = Path(item["path"])
        path = (evidence / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(evidence.resolve()):
            problems.append(f"{manifest_path}: file path escapes evidence: {item['path']!r}")
            continue
        key = relative.as_posix().casefold()
        if key in covered:
            problems.append(f"{manifest_path}: duplicate file entry {item['path']!r}")
        covered.add(key)
        if not path.is_file():
            problems.append(f"{manifest_path}: missing hashed file {item.get('path')!r}")
            continue
        if path.stat().st_size != item.get("bytes"):
            problems.append(f"{manifest_path}: byte count changed for {item['path']}")
        if _sha256(path) != item.get("sha256"):
            problems.append(f"{manifest_path}: SHA-256 changed for {item['path']}")
    actual = {p.relative_to(evidence).as_posix().casefold() for p in evidence.rglob("*")
              if p.is_file() and p != manifest_path}
    for missing in sorted(actual - covered):
        problems.append(f"{manifest_path}: file not covered by manifest: {missing}")
    return problems


def validate_topic_workspace(topic_dir: Path) -> dict[str, Any]:
    """Validate a topic and every design/attempt/evidence package below it."""
    root = Path(topic_dir).resolve()
    problems: list[str] = []
    warnings: list[str] = []
    counts = {"designs": 0, "attempts": 0, "iterations": 0, "evidence_packages": 0}

    for required in ("README.md", "AGENTS.md", "OPERATIONS.md", "notes.md", "topic.md"):
        if not (root / required).is_file():
            problems.append(f"missing required topic file: {required}")
    try:
        topic, _ = load_topic(root / "topic.md")
    except Exception as exc:  # noqa: BLE001 - aggregate all contract errors
        return {"status": "invalid", "topic_dir": str(root), "problems": [str(exc)], "warnings": [], **counts}

    designs_root = root / "designs"
    if not designs_root.is_dir():
        problems.append("missing designs/ directory")
        design_dirs: list[Path] = []
    else:
        design_dirs = sorted(path for path in designs_root.iterdir() if path.is_dir())
    for design_dir in design_dirs:
        counts["designs"] += 1
        try:
            design, _gates, _ = load_design(design_dir / "design.md")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{design_dir}: {exc}")
            continue
        if design["topic_id"] != topic["topic_id"]:
            problems.append(f"{design_dir}: topic_id does not match {topic['topic_id']!r}")
        model_path = (design_dir / design["model"]).resolve()
        if not model_path.is_relative_to(design_dir.resolve()):
            problems.append(f"{design_dir}: model source escapes design directory")
        elif not model_path.is_file():
            problems.append(f"{design_dir}: model source {design['model']!r} is missing")
        attempts_root = design_dir / "attempts"
        if not attempts_root.is_dir():
            problems.append(f"{design_dir}: missing attempts/ directory")
            continue
        for attempt_dir in sorted(path for path in attempts_root.iterdir() if path.is_dir()):
            counts["attempts"] += 1
            try:
                attempt = load_attempt(attempt_dir / "attempt.json")
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{attempt_dir}: {exc}")
                continue
            for key, expected in (
                ("topic_id", topic["topic_id"]),
                ("design_id", design["design_id"]),
                ("attempt_id", attempt_dir.name),
            ):
                if attempt.get(key) != expected:
                    problems.append(f"{attempt_dir}: {key} is {attempt.get(key)!r}, expected {expected!r}")
            iterations = attempt_dir / "iterations.jsonl"
            rows = []
            if not iterations.is_file():
                problems.append(f"{attempt_dir}: missing iterations.jsonl")
            else:
                try:
                    rows = read_iterations(iterations)
                    counts["iterations"] += len(rows)
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"{iterations}: {exc}")
            evidence = attempt_dir / "evidence"
            has_evidence = evidence.is_dir()
            if evidence.is_dir():
                counts["evidence_packages"] += 1
                problems.extend(
                    _validate_manifest(
                        evidence,
                        {
                            "topic_id": topic["topic_id"],
                            "design_id": design["design_id"],
                            "attempt_id": attempt["attempt_id"],
                        },
                    )
                )
            revisions = attempt_dir / 'evidence-revisions'
            if revisions.is_dir():
                from .function_evidence import validate_revision
                for revision in sorted(revisions.iterdir()):
                    if not revision.is_dir():
                        problems.append(f'{revision}: unexpected item in evidence-revisions')
                        continue
                    try:
                        facts = [r for r in rows if r.get('evidence',{}).get('revision')==revision.name]
                        if len(facts)!=1:
                            raise ValueError('revision must be bound to exactly one finalized iteration')
                        doc = validate_revision(revision,facts[0]['evidence']['manifest_sha256'])
                        if doc['job']!=facts[0]['job_id']:
                            raise ValueError('revision job differs from iteration')
                        counts['evidence_packages']+=1
                        has_evidence = True
                    except Exception as exc:
                        problems.append(f'{revision}: {exc}')
            if not has_evidence:
                warnings.append(f"{attempt_dir}: no promoted evidence package yet")
            for row in rows:
                binding=row.get('evidence')
                if binding and not (revisions/binding['revision']).is_dir():
                    problems.append(f'{attempt_dir}: iteration {row["iter"]} evidence revision is missing')

    return {
        "status": "valid" if not problems else "invalid",
        "topic_dir": str(root),
        **counts,
        "problems": problems,
        "warnings": warnings,
    }
