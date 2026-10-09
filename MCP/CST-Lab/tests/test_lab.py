from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cst_lab import LabOperations, LabPaths


ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 8, 8, 4, 0, tzinfo=timezone.utc)


def operations(tmp_path: Path) -> LabOperations:
    paths = LabPaths(
        workspace_root=tmp_path,
        registry_root=tmp_path / "cst_runs" / "_registry",
        database=tmp_path / "cst_runs" / "_registry" / "cst-lab.sqlite3",
        schemas_root=ROOT / "brain" / "schemas",
    )
    return LabOperations(paths, clock=lambda: NOW)


def source_project(tmp_path: Path) -> Path:
    source = tmp_path / "Filter.cst"
    source.write_bytes(b"fake-cst-container")
    companion = tmp_path / "Filter"
    model = companion / "Model"
    model.mkdir(parents=True)
    (model / "Parameters.json").write_text(
        json.dumps({"f0": {"value": 10, "unit": "GHz"}}), encoding="utf-8"
    )
    (model / "simulationproperties.json").write_text(
        json.dumps({"solver": "frequency-domain"}), encoding="utf-8"
    )
    (model / "schematic.xml").write_text("<model />", encoding="utf-8")
    temp = companion / "Temp"
    temp.mkdir()
    (temp / "unstable.bin").write_bytes(b"ignored")
    (companion / "Model.lok").write_bytes(b"ignored lock")
    return source


def metric(name: str = "s11_min_db") -> dict:
    return {
        "name": name,
        "signal": "S1,1",
        "representation": "db20",
        "unit": "dB",
        "domain": "frequency",
        "frequency_window": {"start": 9.5, "stop": 10.5, "unit": "GHz"},
        "aggregation": "min",
        "direction": "minimize",
        "target": -20,
        "missing_data_policy": "invalid",
        "quality_gates": ["frequency-window-covered", "finite-complex-data"],
    }


def spec(revision_id: str) -> dict:
    return {
        "schema_version": 2,
        "title": "Filter frequency move",
        "project_revision_id": revision_id,
        "hypothesis": "Scaling resonator lengths moves the passband predictably.",
        "parameters": [
            {"name": "scale", "kind": "continuous", "low": 0.8, "high": 1.2}
        ],
        "objectives": [metric()],
        "constraints": [],
        "fidelity_plan": {"stages": [{"name": "coarse"}, {"name": "confirm"}]},
        "evaluation_budget": {"max_trials": 8, "max_solver_minutes": 120},
        "approval_policy": {"before_solver": True, "before_source_change": True},
        "stop_conditions": [{"kind": "target-reached"}],
        "tags": ["filter", "frequency-move"],
    }


def test_project_revision_and_portable_manifests(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    source = source_project(tmp_path)

    project = ops.register_project(str(source))
    assert project["project_id"].startswith("project-")
    assert project["manifest"]["companion"]["file_count"] == 3
    assert project["manifest"]["companion"]["skipped"][0]["reason"] == "volatile-or-lock-file"
    assert Path(project["portable_manifest"]).is_file()

    revision = ops.snapshot_model(project["project_id"])
    snapshot = revision["snapshot"]["snapshot"]
    assert snapshot["parameters"]["f0"]["value"] == 10
    assert snapshot["simulation_properties"]["solver"] == "frequency-domain"
    assert snapshot["history"]["live_export_required"] is True
    assert Path(revision["portable_manifest"]).is_file()


def test_source_drift_requires_reregistration(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    source = source_project(tmp_path)
    project = ops.register_project(str(source))
    source.write_bytes(b"changed")

    with pytest.raises(ValueError, match="changed after registration"):
        ops.snapshot_model(project["project_id"])


def test_experiment_trial_lifecycle_and_compare(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    project = ops.register_project(str(source_project(tmp_path)))
    revision = ops.snapshot_model(project["project_id"])
    experiment = ops.create_experiment(spec(revision["revision_id"]))
    experiment_id = experiment["experiment_id"]

    validated = ops.validate_experiment(experiment_id)
    assert validated["experiment"]["status"] == "prepared"
    assert validated["validation"]["status"] == "valid"
    assert ops.transition_experiment(experiment_id, "queued")["status"] == "queued"
    assert ops.transition_experiment(experiment_id, "running")["status"] == "running"

    trial = ops.create_trial(experiment_id, {"scale": 0.95})
    ops.transition_trial(trial["trial_id"], "queued")
    ops.transition_trial(trial["trial_id"], "running")
    ops.transition_trial(trial["trial_id"], "validating")
    completed = ops.transition_trial(
        trial["trial_id"],
        "completed",
        objectives={"s11_min_db": -23.4},
        constraints={},
    )
    assert completed["objectives"]["s11_min_db"] == -23.4

    comparison = ops.compare_trials(experiment_id)
    assert comparison["completed_trial_count"] == 1
    assert comparison["trials"][0]["parameters"] == {"scale": 0.95}
    assert Path(ops.compile_case_handoff(experiment_id)["path"]).is_file()


def test_invalid_state_and_invalid_numeric_completion_are_rejected(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    project = ops.register_project(str(source_project(tmp_path)))
    revision = ops.snapshot_model(project["project_id"])
    experiment = ops.create_experiment(spec(revision["revision_id"]))

    with pytest.raises(ValueError, match="Invalid experiment transition"):
        ops.transition_experiment(experiment["experiment_id"], "completed")

    ops.validate_experiment(experiment["experiment_id"])
    trial = ops.create_trial(experiment["experiment_id"], {"scale": 1.0})
    ops.transition_trial(trial["trial_id"], "queued")
    ops.transition_trial(trial["trial_id"], "running")
    ops.transition_trial(trial["trial_id"], "validating")
    with pytest.raises(ValueError, match="require objective"):
        ops.transition_trial(trial["trial_id"], "completed")


def test_project_lock_is_single_writer_and_owner_scoped(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    project = ops.register_project(str(source_project(tmp_path)))
    project_id = project["project_id"]

    lock = ops.acquire_project_lock(project_id, "agent-a", ttl_minutes=30)
    assert lock["owner"] == "agent-a"
    with pytest.raises(ValueError, match="locked by agent-a"):
        ops.acquire_project_lock(project_id, "agent-b", ttl_minutes=30)
    assert ops.release_project_lock(project_id, "agent-b")["released"] is False
    assert ops.release_project_lock(project_id, "agent-a")["released"] is True


def test_experiment_schema_rejects_ambiguous_metric(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    project = ops.register_project(str(source_project(tmp_path)))
    revision = ops.snapshot_model(project["project_id"])
    invalid = spec(revision["revision_id"])
    del invalid["objectives"][0]["representation"]

    with pytest.raises(ValueError, match="representation"):
        ops.create_experiment(invalid)


def test_unconfigured_paths_resolve_repository_root(monkeypatch) -> None:
    monkeypatch.delenv('CST_AUTOMATION_ROOT', raising=False)
    # Isolate the legacy default from an operator's ignored local deployment file.
    monkeypatch.setattr('cst_lab.paths.default_workspace', lambda platform: platform)
    paths = LabPaths.resolve()
    assert paths.workspace_root == ROOT
    assert paths.schemas_root == ROOT / "brain" / "schemas"
