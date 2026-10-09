#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from cst_lab import LabOperations


INSTRUCTIONS = """Use CST Lab as the local experiment registry and lifecycle plane.
Register and snapshot source projects read-only. Never write a user's source .cst.
Create experiments before solver work, use project locks for write operations, and
record invalid/failed/partial outcomes without inventing numeric objective values."""

mcp = FastMCP("cst-lab-mcp", instructions=INSTRUCTIONS)
operations = LabOperations()


@mcp.tool()
def lab_register_project_tool(source_path: str) -> dict[str, Any]:
    """Register a CST source project by path and content evidence without modifying it."""
    return operations.register_project(source_path)


@mcp.tool()
def lab_snapshot_model_tool(project_id: str) -> dict[str, Any]:
    """Create an immutable offline model revision from registered project evidence."""
    return operations.snapshot_model(project_id)


@mcp.tool()
def lab_create_experiment_tool(spec: dict[str, Any]) -> dict[str, Any]:
    """Create a schema-validated CST experiment in planned state."""
    return operations.create_experiment(spec)


@mcp.tool()
def lab_validate_experiment_tool(experiment_id: str) -> dict[str, Any]:
    """Validate an experiment and move it from planned to prepared."""
    return operations.validate_experiment(experiment_id)


@mcp.tool()
def lab_queue_experiment_tool(experiment_id: str) -> dict[str, Any]:
    """Queue a prepared or resumed experiment for execution."""
    return operations.transition_experiment(experiment_id, "queued")


@mcp.tool()
def lab_get_experiment_status_tool(experiment_id: str) -> dict[str, Any]:
    """Return experiment state, trials, and auditable lifecycle events."""
    return {
        "experiment": operations.registry.get_experiment(experiment_id),
        "trials": operations.list_trials(experiment_id),
        "events": operations.registry.events("experiment", experiment_id),
    }


@mcp.tool()
def lab_pause_experiment_tool(experiment_id: str, reason: str | None = None) -> dict[str, Any]:
    """Pause a queued or running experiment without discarding its state."""
    return operations.transition_experiment(experiment_id, "paused", reason)


@mcp.tool()
def lab_resume_experiment_tool(experiment_id: str, reason: str | None = None) -> dict[str, Any]:
    """Resume a paused, failed, invalid, partial, or blocked experiment by re-queueing it."""
    return operations.transition_experiment(experiment_id, "queued", reason)


@mcp.tool()
def lab_cancel_experiment_tool(experiment_id: str, reason: str) -> dict[str, Any]:
    """Cancel a non-terminal experiment while preserving all evidence."""
    return operations.transition_experiment(experiment_id, "cancelled", reason)


@mcp.tool()
def lab_create_trial_tool(experiment_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Create the next numbered trial with an immutable parameter proposal."""
    return operations.create_trial(experiment_id, parameters)


@mcp.tool()
def lab_update_trial_tool(
    trial_id: str,
    status: str,
    objectives: dict[str, Any] | None = None,
    constraints: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance a trial state and attach validated metrics, constraints, or structured errors."""
    return operations.transition_trial(
        trial_id, status, objectives=objectives, constraints=constraints, error=error
    )


@mcp.tool()
def lab_list_trials_tool(experiment_id: str) -> list[dict[str, Any]]:
    """List all trials for an experiment in deterministic sequence order."""
    return operations.list_trials(experiment_id)


@mcp.tool()
def lab_compare_trials_tool(
    experiment_id: str, trial_ids: list[str] | None = None
) -> dict[str, Any]:
    """Build a parameter/objective comparison table from completed trials only."""
    return operations.compare_trials(experiment_id, trial_ids)


@mcp.tool()
def lab_compile_case_tool(experiment_id: str) -> dict[str, Any]:
    """Create a portable handoff for cst-trace-compile after solver evidence validation."""
    return operations.compile_case_handoff(experiment_id)


@mcp.tool()
def lab_acquire_project_lock_tool(
    project_id: str, owner: str, ttl_minutes: int = 60
) -> dict[str, Any]:
    """Acquire an expiring single-writer lock before modifying a CST working copy."""
    return operations.acquire_project_lock(project_id, owner, ttl_minutes)


@mcp.tool()
def lab_release_project_lock_tool(project_id: str, owner: str) -> dict[str, Any]:
    """Release a project lock only when the owner matches."""
    return operations.release_project_lock(project_id, owner)


@mcp.tool()
def lab_index_artifacts_tool(
    run_directory: str | None = None,
    rehash: bool = False,
    include_traces: bool = True,
) -> dict[str, Any]:
    """Index cst_runs into the artifact catalog with retention classes and evidence digests."""
    return operations.index_artifacts(
        run_directory=run_directory, rehash=rehash, include_traces=include_traces
    )


@mcp.tool()
def lab_legacy_inventory_tool() -> dict[str, Any]:
    """Cluster legacy run directories into project families read-only, moving nothing."""
    document = operations.legacy_inventory()
    return {key: value for key, value in document.items() if key != "run_directories"}


@mcp.tool()
def lab_plan_retention_tool(
    project_family: list[str] | None = None,
    run_directory: str | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Build a reviewable reclamation plan for recomputable solver caches without deleting."""
    plan = operations.plan_retention(
        families=project_family, run_directory=run_directory, max_bytes=max_bytes
    )
    return {key: value for key, value in plan.items() if key != "units"}


@mcp.tool()
def lab_triage_experiments_tool(statuses: list[str] | None = None) -> dict[str, Any]:
    """Recommend a terminal status for stale experiments without changing any state."""
    return operations.triage_experiments(statuses=statuses)


@mcp.tool()
def lab_lock_inventory_tool() -> dict[str, Any]:
    """List CST .lok files with age and owner; never deletes a lock file."""
    report = operations.lock_inventory()
    return {key: value for key, value in report.items() if key != "locks"}


@mcp.tool()
def lab_purge_expired_locks_tool() -> dict[str, Any]:
    """Delete registry project locks whose TTL already elapsed and record the purge."""
    return operations.purge_expired_locks()


@mcp.tool()
def lab_workspace_governance_tool() -> dict[str, Any]:
    """Report tmp/ and output/ contents with duplicate detection against the artifact catalog."""
    return operations.workspace_governance()


if __name__ == "__main__":
    mcp.run()

