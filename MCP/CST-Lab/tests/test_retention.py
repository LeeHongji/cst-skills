from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import pytest

from cst_lab import LabOperations, LabPaths, RetentionPolicy
from cst_lab.paths import long_path
from cst_lab.collector import (
    BLOCK_LOCK,
    BLOCK_NON_TERMINAL,
    BLOCK_NO_EVIDENCE,
    BLOCK_NO_OWNER,
    BLOCK_PROTECTED,
    unit_key,
)
from cst_lab.artifacts import artifact_id_for
from cst_lab.diagnostics import transition_path
from cst_lab.registry import ARTIFACTS_INDEXES_V2, SCHEMA_VERSION, LabRegistry
from cst_lab.retention import EVIDENCE, REGENERABLE, SCRATCH, UNCLASSIFIED

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 8, 8, 4, 0, tzinfo=timezone.utc)


def operations(tmp_path: Path, *, now: datetime = NOW) -> LabOperations:
    paths = LabPaths(
        workspace_root=tmp_path,
        registry_root=tmp_path / "cst_runs" / "_registry",
        database=tmp_path / "cst_runs" / "_registry" / "cst-lab.sqlite3",
        schemas_root=ROOT / "brain" / "schemas",
    )
    (tmp_path / "cst_runs").mkdir(parents=True, exist_ok=True)
    return LabOperations(paths, clock=lambda: now)


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


def spec(revision_id: str, title: str = "Filter frequency move") -> dict:
    return {
        "schema_version": 2,
        "title": title,
        "project_revision_id": revision_id,
        "hypothesis": "Scaling resonator lengths moves the passband predictably.",
        "parameters": [{"name": "scale", "kind": "continuous", "low": 0.8, "high": 1.2}],
        "objectives": [metric()],
        "constraints": [],
        "fidelity_plan": {"stages": [{"name": "coarse"}, {"name": "confirm"}]},
        "evaluation_budget": {"max_trials": 8, "max_solver_minutes": 120},
        "approval_policy": {"before_solver": True, "before_source_change": True},
        "stop_conditions": [{"kind": "target-reached"}],
        "tags": ["filter", "frequency-move"],
    }


def source_project(tmp_path: Path, stem: str = "Filter") -> Path:
    source = tmp_path / f"{stem}.cst"
    source.write_bytes(b"fake-cst-container")
    model = tmp_path / stem / "Model"
    model.mkdir(parents=True, exist_ok=True)
    (model / "Parameters.json").write_text(json.dumps({"f0": 10}), encoding="utf-8")
    (model / "simulationproperties.json").write_text(json.dumps({"s": 1}), encoding="utf-8")
    return source


def working_copy(
    trial_run_path: Path,
    stem: str,
    *,
    result_bytes: int = 4096,
    with_lock: bool = False,
    with_temp: bool = True,
) -> Path:
    """Build a realistic CST working copy: project, Model/, Result/, Temp/."""

    working = trial_run_path / "working"
    project = working / f"{stem}.cst"
    working.mkdir(parents=True, exist_ok=True)
    project.write_bytes(b"cst-container")
    companion = working / stem
    model = companion / "Model" / "3D"
    model.mkdir(parents=True)
    (model / "ModelHistory.json").write_text(json.dumps({"blocks": []}), encoding="utf-8")
    (companion / "Model" / "Parameters.json").write_text("{}", encoding="utf-8")
    result = companion / "Result"
    result.mkdir(parents=True)
    (result / "Model.rom").write_bytes(b"r" * result_bytes)
    (result / "Model.m3t").write_bytes(b"m" * result_bytes)
    (result / "output.txt").write_text("solver finished", encoding="utf-8")
    if with_temp:
        temp = companion / "Temp"
        temp.mkdir()
        (temp / "ThreadInfo.txt").write_text("threads", encoding="utf-8")
    if with_lock:
        (companion / "Model.lok").write_bytes(b"")
    return companion


def export_evidence(trial_run_path: Path, stem: str) -> None:
    exports = trial_run_path / "evidence"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / f"{stem}.s2p").write_text("! touchstone\n# GHZ S DB R 50\n", encoding="utf-8")
    (exports / "filter-response.csv").write_text("f,s11\n1,-20\n", encoding="utf-8")


# --------------------------------------------------------------------- policy


