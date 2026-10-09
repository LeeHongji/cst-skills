"""Publish Function facade iterations into the evidence-backed Brain.

The Function facade owns the append-only Lab record.  This module creates a
readable Brain projection from that record without copying or rewriting the
scientific fact.  The projection is deliberately immutable by identity: a
different history hash produces a different snapshot directory and page.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .locking import MutationLock
from .markdown import render_page, safe_name, stable_id
from .operations import BrainOperations
from .paths import BrainPaths


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workspace_uri(path: Path, workspace_root: Path) -> str:
    try:
        return f"workspace://{path.resolve().relative_to(workspace_root.resolve()).as_posix()}"
    except ValueError:
        return str(path.resolve())


def _load_iteration(history: Path, iteration: int) -> dict[str, Any]:
    for raw in history.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        if row.get("iter") == iteration:
            return row
    raise ValueError(f"iteration {iteration} is not present in {history}")


def publish_function_iteration(
    *,
    history: str | Path,
    fact_file: str | Path,
    request_file: str | Path,
    job_ref: str,
    workspace_root: str | Path,
    brain_root: str | Path | None = None,
) -> dict[str, Any]:
    """Project one finalized Function iteration into Brain.

    ``fact_file`` is written by the Function worker after finalization.  The
    exact JSON line is read back from ``history`` and must match the supplied
    fact, so a stale or mismatched sidecar cannot silently become knowledge.
    """

    history_path = Path(history).expanduser().resolve()
    fact = json.loads(Path(fact_file).read_text(encoding="utf-8"))
    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    workspace = Path(workspace_root).expanduser().resolve()
    if not history_path.is_file():
        raise FileNotFoundError(history_path)
    row = _load_iteration(history_path, int(fact["iter"]))
    if row != fact:
        raise ValueError("fact sidecar differs from the append-only iteration line")
    if fact.get("job_id") != job_ref:
        raise ValueError("fact job_id differs from the requested job reference")

    paths = BrainPaths.resolve(brain_root or (workspace / "brain"))
    paths.ensure()
    history_sha = _sha256(history_path)
    topic = str(request["topic"])
    design = str(request["design"])
    attempt = str(request["attempt"])
    iteration = int(fact["iter"])
    case_id = (
        f"function-{safe_name(topic)}-{safe_name(design)}-"
        f"{safe_name(attempt)}-iter-{iteration:04d}-{history_sha[:12]}"
    ).replace(" ", "-").lower()
    snapshot = paths.raw / "trace-snapshots" / case_id
    manifest_path = snapshot / "manifest.json"
    page_path = paths.wiki / "cases" / f"Function iteration {topic} {design} {attempt} #{iteration}.md"
    now = datetime.now(timezone.utc).isoformat()

    manifest = {
        "schema_version": 1,
        "kind": "function-iteration",
        "case_id": case_id,
        "title": f"Function iteration {topic}/{design}/{attempt} #{iteration}",
        "published_at": now,
        "source": {
            "history_uri": _workspace_uri(history_path, workspace),
            "history_sha256": history_sha,
            "iteration": iteration,
            "job_id": job_ref,
        },
        "request": {
            "topic": topic,
            "design": design,
            "attempt": attempt,
            "request_id": request.get("request_id"),
            "operation": request.get("operation"),
            "why": request.get("why"),
        },
        "fact": fact,
        "evidence": sorted(set((fact.get("artifacts") or {}).values())),
    }

    body = "\n".join(
        [
            "# Function iteration / 函数迭代",
            "",
            "This page is a searchable projection of the append-only CST-Lab iteration. "
            "The JSONL line remains the source of truth; this page does not replace it.",
            "",
            "## Identity / 标识",
            "",
            f"- Topic: `{topic}`; design: `{design}`; attempt: `{attempt}`; iter: `{iteration}`",
            f"- Fidelity: `{fact.get('fidelity')}`; provenance: `{fact.get('provenance')}`; "
            f"status: `{fact.get('status')}`; audited: `{fact.get('audited')}`",
            f"- Parent: `{fact.get('parent')}`; job: `{job_ref}`",
            f"- History: `{manifest['source']['history_uri']}` (SHA-256 `{history_sha}`)",
            "",
            "## What changed / 变化",
            "",
            f"- Parameter delta: `{json.dumps(fact.get('param_delta') or {}, ensure_ascii=False, sort_keys=True)}`",
            f"- Setup delta: `{json.dumps(fact.get('setup_delta') or {}, ensure_ascii=False, sort_keys=True)}`",
            f"- DRC: `{fact.get('drc')}`; execution kind: `{fact.get('execution_kind')}`; "
            f"cache hit: `{fact.get('cache_hit')}`",
            f"- Observation: {fact.get('observation') or request.get('why') or '未提供'}",
            "",
            "## Result / 结果",
            "",
            f"- Acceptance: `{(fact.get('acceptance') or {}).get('status', 'not_evaluated')}`",
            f"- Metrics: `{json.dumps(fact.get('metrics') or {}, ensure_ascii=False, sort_keys=True)}`",
            f"- Evidence refs: {len(manifest['evidence'])}",
            "",
            "## Evidence / 证据",
            "",
            *[f"- `{ref}`" for ref in manifest["evidence"]],
            "",
            "## Raw fact / 原始事实",
            "",
            "```json",
            json.dumps(fact, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    metadata = {
        "id": stable_id("function-iteration", f"{case_id}|{history_sha}"),
        "type": "case",
        "status": "case-specific",
        "title": manifest["title"],
        "created": now[:10],
        "updated": now[:10],
        "aliases": [f"{topic}/{design}/{attempt} iter {iteration}"],
        "domains": ["cst-function", "microwave-engineering"],
        "cst_versions": [],
        "sources": [f"[[{manifest_path.relative_to(paths.root).as_posix()}]]"],
        "evidence": manifest["evidence"],
        "related": [],
        "contradicts": [],
        "supersedes": [],
        "reproduces": [],
        "uses_skill": ["[[cst-experiment-orchestration]]", "[[cst-strategy-learning]]"],
        "uses_tool": ["[[cst_run]]", "[[cst_get]]", "[[cst_approve]]"],
        "tags": ["memory/case", "cst/function-iteration", f"topic/{topic}", f"fidelity/{fact.get('fidelity')}", f"provenance/{fact.get('provenance')}"],
    }

    # One lock covers manifest, page, raw index registration, and BM25 rebuild.
    with MutationLock(paths, "function-iteration-publication"):
        if manifest_path.exists():
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            if previous.get("source", {}).get("history_sha256") == history_sha and page_path.exists():
                return {"status": "unchanged", "case_id": case_id, "manifest": str(manifest_path), "page": str(page_path),
                        "evidence_count": len(previous.get('evidence', []))}
        snapshot.mkdir(parents=True, exist_ok=True)
        operations = BrainOperations(paths)
        operations._write_json(manifest_path, manifest)
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(render_page(metadata, body), encoding="utf-8")
        raw = operations._load_raw_manifest()
        raw.setdefault("trace_snapshots", {})[case_id] = {
            "manifest": manifest_path.relative_to(paths.root).as_posix(),
            "run_uri": manifest["source"]["history_uri"],
            "compiled_at": now,
            "kind": "function-iteration",
        }
        raw["generated_at"] = now
        operations._write_json(paths.raw_manifest, raw)
        operations.index.build()
    return {"status": "published", "case_id": case_id, "manifest": str(manifest_path), "page": str(page_path), "evidence_count": len(manifest["evidence"])}
