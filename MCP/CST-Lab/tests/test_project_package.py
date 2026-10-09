from __future__ import annotations

import json
from pathlib import Path

import pytest

from cst_lab.project_package import (
    PromotionArtifact,
    promote_project_package,
    validate_package,
)


def source_fixture(root: Path) -> tuple[Path, Path]:
    run = root / "cst_runs" / "topics" / "t" / "d" / "a" / "i000"
    project = run / "working" / "model.cst"
    project.parent.mkdir(parents=True)
    project.write_bytes(b"CST project")
    companion = project.with_suffix("")
    (companion / "Model" / "3D").mkdir(parents=True)
    (companion / "Model" / "3D" / "Model.dsn").write_bytes(b"model definition")
    (companion / "ModelCache").mkdir()
    (companion / "ModelCache" / "mesh.tet").write_bytes(b"cache")
    (companion / "Result").mkdir()
    (companion / "Result" / "solution.rom").write_bytes(b"large result")
    (companion / "Temp").mkdir()
    (companion / "Temp" / "scratch.tmp").write_bytes(b"scratch")
    curve = run / "exports" / "response.s2p"
    curve.parent.mkdir()
    curve.write_text("# GHz S RI R 50\n1 1 0 0 0 0 0 1 0\n", encoding="utf-8")
    return project, curve


def promote(root: Path, *, artifacts: list[PromotionArtifact] | None = None) -> Path:
    project, curve = source_fixture(root)
    target = root / "projects" / "t" / "designs" / "d" / "attempts" / "a" / "evidence"
    promote_project_package(
        workspace_root=root,
        source_project=project,
        evidence_dir=target,
        artifacts=artifacts or [PromotionArtifact("primary_touchstone", curve)],
        origin_run_uri="run://topics/t/d/a/i000",
        topic_id="t",
        design_id="d",
        attempt_id="a",
        source_commit="abc123",
    )
    return target


def test_promotes_only_reopenable_model_and_selected_evidence(tmp_path: Path) -> None:
    target = promote(tmp_path)
    assert (target / "selected.cst").read_bytes() == b"CST project"
    assert (target / "selected" / "Model" / "3D" / "Model.dsn").is_file()
    assert not (target / "selected" / "ModelCache").exists()
    assert not (target / "selected" / "Result").exists()
    assert not (target / "selected" / "Temp").exists()
    assert (target / "artifacts" / "primary_touchstone" / "response.s2p").is_file()
    assert validate_package(target) == []


def test_manifest_records_origin_hashes_and_pending_live_verification(tmp_path: Path) -> None:
    target = promote(tmp_path)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["origin_run_uri"] == "run://topics/t/d/a/i000"
    assert manifest["source_commit"] == "abc123"
    assert manifest["verification"] == {
        "static_package": "pass",
        "cst_reopen": "pending",
        "ir_comparison": "pending",
    }
    indexed = {item["path"]: item for item in manifest["files"]}
    assert indexed["selected.cst"]["sha256"]
    assert indexed["selected/Model/3D/Model.dsn"]["sha256"]
    assert all("Result/" not in path for path in indexed)


def test_refuses_to_overwrite_a_promoted_package(tmp_path: Path) -> None:
    target = promote(tmp_path)
    project = tmp_path / "cst_runs" / "topics" / "t" / "d" / "a" / "i000" / "working" / "model.cst"
    curve = tmp_path / "cst_runs" / "topics" / "t" / "d" / "a" / "i000" / "exports" / "response.s2p"
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        promote_project_package(
            workspace_root=tmp_path,
            source_project=project,
            evidence_dir=target,
            artifacts=[PromotionArtifact("primary_touchstone", curve)],
            origin_run_uri="run://x",
            topic_id="t",
            design_id="d",
            attempt_id="a",
        )


def test_refuses_a_locked_source_without_deleting_the_lock(tmp_path: Path) -> None:
    project, curve = source_fixture(tmp_path)
    lock = project.with_suffix("") / "Model.lok"
    lock.write_bytes(b"held")
    with pytest.raises(RuntimeError, match="Locks are never deleted"):
        promote_project_package(
            workspace_root=tmp_path,
            source_project=project,
            evidence_dir=tmp_path / "projects" / "t" / "evidence",
            artifacts=[PromotionArtifact("primary_touchstone", curve)],
            origin_run_uri="run://x",
            topic_id="t",
            design_id="d",
            attempt_id="a",
        )
    assert lock.is_file()


def test_refuses_source_or_destination_outside_their_planes(tmp_path: Path) -> None:
    project, curve = source_fixture(tmp_path)
    outside = tmp_path / "outside.cst"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError, match="source project must be inside"):
        promote_project_package(
            workspace_root=tmp_path,
            source_project=outside,
            evidence_dir=tmp_path / "projects" / "t" / "evidence",
            artifacts=[PromotionArtifact("primary_touchstone", curve)],
            origin_run_uri="run://x",
            topic_id="t",
            design_id="d",
            attempt_id="a",
        )
    with pytest.raises(ValueError, match="evidence directory must be inside"):
        promote_project_package(
            workspace_root=tmp_path,
            source_project=project,
            evidence_dir=tmp_path / "elsewhere",
            artifacts=[PromotionArtifact("primary_touchstone", curve)],
            origin_run_uri="run://x",
            topic_id="t",
            design_id="d",
            attempt_id="a",
        )


def test_requires_typed_curve_evidence(tmp_path: Path) -> None:
    project, _curve = source_fixture(tmp_path)
    metric = project.parents[1] / "metrics.json"
    metric.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="requires Touchstone or CSV"):
        promote_project_package(
            workspace_root=tmp_path,
            source_project=project,
            evidence_dir=tmp_path / "projects" / "t" / "evidence",
            artifacts=[PromotionArtifact("metrics", metric)],
            origin_run_uri="run://x",
            topic_id="t",
            design_id="d",
            attempt_id="a",
        )