@pytest.mark.parametrize(
    "relative, expected",
    [
        ("run/trials/0000/working/m.cst", EVIDENCE),
        ("run/trials/0000/evidence/m.s2p", EVIDENCE),
        ("run/trials/0000/trial.json", EVIDENCE),
        ("run/trials/0000/working/m/Result/Model.rom", REGENERABLE),
        ("run/trials/0000/working/m/Result/Model.m3t", REGENERABLE),
        ("run/trials/0000/working/m/Temp/ThreadInfo.txt", SCRATCH),
        ("run/trials/0000/working/m/Model.lok", SCRATCH),
        ("run/scratch/notes.tmp", SCRATCH),
        ("run/trials/0000/working/m/Model/3D/Model.dib", UNCLASSIFIED),
        ("run/trials/0000/working/m/ModelCache/Model.cha", UNCLASSIFIED),
    ],
)
def test_policy_classifies_by_location_and_suffix(relative: str, expected: str) -> None:
    policy = RetentionPolicy.default()
    assert policy.classify(PurePosixPath(relative)).retention_class == expected


def test_regenerable_suffix_outside_result_is_retained() -> None:
    """A .dib preview inside Model/ is not a reclaimable solver cache."""

    policy = RetentionPolicy.default()
    inside = policy.classify(PurePosixPath("run/w/m/Result/Model.dib"))
    outside = policy.classify(PurePosixPath("run/w/m/Model/DS/Image/Model.dib"))
    assert inside.retention_class == REGENERABLE
    assert outside.retention_class == UNCLASSIFIED
    assert outside.deletable is False


def test_only_evidence_is_hashed_and_locks_are_never_deletable() -> None:
    policy = RetentionPolicy.default()
    assert policy.classify(PurePosixPath("r/a.s2p")).hash_required is True
    assert policy.classify(PurePosixPath("r/w/m/Result/a.rom")).hash_required is False
    huge = policy.classify(PurePosixPath("r/a.csv"), size_bytes=policy.hash_max_bytes + 1)
    assert huge.hash_required is False
    assert policy.classify(PurePosixPath("r/w/m/Model.lok")).deletable is False
    assert policy.classify(PurePosixPath("r/w/m.cst")).deletable is False


def test_reserved_run_directories_match_by_prefix() -> None:
    policy = RetentionPolicy.default()
    assert policy.is_reserved("cst-cad-phase1-verification_20260910") is True
    assert policy.is_reserved("fig15-filter-d-paper-target-tuning_20260830") is False


def test_unit_key_stops_at_the_working_copy() -> None:
    policy = RetentionPolicy.default()
    assert (
        unit_key("run/trials/0000/working/model/Result/deep/a.rom", policy)
        == "run/trials/0000/working/model"
    )
    assert unit_key("run/trials/0000/working/model/Temp/a.txt", policy) == "run/trials/0000/working/model"
    assert unit_key("run/trials/0000/working/model/Model.lok", policy) == "run/trials/0000/working/model"


# --------------------------------------------------------------------- indexer


def prepared_experiment(
    ops: LabOperations, *, title: str = "Filter frequency move", stem: str = "Filter"
) -> dict:
    project = ops.register_project(str(source_project(ops.paths.workspace_root, stem)))
    revision = ops.snapshot_model(project["project_id"])
    experiment = ops.create_experiment(spec(revision["revision_id"], title))
    ops.validate_experiment(experiment["experiment_id"])
    return experiment


def completed_trial(
    ops: LabOperations,
    experiment_id: str,
    stem: str,
    *,
    objective: float = -12.0,
    **kwargs,
) -> dict:
    """Complete a trial. The default objective misses the -20 dB target, so the
    trial is an ordinary screening result rather than a protected best candidate."""

    trial = ops.create_trial(experiment_id, {"scale": 0.95})
    working_copy(Path(trial["run_path"]), stem, **kwargs)
    ops.transition_trial(trial["trial_id"], "queued")
    ops.transition_trial(trial["trial_id"], "running")
    ops.transition_trial(trial["trial_id"], "validating")
    return ops.transition_trial(
        trial["trial_id"], "completed", objectives={"s11_min_db": objective}
    )


