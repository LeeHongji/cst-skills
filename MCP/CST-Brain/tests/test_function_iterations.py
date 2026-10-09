import json
from pathlib import Path

from cst_brain.function_iterations import publish_function_iteration
from cst_brain.index import BrainIndex
from cst_brain.paths import BrainPaths


def test_function_iteration_projection_is_idempotent_and_searchable(tmp_path: Path):
    workspace = tmp_path / "workspace"
    brain = workspace / "brain"
    history = workspace / "projects" / "topic" / "designs" / "coupon" / "attempts" / "a01" / "iterations.jsonl"
    history.parent.mkdir(parents=True)
    fact = {
        "schema_version": 1,
        "iter": 0,
        "ts": "2026-09-15T00:00:00+00:00",
        "parent": None,
        "param_delta": {"length_mm": [10.0, 10.5]},
        "setup_delta": {},
        "drc": "pass",
        "job_id": "job://" + "a" * 64 + "/" + "b" * 32,
        "request_sha256": "c" * 64,
        "status": "completed",
        "fidelity": "screen",
        "execution_kind": "solver",
        "duration_s": 1.2,
        "cache_hit": False,
        "provenance": "native",
        "audited": True,
        "acceptance": {"status": "pass", "gates": []},
        "metrics": {"s21_db": -0.2},
        "artifacts": {"manifest.json": "artifact://" + "d" * 64 + "/" + "e" * 32 + "/manifest.json"},
        "observation": "increase length and verify passband",
        "execution": {"schema_version": 1, "parameters": {"length_mm": 10.5}, "model_intent_id": "f" * 64, "topology_hash": "1" * 64, "setup": {}, "setup_sha256": "2" * 64, "setup_overrides": {}, "model_source_sha256": "3" * 64, "emitted_sha256": "4" * 64},
        "solver": {"converged": True},
        "evidence": {"kind": "simulation", "revision": "r-" + "e" * 32, "manifest_sha256": "5" * 64},
    }
    history.write_text(json.dumps(fact) + "\n", encoding="utf-8")
    fact_file = tmp_path / "fact.json"
    request_file = tmp_path / "request.json"
    fact_file.write_text(json.dumps(fact), encoding="utf-8")
    request_file.write_text(json.dumps({"topic": "topic", "design": "coupon", "attempt": "a01", "request_id": "test-iteration", "operation": "simulate", "why": "verify learning projection"}), encoding="utf-8")

    first = publish_function_iteration(history=history, fact_file=fact_file, request_file=request_file, job_ref=fact["job_id"], workspace_root=workspace, brain_root=brain)
    second = publish_function_iteration(history=history, fact_file=fact_file, request_file=request_file, job_ref=fact["job_id"], workspace_root=workspace, brain_root=brain)
    assert first["status"] == "published"
    assert second["status"] == "unchanged"
    result = BrainIndex(BrainPaths.resolve(brain)).search("passband length native screen", limit=5)
    assert any(item["path"] == Path(first["page"]).relative_to(brain).as_posix() for item in result["results"])
