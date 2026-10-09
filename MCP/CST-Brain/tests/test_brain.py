from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from cst_brain import BrainIndex, BrainOperations, BrainPaths
from cst_brain.index import tokenize
from cst_brain.markdown import read_page, render_page


def scaffold(tmp_path: Path) -> BrainPaths:
    paths = BrainPaths.resolve(tmp_path / "brain")
    paths.ensure()
    (paths.raw_manifest).write_text(
        '{"schema_version": 1, "sources": {}, "trace_snapshots": {}}\n',
        encoding="utf-8",
    )
    for name, title in (("index.md", "Index"), ("log.md", "Log")):
        (paths.meta / name).write_text(
            render_page(
                {
                    "id": f"meta-{name}",
                    "type": "meta",
                    "status": "validated",
                    "title": title,
                    "created": "2026-07-29",
                    "updated": "2026-07-29",
                    "tags": ["meta/test"],
                    "evidence": ["test://fixture"],
                },
                f"# {title}",
            ),
            encoding="utf-8",
        )
    return paths


def test_tokenize_supports_chinese_english_and_units() -> None:
    tokens = tokenize("发夹滤波器 Hairpin Filter 10GHz 0.8mm Ω")
    assert "hairpin" in tokens
    assert "filter" in tokens
    assert "10ghz" in tokens
    assert "滤波器" in tokens or "滤波" in tokens
    assert "Ω".casefold() in tokens


def test_bm25_search_and_context_pack(tmp_path: Path) -> None:
    paths = scaffold(tmp_path)
    page = paths.wiki / "foundations" / "Hairpin Filter.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        render_page(
            {
                "id": "foundation-hairpin-filter",
                "type": "foundation",
                "status": "validated",
                "title": "Hairpin Filter 发夹滤波器",
                "created": "2026-07-29",
                "updated": "2026-07-29",
                "tags": ["microwave/filter"],
                "evidence": ["source://book-a", "source://paper-b"],
            },
            "# Principle\n\n发夹滤波器使用折叠的半波谐振器与相邻耦合。",
        ),
        encoding="utf-8",
    )
    index = BrainIndex(paths)
    built = index.build()
    result = index.search("发夹滤波器 hairpin")
    broad_result = index.search("filter resonator coupling")
    title_result = index.search("hairpin filter")
    context = index.context_pack("谐振器耦合", mode="quick")
    assert built["document_count"] == 3
    assert result["results"][0]["id"] == "foundation-hairpin-filter"
    assert broad_result["results"][0]["id"] == "foundation-hairpin-filter"
    assert title_result["results"][0]["id"] == "foundation-hairpin-filter"
    assert any(item["id"] == "foundation-hairpin-filter" for item in context["pages"])
    assert json.dumps(context, ensure_ascii=False)


def test_promotion_requires_evidence_or_human_approval(tmp_path: Path) -> None:
    paths = scaffold(tmp_path)
    operations = BrainOperations(
        paths,
        clock=lambda: datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
    )
    created = operations.create_candidate(
        "Single run claim",
        "# Claim\n\nA single observation.",
        evidence=["trace://run-1"],
    )
    denied = operations.promote(created["id"])
    approved = operations.promote(created["id"], human_approved=True)
    metadata, _ = read_page(Path(approved["path"]))
    assert denied["status"] == "insufficient_evidence"
    assert approved["new_status"] == "validated"
    assert "wiki" in Path(approved["path"]).parts
    assert not Path(created["path"]).exists()
    assert metadata["status"] == "validated"
    assert metadata["human_approved"] == "2026-07-29"


def test_lint_detects_broken_links_and_ungrounded_validation(tmp_path: Path) -> None:
    paths = scaffold(tmp_path)
    page = paths.wiki / "bad.md"
    page.write_text(
        render_page(
            {
                "id": "bad",
                "type": "claim",
                "status": "validated",
                "title": "Bad",
                "created": "2026-07-29",
                "updated": "2026-07-29",
                "tags": [],
            },
            "# Claim\n\nSee [[Missing Page]].",
        ),
        encoding="utf-8",
    )
    result = BrainOperations(paths).lint()
    codes = {issue["code"] for issue in result["issues"]}
    assert "validated_without_evidence" in codes
    assert "broken_wikilink" in codes


