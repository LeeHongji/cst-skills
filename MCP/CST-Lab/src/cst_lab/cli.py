from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .operations import LabOperations
from .paths import LabPaths
from .project_package import parse_artifacts, promote_project_package, validate_package
from .topic_workspace import init_design, init_topic, validate_topic_workspace


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="cst-lab")
    root.add_argument("--workspace-root")
    commands = root.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register")
    register.add_argument("source_path")

    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("project_id")

    create = commands.add_parser("create-experiment")
    create.add_argument("spec_path")

    validate = commands.add_parser("validate-experiment")
    validate.add_argument("experiment_id")

    status = commands.add_parser("status")
    status.add_argument("experiment_id")

    transition = commands.add_parser("transition-experiment")
    transition.add_argument("experiment_id")
    transition.add_argument("status")
    transition.add_argument("--reason")

    trial = commands.add_parser("create-trial")
    trial.add_argument("experiment_id")
    trial.add_argument("parameters_path")

    update = commands.add_parser("update-trial")
    update.add_argument("trial_id")
    update.add_argument("status")
    update.add_argument("--objectives")
    update.add_argument("--constraints")
    update.add_argument("--error")

    compare = commands.add_parser("compare")
    compare.add_argument("experiment_id")

    compile_case = commands.add_parser("compile-case")
    compile_case.add_argument("experiment_id")

    lock = commands.add_parser("lock")
    lock.add_argument("project_id")
    lock.add_argument("owner")
    lock.add_argument("--ttl-minutes", type=int, default=60)

    unlock = commands.add_parser("unlock")
    unlock.add_argument("project_id")
    unlock.add_argument("owner")

    index = commands.add_parser(
        "index-artifacts", help="Scan cst_runs and write the artifact catalog"
    )
    index.add_argument("--run-directory", help="Limit the scan to one top-level run directory")
    index.add_argument(
        "--rehash", action="store_true", help="Recompute digests even for unchanged evidence"
    )
    index.add_argument("--skip-traces", action="store_true", help="Exclude _mcp_traces")
    index.add_argument(
        "--no-prune", action="store_true", help="Keep catalog rows for files that vanished"
    )

    legacy = commands.add_parser(
        "legacy-inventory", help="Cluster legacy run directories into project families"
    )
    legacy.add_argument("--stdout-only", action="store_true", help="Do not write the JSON file")

    collect = commands.add_parser("gc", help="Plan (default) or execute run-workspace reclamation")
    collect.add_argument("--dry-run", action="store_true", default=True)
    collect.add_argument(
        "--execute",
        action="store_true",
        help="Delete released files after writing the reclamation manifest",
    )
    collect.add_argument(
        "--confirm", action="store_true", help="Required second acknowledgement for --execute"
    )
    collect.add_argument("--project-family", action="append", dest="project_family")
    collect.add_argument("--run-directory")
    collect.add_argument("--max-bytes", type=int)
    collect.add_argument(
        "--protect-best-per-experiment",
        action="store_true",
        help="Also force-retain the best trial of screening experiments that missed target",
    )
    collect.add_argument("--full", action="store_true", help="Print every unit decision")

    triage = commands.add_parser(
        "triage-experiments", help="Recommend a terminal status for stale experiments"
    )
    triage.add_argument("--status", action="append", dest="statuses")

    lok = commands.add_parser("lock-inventory", help="List CST .lok files without deleting them")
    lok.add_argument(
        "--no-probe",
        action="store_true",
        help="Skip the read-only share probe that detects locks held by a live process",
    )
    lok.add_argument("--stale-after-hours", type=int, default=24)
    commands.add_parser("purge-locks", help="Delete registry project locks past their TTL")
    commands.add_parser("workspace-governance", help="Report on tmp/ and output/ contents")
    commands.add_parser("schema-state", help="Show registry schema version and migrations")

    promote = commands.add_parser(
        "promote-package",
        help="Copy selected, reviewable run evidence into a topic package",
    )
    promote.add_argument("--source-project", required=True)
    promote.add_argument("--evidence-dir", required=True)
    promote.add_argument("--origin-run-uri", required=True)
    promote.add_argument("--topic-id", required=True)
    promote.add_argument("--design-id", required=True)
    promote.add_argument("--attempt-id", required=True)
    promote.add_argument("--source-commit")
    promote.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="ROLE=PATH",
        help="Repeat for every Touchstone/CSV/plot/metric/log to promote",
    )

    package = commands.add_parser(
        "validate-package",
        help="Verify a promoted topic evidence package contains no solver cache",
    )
    package.add_argument("evidence_dir")

    topic = commands.add_parser(
        "init-topic",
        help="Create the standard durable workspace for a new research topic",
    )
    topic.add_argument("--topic-id", required=True)
    topic.add_argument("--title", required=True)
    topic.add_argument("--shared-physics", action="append", required=True)
    topic.add_argument(
        "--source-kind",
        choices=["paper", "book", "datasheet", "internal", "standard"],
        required=True,
    )
    topic.add_argument("--source-citation", required=True)
    topic.add_argument("--source-doi")
    topic.add_argument("--source-local-path")

    design = commands.add_parser(
        "init-design",
        help="Add a standard design skeleton with machine-readable gates",
    )
    design.add_argument("--topic-dir", required=True)
    design.add_argument("--design-id", required=True)
    design.add_argument("--title", required=True)
    design.add_argument("--ports", type=int, required=True)
    design.add_argument("--acceptance-file", required=True)
    design.add_argument("--model", default="model.py")

    validate_topic = commands.add_parser(
        "validate-topic",
        help="Validate all contracts, links, iterations, and evidence hashes in a topic",
    )
    validate_topic.add_argument("topic_dir")
    return root


