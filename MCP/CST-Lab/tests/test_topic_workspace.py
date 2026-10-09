from __future__ import annotations

import json
from pathlib import Path

import pytest

from cst_lab.topic_workspace import init_design, init_topic, validate_topic_workspace


def gate() -> dict:
    return {
        "id": "return_loss",
        "metric": "s1_1_db",
        "band_ghz": [1.0, 2.0],
        "comparator": "<",
        "threshold": -10.0,
        "mode": "pointwise",
        "min_samples": 5,
        "note": "Owner-defined initial acceptance contract.",
    }


def topic(root: Path) -> Path:
    return init_topic(
        root,
        topic_id="example-filter",
        title="Example Filter",
        shared_physics=["coupled-resonator synthesis"],
        sources=[{"kind": "internal", "citation": "Owner design brief"}],
    )


def test_init_topic_creates_the_uniform_agent_workspace(tmp_path: Path) -> None:
    target = topic(tmp_path)
    assert {path.name for path in target.iterdir()} == {
        "AGENTS.md",
        "OPERATIONS.md",
        "README.md",
        "designs",
        "notes.md",
        "topic.md",
    }
    report = validate_topic_workspace(target)
    assert report["status"] == "valid"
    assert report["designs"] == 0


def test_init_topic_refuses_bad_ids_and_overwrite(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="kebab-case"):
        init_topic(
            tmp_path,
            topic_id="Bad_ID",
            title="Bad",
            shared_physics=["x"],
            sources=[{"kind": "internal", "citation": "x"}],
        )
    topic(tmp_path)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        topic(tmp_path)


def test_init_design_creates_valid_contract_model_and_attempt_area(tmp_path: Path) -> None:
    topic_dir = topic(tmp_path)
    design = init_design(
        topic_dir,
        design_id="first-device",
        title="First Device",
        ports=2,
        acceptance=[gate()],
    )
    assert (design / "design.md").is_file()
    assert (design / "model.py").is_file()
    assert (design / "attempts" / "README.md").is_file()
    report = validate_topic_workspace(topic_dir)
    assert report["status"] == "valid"
    assert report["designs"] == 1


def test_init_design_requires_a_machine_readable_gate(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="acceptance gate"):
        init_design(
            topic(tmp_path),
            design_id="first-device",
            title="First Device",
            ports=2,
            acceptance=[],
        )


def test_validator_reports_missing_operational_files(tmp_path: Path) -> None:
    topic_dir = topic(tmp_path)
    (topic_dir / "AGENTS.md").unlink()
    report = validate_topic_workspace(topic_dir)
    assert report["status"] == "invalid"
    assert "missing required topic file: AGENTS.md" in report["problems"]


def test_validator_checks_promoted_manifest_hashes(tmp_path: Path) -> None:
    topic_dir = topic(tmp_path)
    design = init_design(
        topic_dir,
        design_id="first-device",
        title="First Device",
        ports=2,
        acceptance=[gate()],
    )
    attempt = design / "attempts" / "a01-baseline"
    evidence = attempt / "evidence"
    (evidence / "selected" / "Model").mkdir(parents=True)
    (evidence / "selected.cst").write_bytes(b"project")
    (evidence / "response.s2p").write_text(
        "# GHz S RI R 50\n1 1 0 0 0 0 0 1 0\n", encoding="utf-8"
    )
    (attempt / "iterations.jsonl").write_text("", encoding="utf-8")
    (attempt / "attempt.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "attempt_id": "a01-baseline",
                "design_id": "first-device",
                "topic_id": "example-filter",
                "topology_hash": "a" * 64,
                "baseline_parameters": {},
                "approved_ranges": {},
                "max_iterations": 3,
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "topic_id": "example-filter",
        "design_id": "first-device",
        "attempt_id": "a01-baseline",
        "files": [
            {
                "path": "selected.cst",
                "bytes": len(b"project"),
                "sha256": "0" * 64,
            }
        ],
    }
    (evidence / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = validate_topic_workspace(topic_dir)
    assert report["status"] == "invalid"
    assert any("SHA-256 changed" in problem for problem in report["problems"])


def test_function_revision_counts_as_promoted_evidence_and_still_checks_hashes(tmp_path):
    from cst_lab.function_evidence import prepare_analysis
    from cst_lab.contracts.iterations import iteration_line
    directory=topic(tmp_path)
    design=init_design(directory,design_id='first-device',title='First',ports=2,acceptance=[gate()])
    attempt=design/'attempts/a01'
    revision=attempt/'evidence-revisions'/('r-'+'b'*32)
    revision.mkdir(parents=True)
    (revision/'metrics.json').write_text('{}')
    job='job://'+'a'*64+'/'+'b'*32
    checksum=prepare_analysis(revision,job)
    (attempt/'attempt.json').write_text(json.dumps(dict(schema_version=1,topic_id='example-filter',
        design_id='first-device',attempt_id='a01',topology_hash='c'*64,
        baseline_parameters={},approved_ranges={},max_iterations=2)))
    fact=iteration_line(iter_number=0,job_id=job,request_sha256='d'*64,status='completed',fidelity='offline',
        provenance='native',audited=False,execution_kind='offline',cache_hit=False,duration_s=0.1,
        acceptance=dict(status='pass',gates=[]),
        evidence=dict(kind='offline-analysis',revision=revision.name,manifest_sha256=checksum))
    (attempt/'iterations.jsonl').write_text(json.dumps(fact)+'\n')
    report=validate_topic_workspace(directory)
    assert report['problems']==[]
    assert report['status']=='valid'
    assert report['evidence_packages']==1 and report['warnings']==[]
    (revision/'metrics.json').write_text('{"tampered":true}')
    broken=validate_topic_workspace(directory)
    assert broken['status']=='invalid' and broken['evidence_packages']==0