def test_compile_run_creates_case_and_immutable_manifest(tmp_path: Path) -> None:
    paths = scaffold(tmp_path)
    run = tmp_path / "cst_runs" / "task-1" / "run-1"
    audit = run / "audit"
    audit.mkdir(parents=True)
    (audit / "source_audit.json").write_text(
        json.dumps(
            {
                "source_cst": "C:/source/Planar Filter.cst",
                "solver_finished_successfully": True,
                "history_count": 42,
                "parameters": [
                    {"name": "f0", "value": "10", "descr": "Center frequency"}
                ],
                "general": {"version": "2026.2", "frequency": "8-12 GHz"},
                "curve_summaries": [
                    {
                        "tree_path": "1D Results/S-Parameters/S1,1",
                        "minimum_db": -22.5,
                        "minimum_db_x": 10.1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (audit / "clone_comparison.json").write_text(
        '{"topology_equal": true}\n',
        encoding="utf-8",
    )
    (run / "reconstructed.cst").write_bytes(b"CST-fixture")

    result = BrainOperations(paths).compile_run(
        str(run),
        case_id="planar-filter-test",
        title="Planar Filter Test",
    )
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    schema_path = Path(__file__).resolve().parents[3] / "brain" / "schemas" / "run-manifest.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(manifest, schema)
    metadata, body = read_page(Path(result["case_path"]))
    assert result["run_status"] == "validated"
    assert manifest["reproducibility"] == "reproduced"
    assert manifest["artifacts"]
    assert metadata["status"] == "case-specific"
    assert "S1,1" in body


def test_compile_run_understands_completed_cst_lab_experiment(tmp_path: Path) -> None:
    paths = scaffold(tmp_path)
    run = tmp_path / "cst_runs" / "filter-move"
    case = run / "manual-probes-v2" / "case_001"
    audit_root = case / "audit.json"
    audit_root.mkdir(parents=True)
    project = case / "working.cst"
    project.write_bytes(b"CST")
    (case / "run.json").write_text(
        json.dumps({"source": str(tmp_path / "baseline.cst"), "target": str(project)}),
        encoding="utf-8",
    )
    (audit_root / "saved-result-audit.json").write_text(
        json.dumps(
            {
                "project": str(project),
                "history_count": 22,
                "validation": {"status": "valid"},
            }
        ),
        encoding="utf-8",
    )
    trial = {
        "trial_id": "trial-test-0000",
        "sequence": 0,
        "status": "completed",
        "parameters": {"L1": 360.0},
        "objectives": {"resonance": 4.187},
        "constraints": {"s11_db": -52.7},
    }
    (run / "case-handoff.json").write_text(
        json.dumps(
            {
                "experiment": {
                    "status": "completed",
                    "spec": {"hypothesis": "Shorter resonators move the passband upward."},
                },
                "trials": [trial],
            }
        ),
        encoding="utf-8",
    )
    (run / "probe-comparison.json").write_text(
        json.dumps({"best_trial_id": trial["trial_id"]}), encoding="utf-8"
    )
    (run / "confirmation-comparison.json").write_text(
        json.dumps(
            {
                "status": "valid",
                "comparisons": [{"max_db_difference": 1e-11}],
            }
        ),
        encoding="utf-8",
    )

    result = BrainOperations(paths).compile_run(
        str(run), case_id="filter-move", title="Filter Move"
    )
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))

    assert result["run_status"] == "validated"
    assert manifest["reproducibility"] == "reproduced"
    assert manifest["metrics"]["lab_objectives"] == {"resonance": 4.187}
    assert manifest["working_project"].endswith("case_001/working.cst")