def main() -> None:
    args = parser().parse_args()
    operations = LabOperations(LabPaths.resolve(args.workspace_root))
    if args.command == "register":
        emit(operations.register_project(args.source_path))
    elif args.command == "snapshot":
        emit(operations.snapshot_model(args.project_id))
    elif args.command == "create-experiment":
        emit(operations.create_experiment(load_json(args.spec_path)))
    elif args.command == "validate-experiment":
        emit(operations.validate_experiment(args.experiment_id))
    elif args.command == "status":
        emit(
            {
                "experiment": operations.registry.get_experiment(args.experiment_id),
                "trials": operations.list_trials(args.experiment_id),
                "events": operations.registry.events("experiment", args.experiment_id),
            }
        )
    elif args.command == "transition-experiment":
        emit(operations.transition_experiment(args.experiment_id, args.status, args.reason))
    elif args.command == "create-trial":
        emit(operations.create_trial(args.experiment_id, load_json(args.parameters_path)))
    elif args.command == "update-trial":
        emit(
            operations.transition_trial(
                args.trial_id,
                args.status,
                objectives=load_json(args.objectives) if args.objectives else None,
                constraints=load_json(args.constraints) if args.constraints else None,
                error=load_json(args.error) if args.error else None,
            )
        )
    elif args.command == "compare":
        emit(operations.compare_trials(args.experiment_id))
    elif args.command == "compile-case":
        emit(operations.compile_case_handoff(args.experiment_id))
    elif args.command == "lock":
        emit(operations.acquire_project_lock(args.project_id, args.owner, args.ttl_minutes))
    elif args.command == "unlock":
        emit(operations.release_project_lock(args.project_id, args.owner))
    elif args.command == "index-artifacts":
        emit(
            operations.index_artifacts(
                run_directory=args.run_directory,
                rehash=args.rehash,
                include_traces=not args.skip_traces,
                prune=not args.no_prune,
            )
        )
    elif args.command == "legacy-inventory":
        document = operations.legacy_inventory(write=not args.stdout_only)
        emit({key: value for key, value in document.items() if key != "run_directories"})
    elif args.command == "gc":
        if args.execute:
            emit(
                operations.execute_retention(
                    families=args.project_family,
                    run_directory=args.run_directory,
                    max_bytes=args.max_bytes,
                    protect_best_per_experiment=args.protect_best_per_experiment,
                    confirm=args.confirm,
                )
            )
        else:
            plan = operations.plan_retention(
                families=args.project_family,
                run_directory=args.run_directory,
                max_bytes=args.max_bytes,
                protect_best_per_experiment=args.protect_best_per_experiment,
            )
            emit(plan if args.full else {key: value for key, value in plan.items() if key != "units"})
    elif args.command == "triage-experiments":
        emit(operations.triage_experiments(statuses=args.statuses))
    elif args.command == "lock-inventory":
        report = operations.lock_inventory(
            probe=not args.no_probe, stale_after_hours=args.stale_after_hours
        )
        emit({key: value for key, value in report.items() if key != "locks"})
    elif args.command == "purge-locks":
        emit(operations.purge_expired_locks())
    elif args.command == "workspace-governance":
        emit(operations.workspace_governance())
    elif args.command == "schema-state":
        emit(operations.schema_state())
    elif args.command == "promote-package":
        emit(
            promote_project_package(
                workspace_root=operations.paths.workspace_root,
                source_project=Path(args.source_project),
                evidence_dir=Path(args.evidence_dir),
                artifacts=parse_artifacts(args.artifact),
                origin_run_uri=args.origin_run_uri,
                topic_id=args.topic_id,
                design_id=args.design_id,
                attempt_id=args.attempt_id,
                source_commit=args.source_commit,
            )
        )
    elif args.command == "validate-package":
        problems = validate_package(Path(args.evidence_dir))
        emit({"status": "valid" if not problems else "invalid", "problems": problems})
    elif args.command == "init-topic":
        source = {"kind": args.source_kind, "citation": args.source_citation}
        if args.source_doi:
            source["doi"] = args.source_doi
        if args.source_local_path:
            source["local_path"] = args.source_local_path
        target = init_topic(
            operations.paths.workspace_root,
            topic_id=args.topic_id,
            title=args.title,
            shared_physics=args.shared_physics,
            sources=[source],
        )
        emit(
            {
                "status": "created",
                "topic_dir": str(target),
                "branch": f"topic/{args.topic_id}",
                "next_action": "init-design",
            }
        )
    elif args.command == "init-design":
        payload = load_json(args.acceptance_file)
        gates = payload["acceptance"] if isinstance(payload, dict) else payload
        target = init_design(
            Path(args.topic_dir),
            design_id=args.design_id,
            title=args.title,
            ports=args.ports,
            acceptance=gates,
            model=args.model,
        )
        emit(
            {
                "status": "created",
                "design_dir": str(target),
                "next_action": "implement model.py and generate geometry-ir.json",
            }
        )
    elif args.command == "validate-topic":
        report = validate_topic_workspace(Path(args.topic_dir))
        emit(report)
        if report["status"] != "valid":
            raise SystemExit(1)