def test_index_records_classes_owners_and_is_idempotent(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a")
    export_evidence(Path(trial["run_path"]), "filter_a")

    first = ops.index_artifacts()
    classes = first["stats"]["by_retention_class"]
    assert classes[REGENERABLE]["files"] == 2
    assert classes[SCRATCH]["files"] == 1
    assert first["stats"]["written"] == first["stats"]["scanned_files"]
    assert first["stats"]["hashed_files"] == classes[EVIDENCE]["files"]

    connection = sqlite3.connect(ops.paths.database)
    connection.row_factory = sqlite3.Row
    try:
        rom = connection.execute(
            "SELECT * FROM artifacts WHERE run_path LIKE '%Result/Model.rom'"
        ).fetchone()
        touchstone = connection.execute(
            "SELECT * FROM artifacts WHERE run_path LIKE '%filter_a.s2p'"
        ).fetchone()
    finally:
        connection.close()

    assert rom["retention_class"] == REGENERABLE
    assert rom["sha256"] is None, "recomputable caches must not pay for a digest"
    assert rom["producing_tool"] == "cst-solver"
    assert rom["trial_id"] == trial["trial_id"]
    assert rom["experiment_id"] == experiment["experiment_id"]
    assert rom["owner_kind"] == "trial"
    assert touchstone["sha256"] is not None
    assert touchstone["artifact_type"] == "touchstone"

    second = ops.index_artifacts()
    assert second["stats"]["unchanged"] == second["stats"]["scanned_files"]
    assert second["stats"]["written"] == 0
    assert second["catalog"]["totals"]["files"] == first["catalog"]["totals"]["files"]


def test_index_catalogs_loose_files_at_the_runs_root(tmp_path: Path) -> None:
    """A file dropped straight into cst_runs/ must still get a catalog row."""

    ops = operations(tmp_path)
    loose = ops.paths.runs_root / "fig15-filter-d-paper-targets.json"
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_text('{"target_db": -20}', encoding="utf-8")

    ops.index_artifacts()
    record = ops.registry.get_artifact(artifact_id_for("fig15-filter-d-paper-targets.json"))
    assert record is not None, "loose root-level files must not be skipped by the walker"
    assert record["run_directory"] == "_loose_files"
    assert record["retention_class"] == EVIDENCE
    assert record["sha256"] is not None

    plan = ops.plan_retention()
    assert plan["totals"]["units_released"] == 0, "an evidence JSON is never reclaimable"
    assert loose.is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="MAX_PATH only applies on Windows")
def test_index_hashes_evidence_beyond_the_windows_path_limit(tmp_path: Path) -> None:
    """Evidence deeper than 260 characters must still be hashed, not pruned.

    Real CST export trees exceed MAX_PATH. Without extended-length paths the
    file looks missing, so the catalog would drop a row for evidence that is
    actually present on disk.
    """

    ops = operations(tmp_path)
    deep = ops.paths.runs_root / "deep-run_20260810_aaaaaaaaaaaa" / "exports"
    while len(str(deep)) < 250:
        deep = deep / "reference_balanced_final_ho14p24_hc14p84_t3p00_g0p34"
    target = deep / "response.s2p"
    long_path(deep).mkdir(parents=True, exist_ok=True)
    long_path(target).write_text("! touchstone\n", encoding="utf-8")
    assert len(str(target)) > 260
    # Windows hosts may enable long paths globally. The catalog must preserve
    # and hash this evidence in either configuration; invisibility through plain
    # pathlib is not a valid portable precondition.
    assert long_path(target).is_file()

    stats = ops.index_artifacts()["stats"]
    assert stats["hash_errors"] == 0, "long paths must not surface as hash errors"

    record = ops.registry.get_artifact(
        artifact_id_for(target.relative_to(ops.paths.runs_root).as_posix())
    )
    assert record is not None
    assert record["retention_class"] == EVIDENCE
    assert record["sha256"] is not None

    second = ops.index_artifacts()["stats"]
    assert second["removed_stale"] == 0, "a long-path file must never be pruned as missing"


