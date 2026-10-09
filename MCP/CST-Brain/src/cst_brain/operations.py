from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .index import BrainIndex
from .locking import serialized_mutation
from .markdown import (
    read_page,
    render_page,
    safe_name,
    sha256_file,
    stable_id,
    wikilinks,
)
from .paths import BrainPaths


REQUIRED_FIELDS = {
    "id",
    "type",
    "status",
    "title",
    "created",
    "updated",
    "tags",
}
ALLOWED_STATUS = {
    "seed",
    "candidate",
    "case-specific",
    "validated",
    "contradicted",
    "superseded",
    "deprecated",
}
TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".csv",
    ".tsv",
    ".vba",
    ".py",
    ".xml",
    ".yaml",
    ".yml",
}


class BrainOperations:
    def __init__(
        self,
        paths: BrainPaths | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.paths = paths or BrainPaths.resolve()
        self.paths.ensure()
        self.index = BrainIndex(self.paths)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now_iso(self) -> str:
        return self._clock().isoformat()

    def _today_iso(self) -> str:
        return self._clock().date().isoformat()

    def _load_raw_manifest(self) -> dict[str, Any]:
        if not self.paths.raw_manifest.exists():
            return {"schema_version": 1, "sources": {}, "trace_snapshots": {}}
        return json.loads(self.paths.raw_manifest.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _append_log(self, operation: str, title: str, details: list[str]) -> None:
        log_path = self.paths.meta / "log.md"
        metadata, body = read_page(log_path)
        heading = "# Operation Log"
        entry = "\n".join(
            [
                f"## [{self._today_iso()}] {operation} | {title}",
                "",
                *[f"- {detail}" for detail in details],
                "",
            ]
        )
        if heading in body:
            body = body.replace(heading, f"{heading}\n\n{entry}", 1)
        else:
            body = f"{heading}\n\n{entry}\n{body}"
        metadata["updated"] = self._today_iso()
        log_path.write_text(render_page(metadata, body), encoding="utf-8")

    def _add_index_entry(self, heading: str, title: str, relative: str, summary: str) -> None:
        index_path = self.paths.meta / "index.md"
        metadata, body = read_page(index_path)
        link = f"[[{Path(relative).stem}]]"
        if link in body:
            return
        marker = f"## {heading}"
        entry = f"- {link} — {summary}"
        if marker in body:
            body = body.replace(marker, f"{marker}\n\n{entry}", 1)
        else:
            body = f"{body.rstrip()}\n\n{marker}\n\n{entry}\n"
        metadata["updated"] = self._today_iso()
        index_path.write_text(render_page(metadata, body), encoding="utf-8")

    def read_page(self, identifier: str) -> dict[str, Any]:
        direct = (self.paths.root / identifier).resolve()
        if direct.is_file() and self.paths.root in direct.parents:
            metadata, body = read_page(direct)
            return {
                "status": "success",
                "path": direct.relative_to(self.paths.root).as_posix(),
                "metadata": metadata,
                "content": body.strip(),
            }
        matches: list[Path] = []
        needle = identifier.casefold()
        for path in list(self.paths.wiki.rglob("*.md")) + list(self.paths.inbox.rglob("*.md")):
            metadata, _ = read_page(path)
            if (
                path.stem.casefold() == needle
                or str(metadata.get("id", "")).casefold() == needle
                or str(metadata.get("title", "")).casefold() == needle
            ):
                matches.append(path)
        if not matches:
            return {"status": "not_found", "identifier": identifier}
        if len(matches) > 1:
            return {
                "status": "ambiguous",
                "identifier": identifier,
                "matches": [
                    path.relative_to(self.paths.root).as_posix() for path in matches
                ],
            }
        metadata, body = read_page(matches[0])
        return {
            "status": "success",
            "path": matches[0].relative_to(self.paths.root).as_posix(),
            "metadata": metadata,
            "content": body.strip(),
        }

    @serialized_mutation("vault-mutations")
    def ingest_source(
        self,
        source_path: str,
        title: str | None = None,
        source_type: str = "document",
        force: bool = False,
    ) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            return {"status": "error", "error": f"Source file not found: {source}"}
        digest = sha256_file(source)
        manifest = self._load_raw_manifest()
        sources = manifest.setdefault("sources", {})
        existing = next(
            (
                (key, value)
                for key, value in sources.items()
                if value.get("sha256") == digest
            ),
            None,
        )
        if existing and not force:
            return {
                "status": "unchanged",
                "source": existing[0],
                "manifest": existing[1],
            }
        display_title = title or source.stem
        target_name = f"{self._today_iso()}-{safe_name(source.name)}"
        target = self.paths.raw / "sources" / target_name
        if target.exists() and sha256_file(target) != digest:
            target = target.with_name(f"{target.stem}-{digest[:8]}{target.suffix}")
        if not target.exists():
            shutil.copy2(source, target)
        relative_raw = target.relative_to(self.paths.root).as_posix()
        page_name = safe_name(display_title)
        page_path = self.paths.wiki / "sources" / f"{page_name}.md"
        excerpt = ""
        if source.suffix.casefold() in TEXT_EXTENSIONS:
            try:
                excerpt = source.read_text(encoding="utf-8-sig")[:2000].strip()
            except UnicodeDecodeError:
                excerpt = ""
        metadata = {
            "id": stable_id("source", digest),
            "type": "source",
            "status": "candidate",
            "title": display_title,
            "created": self._today_iso(),
            "updated": self._today_iso(),
            "aliases": [],
            "domains": [],
            "cst_versions": [],
            "sources": [f"[[{relative_raw}]]"],
            "evidence": [f"source://sha256/{digest}"],
            "related": [],
            "contradicts": [],
            "supersedes": [],
            "tags": [f"source/{source_type}"],
            "source_type": source_type,
            "sha256": digest,
        }
        body = "\n".join(
            [
                "# Source summary",
                "",
                "This source has been captured immutably. Agent synthesis is pending.",
                "",
                "## Source excerpt",
                "",
                excerpt or "_Binary or non-text source; inspect with the appropriate Skill._",
                "",
                "## Claims to verify",
                "",
                "- _Pending evidence extraction._",
                "",
                "## Connections",
                "",
                "- _Pending cross-reference pass._",
            ]
        )
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(render_page(metadata, body), encoding="utf-8")
        sources[relative_raw] = {
            "sha256": digest,
            "ingested_at": self._now_iso(),
            "source_uri": self.paths.logical_uri(source),
            "source_page": page_path.relative_to(self.paths.root).as_posix(),
        }
        manifest["generated_at"] = self._now_iso()
        self._write_json(self.paths.raw_manifest, manifest)
        self._add_index_entry(
            "Sources",
            display_title,
            page_path.relative_to(self.paths.root).as_posix(),
            f"{source_type}; evidence captured",
        )
        self._append_log(
            "ingest",
            display_title,
            [f"Raw: `{relative_raw}`", f"SHA256: `{digest}`"],
        )
        self.index.build()
        return {
            "status": "success",
            "raw_path": str(target),
            "page_path": str(page_path),
            "sha256": digest,
        }

    @serialized_mutation("vault-mutations")
    def create_candidate(
        self,
        title: str,
        body: str,
        page_type: str = "claim",
        evidence: list[str] | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        safe_title = safe_name(title)
        folder = "strategy-candidates" if page_type == "strategy" else "claims"
        page_path = self.paths.inbox / folder / f"{safe_title}.md"
        if page_path.exists():
            return {"status": "exists", "path": str(page_path)}
        metadata = {
            "id": stable_id(page_type, f"{title}|{self._today_iso()}"),
            "type": page_type,
            "status": "candidate",
            "title": title,
            "created": self._today_iso(),
            "updated": self._today_iso(),
            "aliases": [],
            "domains": [domain] if domain else [],
            "cst_versions": [],
            "sources": [],
            "evidence": evidence or [],
            "related": [],
            "contradicts": [],
            "supersedes": [],
            "tags": [f"inbox/{page_type}"],
        }
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(render_page(metadata, body), encoding="utf-8")
        heading = {
            "strategy": "Optimization strategies",
            "failure": "Failures",
        }.get(page_type, "Open questions")
        self._add_index_entry(
            heading,
            title,
            page_path.relative_to(self.paths.root).as_posix(),
            f"{page_type} candidate; evidence review pending",
        )
        self._append_log("candidate", title, [f"Page: `{self.paths.logical_uri(page_path)}`"])
        self.index.build()
        return {"status": "success", "path": str(page_path), "id": metadata["id"]}

    def _selected_run_files(self, run_dir: Path) -> list[Path]:
        preferred = {
            "final_report.md",
            "status.json",
            "config.json",
            "source_audit.json",
            "clone_comparison.json",
            "reconstruction_status.json",
            "forced_resimulation_status.json",
            "parameters.csv",
            "history_index.csv",
            "history_replay.vba",
            "case-handoff.json",
            "probe-comparison.json",
            "confirmation-comparison.json",
            "source-comparison.json",
            "saved-result-audit.json",
            "validation-report.json",
            "evidence.json",
            "run.json",
        }
        selected: list[Path] = []
        for path in run_dir.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(run_dir)
            top_level = relative.parts[0].casefold()
            suffix = path.suffix.casefold()
            evidence_tree_file = (
                top_level in {"audit", "results"}
                and suffix in TEXT_EXTENSIONS | {".s2p"}
            )
            root_procedure = (
                len(relative.parts) == 1
                and suffix in {".md", ".py", ".json"}
            )
            if (
                path.name in preferred
                or suffix in {".cst", ".s2p"}
                or evidence_tree_file
                or root_procedure
            ):
                selected.append(path)
        return sorted(selected)

    @serialized_mutation("vault-mutations")
    def compile_run(
        self,
        run_path: str,
        case_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        run_dir = Path(run_path).expanduser().resolve()
        if not run_dir.is_dir():
            return {"status": "error", "error": f"Run directory not found: {run_dir}"}
        resolved_case_id = case_id or re.sub(r"[^a-z0-9]+", "-", run_dir.name.casefold()).strip("-")
        display_title = title or run_dir.name.replace("_", " ").title()
        snapshot_dir = self.paths.raw / "trace-snapshots" / resolved_case_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        selected = self._selected_run_files(run_dir)
        artifacts: list[dict[str, Any]] = []
        for path in selected:
            artifacts.append(
                {
                    "uri": self.paths.logical_uri(path),
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                    "kind": path.suffix.casefold().lstrip(".") or "file",
                }
            )
            if path.suffix.casefold() in TEXT_EXTENSIONS and path.stat().st_size <= 2_000_000:
                destination = snapshot_dir / path.relative_to(run_dir)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
        audit_path = next((path for path in selected if path.name == "source_audit.json"), None)
        audit: dict[str, Any] = {}
        if audit_path:
            audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
        comparison_path = next(
            (path for path in selected if path.name == "clone_comparison.json"),
            None,
        )
        comparison: dict[str, Any] = {}
        if comparison_path:
            comparison = json.loads(comparison_path.read_text(encoding="utf-8-sig"))
        lab_handoff_path = next((path for path in selected if path.name == "case-handoff.json"), None)
        lab_handoff: dict[str, Any] = {}
        if lab_handoff_path:
            lab_handoff = json.loads(lab_handoff_path.read_text(encoding="utf-8-sig"))
        probe_comparison_path = next(
            (path for path in selected if path.name == "probe-comparison.json"), None
        )
        probe_comparison: dict[str, Any] = {}
        if probe_comparison_path:
            probe_comparison = json.loads(probe_comparison_path.read_text(encoding="utf-8-sig"))
        confirmation_path = next(
            (
                path
                for path in selected
                if path.name in {"confirmation-comparison.json", "source-comparison.json"}
            ),
            None,
        )
        confirmation: dict[str, Any] = {}
        if confirmation_path:
            confirmation = json.loads(confirmation_path.read_text(encoding="utf-8-sig"))
        lab_audits: list[dict[str, Any]] = []
        for path in selected:
            if path.name != "saved-result-audit.json":
                continue
            try:
                candidate = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if candidate.get("validation", {}).get("status") == "valid":
                lab_audits.append(candidate)
        lab_runs: list[dict[str, Any]] = []
        for path in selected:
            if path.name != "run.json":
                continue
            try:
                candidate = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if candidate.get("source") and candidate.get("target"):
                lab_runs.append(candidate)
        solver_success = bool(audit.get("solver_finished_successfully"))
        parameters = audit.get("parameters") or []
        general = audit.get("general") or {}
        simulation = audit.get("simulation") or {}
        source_project = audit.get("source_cst")
        lab_experiment = lab_handoff.get("experiment") or {}
        lab_trials = lab_handoff.get("trials") or []
        completed_trials = [item for item in lab_trials if item.get("status") == "completed"]
        best_trial_id = probe_comparison.get("best_trial_id")
        best_trial = next(
            (item for item in completed_trials if item.get("trial_id") == best_trial_id),
            completed_trials[0] if completed_trials else None,
        )
        if lab_handoff:
            solver_success = bool(
                lab_experiment.get("status") == "completed"
                and completed_trials
                and len(lab_audits) >= len(completed_trials)
            )
            if best_trial:
                parameters = [
                    {"name": name, "value": value, "descr": "CST-Lab best trial"}
                    for name, value in (best_trial.get("parameters") or {}).items()
                ]
            if lab_runs:
                source_project = lab_runs[0].get("source")
        lab_working_project = None
        if best_trial:
            sequence_marker = f"case_{int(best_trial.get('sequence', 0)) + 1:03d}"
            best_audit = next(
                (item for item in lab_audits if sequence_marker in str(item.get("project", ""))),
                None,
            )
            if best_audit:
                lab_working_project = best_audit.get("project")
        if lab_handoff and confirmation:
            source_project = source_project or confirmation.get("reference")
            lab_working_project = lab_working_project or confirmation.get("candidate")
        if source_project and Path(str(source_project)).exists():
            source_project = self.paths.logical_uri(str(source_project))
        manifest = {
            "schema_version": 1,
            "case_id": resolved_case_id,
            "task_id": run_dir.parent.name,
            "run_id": run_dir.name,
            "run_path": self.paths.logical_uri(run_dir),
            "source_project": source_project,
            "working_project": (
                self.paths.logical_uri(lab_working_project)
                if lab_working_project
                else next(
                    (item["uri"] for item in artifacts if "reconstructed" in item["uri"].casefold() and item["kind"] == "cst"),
                    None,
                )
            ),
            "objective": {},
            "constraints": [],
            "parameters": parameters,
            "solver": {
                "frequency": general.get("frequency") or simulation.get("frequency"),
                "run_options": simulation.get("run_options"),
            },
            "metrics": {
                "solver_finished_successfully": solver_success,
                "broadband_samples": audit.get("broadband_samples"),
                "curve_summaries": audit.get("curve_summaries") or [],
                "comparison": comparison,
                "lab_objectives": best_trial.get("objectives") if best_trial else None,
                "lab_constraints": best_trial.get("constraints") if best_trial else None,
                "trial_comparison": probe_comparison,
                "confirmation": confirmation,
            },
            "status": "validated" if solver_success else "partial",
            "artifacts": artifacts,
            "knowledge_used": [],
            "skills_used": [
                "cst-simulation-workflow",
                "cst-vba-modeling",
                "cst-strategy-learning",
            ],
            "reproducibility": (
                "reproduced"
                if solver_success and (comparison or confirmation.get("status") == "valid")
                else "partial"
            ),
            "compiled_at": self._now_iso(),
        }
        manifest_path = snapshot_dir / "manifest.json"
        self._write_json(manifest_path, manifest)
        raw_manifest = self._load_raw_manifest()
        raw_manifest.setdefault("trace_snapshots", {})[resolved_case_id] = {
            "manifest": manifest_path.relative_to(self.paths.root).as_posix(),
            "run_uri": self.paths.logical_uri(run_dir),
            "compiled_at": manifest["compiled_at"],
        }
        raw_manifest["generated_at"] = manifest["compiled_at"]
        self._write_json(self.paths.raw_manifest, raw_manifest)

        parameter_lines = [
            f"| {item.get('name', '')} | {item.get('value', item.get('expr', ''))} | {item.get('descr', '')} |"
            for item in parameters
        ]
        curve_lines = [
            f"- {item.get('tree_path')}: minimum {item.get('minimum_db')} dB at {item.get('minimum_db_x')} GHz"
            for item in audit.get("curve_summaries") or []
            if str(item.get("tree_path", "")).replace("/", "\\").startswith(
                "1D Results\\S-Parameters\\"
            )
        ]
        if not curve_lines and best_trial:
            curve_lines = [
                *[
                    f"- Objective `{name}`: {value}"
                    for name, value in (best_trial.get("objectives") or {}).items()
                ],
                *[
                    f"- Constraint `{name}`: {value}"
                    for name, value in (best_trial.get("constraints") or {}).items()
                ],
            ]
        frequency = general.get("frequency") or simulation.get("frequency") or {}
        if isinstance(frequency, dict):
            frequency_text = (
                f"{frequency.get('minimum', '?')}–{frequency.get('maximum', '?')} "
                f"{frequency.get('unit', '')}"
            ).strip()
        else:
            frequency_text = str(frequency)
        comparison_lines: list[str] = []
        if comparison:
            comparison_lines = [
                f"- Parameters exact match: {comparison.get('parameters_exact_match')}",
                f"- History exact match: {comparison.get('history_exact_match')}",
                f"- Result tree exact match: {comparison.get('result_tree_exact_match')}",
                f"- Fresh solver success: {comparison.get('fresh_solver_success')}",
            ]
            max_differences = [
                item.get("max_abs_db_difference")
                for item in comparison.get("s_parameter_comparisons") or []
                if item.get("max_abs_db_difference") is not None
            ]
            if max_differences:
                comparison_lines.append(
                    f"- Maximum absolute S-parameter difference: {max(max_differences):.6g} dB"
                )
        if confirmation:
            confirmation_differences = [
                item.get("max_db_difference")
                for item in confirmation.get("comparisons") or []
                if item.get("max_db_difference") is not None
            ]
            comparison_lines.extend(
                [
                    f"- Independent confirmation: {confirmation.get('status')}",
                    *(
                        [f"- Confirmation maximum S-parameter difference: {max(confirmation_differences):.6g} dB"]
                        if confirmation_differences
                        else []
                    ),
                ]
            )
        failure_lines = [
            "- Direct replay of topology-dependent History can fail when transient face IDs no longer resolve."
        ] if (run_dir / "failed_history_replay").exists() else []
        recovery_lines = [
            "- Recovery used an immutable source snapshot, a native project clone, result deletion, a fresh solve, and numerical comparison."
        ] if comparison.get("fresh_solver_success") else []
        case_metadata = {
            "id": f"case-{resolved_case_id}",
            "type": "case",
            "status": "case-specific",
            "title": display_title,
            "created": self._today_iso(),
            "updated": self._today_iso(),
            "aliases": [],
            "domains": ["microwave-engineering"],
            "cst_versions": [str(general.get("version"))] if general.get("version") else [],
            "sources": [f"[[{manifest_path.relative_to(self.paths.root).as_posix()}]]"],
            "evidence": [f"trace://{resolved_case_id}"],
            "related": [],
            "contradicts": [],
            "supersedes": [],
            "reproduces": [],
            "uses_skill": [
                "[[cst-simulation-workflow]]",
                "[[cst-vba-modeling]]",
            ],
            "uses_tool": ["[[CST MCP]]"],
            "tags": ["memory/case", "cst/validated-run"],
        }
        body = "\n".join(
            [
                "# Objective",
                "",
                (
                    str(lab_experiment.get("spec", {}).get("hypothesis"))
                    if lab_handoff
                    else f"Compile and preserve the validated CST run at `{self.paths.logical_uri(run_dir)}`."
                ),
                "",
                "# Model and solver",
                "",
                f"- CST version: {general.get('version', 'unknown')}",
                f"- Frequency: {frequency_text}",
                f"- Parameters: {len(parameters)}",
                f"- History entries: {audit.get('history_count', lab_audits[0].get('history_count', 'unknown') if lab_audits else 'unknown')}",
                "",
                "## Parameters",
                "",
                "| Name | Value | Description |",
                "| --- | ---: | --- |",
                *parameter_lines,
                "",
                "# Trace summary",
                "",
                f"- Artifact count: {len(artifacts)}",
                f"- Completed CST-Lab trials: {len(completed_trials)}",
                f"- Solver validated: {solver_success}",
                f"- Reproducibility: {manifest['reproducibility']}",
                "",
                "# Results",
                "",
                *(curve_lines or ["- No parsed S-parameter summary was available."]),
                "",
                "## Reconstruction comparison",
                "",
                *(comparison_lines or ["- No reconstruction comparison was available."]),
                "",
                "# Failures and recoveries",
                "",
                *(failure_lines or ["- No failed attempt was captured in this run."]),
                *(recovery_lines or ["- No recovery step was recorded."]),
                "",
                "# Reusable lessons",
                "",
                "- This page is case-specific. Promote general lessons only after independent evidence.",
                "",
                "# Evidence",
                "",
                f"- [[{manifest_path.relative_to(self.paths.root).as_posix()}]]",
            ]
        )
        case_path = self.paths.wiki / "cases" / f"{safe_name(display_title)}.md"
        case_path.parent.mkdir(parents=True, exist_ok=True)
        case_path.write_text(render_page(case_metadata, body), encoding="utf-8")
        self._add_index_entry(
            "Cases",
            display_title,
            case_path.relative_to(self.paths.root).as_posix(),
            f"{manifest['status']} CST run; {len(parameters)} parameters",
        )
        self._append_log(
            "compile-run",
            display_title,
            [
                f"Run: `{self.paths.logical_uri(run_dir)}`",
                f"Manifest: `{manifest_path.relative_to(self.paths.root).as_posix()}`",
                f"Status: `{manifest['status']}`",
            ],
        )
        self.index.build()
        return {
            "status": "success",
            "case_id": resolved_case_id,
            "case_path": str(case_path),
            "manifest_path": str(manifest_path),
            "artifact_count": len(artifacts),
            "run_status": manifest["status"],
        }

    def get_case(self, identifier: str) -> dict[str, Any]:
        result = self.read_page(identifier)
        if result.get("status") == "success" and result["metadata"].get("type") != "case":
            return {"status": "wrong_type", "identifier": identifier}
        return result

    def get_trace(self, case_id: str) -> dict[str, Any]:
        manifest = self.paths.raw / "trace-snapshots" / case_id / "manifest.json"
        if not manifest.exists():
            return {"status": "not_found", "case_id": case_id}
        return {
            "status": "success",
            "case_id": case_id,
            "manifest_path": str(manifest),
            "manifest": json.loads(manifest.read_text(encoding="utf-8")),
        }

    def list_strategies(self, validated_only: bool = False) -> dict[str, Any]:
        pages: list[dict[str, Any]] = []
        for path in list((self.paths.wiki / "optimization-strategies").rglob("*.md")) + list(
            (self.paths.inbox / "strategy-candidates").rglob("*.md")
        ):
            metadata, _ = read_page(path)
            if validated_only and metadata.get("status") != "validated":
                continue
            pages.append(
                {
                    "path": path.relative_to(self.paths.root).as_posix(),
                    "id": metadata.get("id"),
                    "title": metadata.get("title") or path.stem,
                    "status": metadata.get("status"),
                    "domains": metadata.get("domains") or [],
                    "evidence": metadata.get("evidence") or [],
                }
            )
        return {"status": "success", "strategies": pages}

    @serialized_mutation("vault-mutations")
    def promote(self, identifier: str, human_approved: bool = False) -> dict[str, Any]:
        result = self.read_page(identifier)
        if result.get("status") != "success":
            return result
        path = self.paths.root / result["path"]
        metadata = result["metadata"]
        evidence = metadata.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = [evidence]
        if len(set(map(str, evidence))) < 2 and not human_approved:
            return {
                "status": "insufficient_evidence",
                "identifier": identifier,
                "evidence_count": len(set(map(str, evidence))),
                "required": "two independent evidence references or explicit human approval",
            }
        metadata["status"] = "validated"
        metadata["updated"] = self._today_iso()
        if human_approved:
            metadata["human_approved"] = self._today_iso()
        destination = path
        if self.paths.inbox in path.parents:
            folder = {
                "strategy": "optimization-strategies",
                "failure": "failures",
                "case": "cases",
                "source": "sources",
            }.get(str(metadata.get("type")), "concepts")
            destination = self.paths.wiki / folder / path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render_page(metadata, result["content"]), encoding="utf-8")
        if destination != path:
            path.unlink()
        self._append_log(
            "promote",
            str(metadata.get("title") or path.stem),
            [f"Page: `{self.paths.logical_uri(destination)}`"],
        )
        self.index.build()
        return {
            "status": "success",
            "path": str(destination),
            "new_status": "validated",
        }

    def lint(self) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        pages = list(self.paths.wiki.rglob("*.md")) + list(self.paths.inbox.rglob("*.md"))
        stems: dict[str, list[str]] = {}
        ids: dict[str, list[str]] = {}
        for path in pages:
            relative = path.relative_to(self.paths.root).as_posix()
            metadata, body = read_page(path)
            stems.setdefault(path.stem.casefold(), []).append(relative)
            if metadata.get("id"):
                ids.setdefault(str(metadata["id"]), []).append(relative)
            missing = sorted(REQUIRED_FIELDS - set(metadata))
            if missing:
                issues.append({"severity": "error", "code": "missing_frontmatter", "path": relative, "fields": missing})
            if metadata.get("status") and metadata.get("status") not in ALLOWED_STATUS:
                issues.append({"severity": "error", "code": "invalid_status", "path": relative, "value": metadata.get("status")})
            if metadata.get("status") == "validated" and metadata.get("type") != "meta":
                evidence = metadata.get("evidence") or []
                sources = metadata.get("sources") or []
                if not evidence and not sources:
                    issues.append({"severity": "error", "code": "validated_without_evidence", "path": relative})
            for link in wikilinks(body):
                if Path(link).stem.casefold() not in stems:
                    # Resolve after all pages have been seen.
                    pass
        for page_id, matches in ids.items():
            if len(matches) > 1:
                issues.append({"severity": "error", "code": "duplicate_id", "id": page_id, "paths": matches})
        for stem, matches in stems.items():
            if len(matches) > 1:
                issues.append({"severity": "warning", "code": "duplicate_filename", "stem": stem, "paths": matches})
        known = set(stems)
        for path in pages:
            relative = path.relative_to(self.paths.root).as_posix()
            _, body = read_page(path)
            for link in wikilinks(body):
                direct = self.paths.root / link
                markdown = self.paths.root / f"{link}.md"
                if (
                    Path(link).stem.casefold() not in known
                    and not direct.exists()
                    and not markdown.exists()
                ):
                    issues.append({"severity": "warning", "code": "broken_wikilink", "path": relative, "target": link})
        return {
            "status": "clean" if not issues else "issues_found",
            "page_count": len(pages),
            "issue_count": len(issues),
            "issues": issues,
        }