def test_index_prunes_rows_for_deleted_files(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a")
    ops.index_artifacts()

    target = next(Path(trial["run_path"]).rglob("Model.m3t"))
    target.unlink()
    again = ops.index_artifacts()
    assert again["stats"]["removed_stale"] == 1

    connection = sqlite3.connect(ops.paths.database)
    try:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM artifacts WHERE run_path LIKE '%Model.m3t'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert remaining == 0


def test_index_skips_reserved_run_directories(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    reserved = tmp_path / "cst_runs" / "cst-cad-phase1-verification_20260910" / "working"
    reserved.mkdir(parents=True)
    (reserved / "other-agent.cst").write_bytes(b"not mine")

    result = ops.index_artifacts()
    connection = sqlite3.connect(ops.paths.database)
    try:
        rows = connection.execute(
            "SELECT COUNT(*) FROM artifacts WHERE run_directory LIKE 'cst-cad%'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert rows == 0
    assert result["stats"]["scanned_files"] == 0


# -------------------------------------------------------------------- gc gates


def test_terminal_trial_with_evidence_is_released(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a")
    export_evidence(Path(trial["run_path"]), "filter_a")
    ops.index_artifacts()

    plan = ops.plan_retention(write_reports=False)
    released = [item for item in plan["units"] if item["decision"] == "release"]
    assert len(released) == 1, json.dumps(
        [
            {
                "unit": item["unit_path"],
                "blocks": item["block_reasons"],
                "signals": item["protection_signals"],
                "owner": item["owner_kind"],
                "status": item["owner_status"],
                "evidence": item["evidence_artifact_count"],
            }
            for item in plan["units"]
        ],
        indent=2,
    )
    unit = released[0]
    assert unit["trial_id"] == trial["trial_id"]
    assert unit["release_reason"] == "terminal-owner-plus-exported-evidence"
    assert unit["evidence_artifact_count"] >= 2
    # Two Result/ caches plus the Temp/ scratch file.
    assert unit["reclaimable_files"] == 3
    assert plan["totals"]["releasable_bytes"] == unit["reclaimable_bytes"]
    assert unit["regeneration_inputs"]["required_input_count"] > 0


def test_non_terminal_trial_is_retained(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = ops.create_trial(experiment["experiment_id"], {"scale": 1.0})
    working_copy(Path(trial["run_path"]), "filter_a")
    export_evidence(Path(trial["run_path"]), "filter_a")
    ops.transition_trial(trial["trial_id"], "queued")
    ops.transition_trial(trial["trial_id"], "running")
    ops.index_artifacts()

    plan = ops.plan_retention(write_reports=False)
    assert plan["totals"]["units_released"] == 0
    assert BLOCK_NON_TERMINAL in plan["block_reason_counts"]


def test_missing_evidence_blocks_release(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    completed_trial(ops, experiment["experiment_id"], "filter_a")
    ops.index_artifacts()

    plan = ops.plan_retention(write_reports=False)
    assert plan["totals"]["units_released"] == 0
    assert BLOCK_NO_EVIDENCE in plan["block_reason_counts"]


def test_lock_file_blocks_release(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a", with_lock=True)
    export_evidence(Path(trial["run_path"]), "filter_a")
    ops.index_artifacts()

    plan = ops.plan_retention(write_reports=False)
    assert plan["totals"]["units_released"] == 0
    unit = plan["units"][0]
    assert BLOCK_LOCK in unit["block_reasons"]
    assert unit["lock_paths"]


def test_selected_candidate_is_force_retained(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_selected_refined")
    export_evidence(Path(trial["run_path"]), "filter_selected_refined")
    ops.index_artifacts()

    plan = ops.plan_retention(write_reports=False)
    unit = plan["units"][0]
    assert unit["decision"] == "retain"
    assert BLOCK_PROTECTED in unit["block_reasons"]
    assert any("model-basename-token:selected" in s for s in unit["protection_signals"])


def test_best_trial_meeting_target_is_force_retained(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a", objective=-23.4)
    export_evidence(Path(trial["run_path"]), "filter_a")
    ops.index_artifacts()

    plan = ops.plan_retention(write_reports=False)
    unit = plan["units"][0]
    assert unit["decision"] == "retain"
    assert BLOCK_PROTECTED in unit["block_reasons"]
    assert any("A:best-trial-meeting-target" in s for s in unit["protection_signals"])


def test_best_of_a_missed_screen_is_opt_in_protection(tmp_path: Path) -> None:
    """A screening run that never met its target is releasable unless asked otherwise."""

    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a", objective=-12.0)
    export_evidence(Path(trial["run_path"]), "filter_a")
    ops.index_artifacts()

    assert ops.plan_retention(write_reports=False)["totals"]["units_released"] == 1
    guarded = ops.plan_retention(write_reports=False, protect_best_per_experiment=True)
    assert guarded["totals"]["units_released"] == 0
    assert any(
        "B:best-trial-below-target" in signal
        for signal in guarded["units"][0]["protection_signals"]
    )


def test_working_copy_without_lab_owner_is_retained(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    stray = tmp_path / "cst_runs" / "manual-exploration_20260808" / "trials" / "0000"
    stray.mkdir(parents=True)
    working_copy(stray, "manual_model")
    export_evidence(stray, "manual_model")
    ops.index_artifacts()

    plan = ops.plan_retention(write_reports=False)
    assert plan["totals"]["units_released"] == 0
    assert BLOCK_NO_OWNER in plan["block_reason_counts"]


def test_max_bytes_defers_units_beyond_the_budget(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    for index, stem in enumerate(("filter_a", "filter_b")):
        trial = completed_trial(
            ops, experiment["experiment_id"], stem, result_bytes=4096 * (index + 1)
        )
        export_evidence(Path(trial["run_path"]), stem)
    ops.index_artifacts()

    full = ops.plan_retention(write_reports=False)
    assert full["totals"]["units_released"] == 2

    limited = ops.plan_retention(write_reports=False, max_bytes=9000)
    assert limited["totals"]["units_released"] == 1
    assert limited["totals"]["units_deferred"] == 1
    assert limited["totals"]["releasable_bytes"] <= 9000


def test_project_family_filter_uses_legacy_inventory(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a")
    export_evidence(Path(trial["run_path"]), "filter_a")
    ops.index_artifacts()
    inventory = ops.legacy_inventory()
    family = inventory["run_directories"][0]["project_family"]

    matched = ops.plan_retention(write_reports=False, families=[family])
    assert matched["totals"]["units_considered"] == 1
    assert matched["units"][0]["project_family"] == family
    missed = ops.plan_retention(write_reports=False, families=["oam-uca-3p5ghz"])
    assert missed["totals"]["units_considered"] == 0


# ------------------------------------------------------------------ gc execute


def test_execute_requires_confirmation(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a")
    export_evidence(Path(trial["run_path"]), "filter_a")
    ops.index_artifacts()

    with pytest.raises(ValueError, match="confirm"):
        ops.execute_retention(confirm=False)
    assert next(Path(trial["run_path"]).rglob("Model.rom"), None) is not None


def test_execute_writes_manifest_then_removes_only_reclaimable(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a")
    export_evidence(Path(trial["run_path"]), "filter_a")
    ops.index_artifacts()

    result = ops.execute_retention(confirm=True)
    assert result["status"] == "executed"
    assert result["removed_files"] == 3
    assert result["removed_bytes"] > 0

    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["units"][0]["release_reason"]
    assert manifest["units"][0]["regeneration_inputs"]["required_input_count"] > 0
    assert {item["run_path"] for item in manifest["units"][0]["removed"]}
    assert manifest["result"]["removed_files"] == 3

    working = Path(trial["run_path"]) / "working"
    assert (working / "filter_a.cst").is_file(), "the .cst source must survive"
    assert (Path(trial["run_path"]) / "evidence" / "filter_a.s2p").is_file()
    assert next(working.rglob("Model.rom"), None) is None
    assert next(working.rglob("ThreadInfo.txt"), None) is None
    assert (working / "filter_a" / "Model" / "3D" / "ModelHistory.json").is_file()

    connection = sqlite3.connect(ops.paths.database)
    try:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM artifacts WHERE retention_class = ?", (REGENERABLE,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert remaining == 0


def test_execute_skips_a_unit_locked_after_planning(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a")
    export_evidence(Path(trial["run_path"]), "filter_a")
    ops.index_artifacts()

    plan = ops.collector.plan()
    companion = Path(trial["run_path"]) / "working" / "filter_a"
    (companion / "Model.lok").write_bytes(b"")

    result = ops.collector.execute(plan, confirm=True)
    assert result["removed_files"] == 0
    assert result["skipped_count"] == 1
    assert next(companion.rglob("Model.rom"), None) is not None


# ------------------------------------------------------------------- inventory


def test_legacy_inventory_clusters_families_and_flags_reregistration(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops, title="Fig15 filter D coupling screen")
    trial = completed_trial(ops, experiment["experiment_id"], "fig15_filter_d_trial")
    export_evidence(Path(trial["run_path"]), "fig15_filter_d_trial")
    ops.index_artifacts()

    document = ops.legacy_inventory()
    assert Path(document["inventory_path"]).is_file()
    entry = next(
        item
        for item in document["run_directories"]
        if item["run_directory"].startswith("fig15-filter-d")
    )
    assert entry["project_family"] == "fig15-filter-d-dual-mode-microstrip"
    assert entry["lab_registered"] is True
    assert entry["run_uri"].startswith("run://")
    assert entry["experiment_ids"] == [experiment["experiment_id"]]
    assert entry["bytes"]["regenerable"] > 0

    # Registering a trial product as a new project must be reported as such.
    product = Path(trial["run_path"]) / "working" / "fig15_filter_d_trial.cst"
    reregistered = ops.register_project(str(product))
    document = ops.legacy_inventory()
    match = next(
        item
        for item in document["reregistered_trial_products"]
        if item["project_id"] == reregistered["project_id"]
    )
    assert match["produced_by"]["trial_id"] == trial["trial_id"]
    assert match["classification"] == "trial-product-reregistered-as-project"
    assert match["inferred_project_family"] == "fig15-filter-d-dual-mode-microstrip"


# ----------------------------------------------------------------- diagnostics


def test_triage_recommends_cancel_when_target_was_never_met(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a", objective=-23.4)
    export_evidence(Path(trial["run_path"]), "filter_a")
    ops.transition_experiment(experiment["experiment_id"], "queued")
    ops.transition_experiment(experiment["experiment_id"], "running")
    ops.transition_experiment(experiment["experiment_id"], "paused")
    ops.index_artifacts()

    report = ops.triage_experiments()
    row = report["experiments"][0]
    assert row["current_status"] == "paused"
    # objective -23.4 dB is better than the -20 dB target, so the run finished.
    assert row["recommended_status"] == "completed"
    assert row["objective_target_met"] is True
    assert row["transition_path"] == ["queued", "running", "validating", "completed"]
    assert row["evidence_file_count"] >= 2

    # A screening run that never reached the target should be cancelled instead.
    second = prepared_experiment(ops, title="Screen that missed target", stem="Screen")
    weak = completed_trial(ops, second["experiment_id"], "screen_a", objective=-8.0)
    export_evidence(Path(weak["run_path"]), "screen_a")
    ops.transition_experiment(second["experiment_id"], "queued")
    ops.transition_experiment(second["experiment_id"], "paused")
    ops.index_artifacts()

    report = ops.triage_experiments()
    row = next(
        item for item in report["experiments"] if item["experiment_id"] == second["experiment_id"]
    )
    assert row["recommended_status"] == "cancelled"
    assert row["objective_target_met"] is False
    assert "never reached the target" in row["reason"]


def test_triage_defers_when_trials_are_unsettled(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = ops.create_trial(experiment["experiment_id"], {"scale": 1.0})
    ops.transition_trial(trial["trial_id"], "queued")
    ops.transition_experiment(experiment["experiment_id"], "queued")
    ops.transition_experiment(experiment["experiment_id"], "paused")
    ops.index_artifacts()

    row = ops.triage_experiments()["experiments"][0]
    assert row["recommended_status"] == "needs-human-review"
    assert row["transition_path"] is None


def test_transition_path_is_multi_hop_from_paused() -> None:
    assert transition_path("paused", "cancelled") == ["cancelled"]
    assert transition_path("paused", "completed") == [
        "queued",
        "running",
        "validating",
        "completed",
    ]
    assert transition_path("completed", "queued") is None


def test_lock_inventory_reports_without_deleting(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a", with_lock=True)
    ops.index_artifacts()

    report = ops.lock_inventory()
    assert report["lock_file_count"] == 1
    assert report["probe_enabled"] is True
    entry = report["locks"][0]
    assert entry["trial_id"] == trial["trial_id"]
    assert entry["companion_directory"].endswith("filter_a")
    # Nothing holds this lock, so the read-share probe must succeed.
    assert entry["held_by_process"] is False
    assert entry["staleness"] == "recent-review-manually"
    lock = Path(trial["run_path"]) / "working" / "filter_a" / "Model.lok"
    assert lock.is_file(), "lock inventory must never delete a .lok file"

    aged = ops.diagnostics.lock_inventory(stale_after_hours=0)
    assert aged["orphan_candidate_count"] == 1
    assert aged["live_count"] == 0
    assert lock.is_file()


def test_workspace_governance_detects_tmp_duplicates(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    experiment = prepared_experiment(ops)
    trial = completed_trial(ops, experiment["experiment_id"], "filter_a")
    ops.index_artifacts()

    payload = (Path(trial["run_path"]) / "trial.json").read_bytes()
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    (scratch / "copy_of_trial.json").write_bytes(payload)
    (scratch / "unique.json").write_text('{"unique": true}', encoding="utf-8")

    report = ops.workspace_governance()
    entries = {item["name"]: item for item in report["tmp"]["entries"]}
    assert entries["copy_of_trial.json"]["disposition"] == "safe-to-delete-duplicate"
    assert entries["copy_of_trial.json"]["duplicate_of_run_artifact"].startswith("run://")
    assert entries["unique.json"]["disposition"] == "needs-placement-decision"


# --------------------------------------------------------------------- locking


def test_purge_expired_locks_removes_only_elapsed_ttls(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    project = ops.register_project(str(source_project(tmp_path)))
    ops.acquire_project_lock(project["project_id"], "agent-a", ttl_minutes=30)
    assert ops.purge_expired_locks()["purged_count"] == 0

    later = operations(tmp_path, now=NOW + timedelta(hours=2))
    purged = later.purge_expired_locks()
    assert purged["purged_count"] == 1
    assert purged["purged"][0]["owner"] == "agent-a"
    assert purged["remaining"] == []
    events = later.registry.events("project-lock", project["project_id"])
    assert events[-1]["to_status"] == "expired-purged"


def test_acquire_lock_purges_an_elapsed_holder_and_records_it(tmp_path: Path) -> None:
    ops = operations(tmp_path)
    project = ops.register_project(str(source_project(tmp_path)))
    ops.acquire_project_lock(project["project_id"], "agent-a", ttl_minutes=30)

    later = operations(tmp_path, now=NOW + timedelta(hours=2))
    lock = later.acquire_project_lock(project["project_id"], "agent-b", ttl_minutes=30)
    assert lock["owner"] == "agent-b"
    events = later.registry.events("project-lock", project["project_id"])
    assert events[0]["payload"]["trigger"] == "acquire"


# ------------------------------------------------------------------- migration


V1_ARTIFACTS = """
CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    experiment_id TEXT,
    trial_id TEXT,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


def test_migration_upgrades_a_version_one_database(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(V1_ARTIFACTS)
    connection.execute(
        "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("artifact-legacy", None, None, "cst", "C:/old/a.cst", "abc123", 42, "2026-01-01T00:00:00Z"),
    )
    connection.commit()
    connection.close()

    registry = LabRegistry(database, clock=lambda: NOW)
    state = registry.schema_state()
    assert state["user_version"] == SCHEMA_VERSION
    assert state["migrations"][0]["name"] == "artifact-catalog-retention-classes"
    assert "run_path" in state["artifact_columns"]
    assert "retention_class" in state["artifact_columns"]

    migrated = registry.get_artifact("artifact-legacy")
    assert migrated["run_path"] == "C:/old/a.cst"
    assert migrated["sha256"] == "abc123"
    assert migrated["size_bytes"] == 42
    assert migrated["owner_kind"] == "legacy"
    assert migrated["retention_class"] == UNCLASSIFIED

    # Re-opening must be a no-op rather than a second rebuild.
    again = LabRegistry(database, clock=lambda: NOW)
    assert len(again.schema_state()["migrations"]) == 1
    assert again.get_artifact("artifact-legacy")["run_path"] == "C:/old/a.cst"


def test_fresh_database_reports_nullable_sha256(tmp_path: Path) -> None:
    registry = LabRegistry(tmp_path / "fresh.sqlite3", clock=lambda: NOW)
    connection = registry.connect()
    try:
        columns = {row[1]: row for row in connection.execute("PRAGMA table_info(artifacts)")}
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(artifacts)")}
    finally:
        connection.close()
    assert columns["sha256"][3] == 0, "sha256 must be nullable for unhashed caches"
    assert columns["size_bytes"][3] == 1
    for name in ("idx_artifacts_run_directory", "idx_artifacts_retention"):
        assert name in indexes
    assert ARTIFACTS_INDEXES_V2.strip()
