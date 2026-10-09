from __future__ import annotations

import argparse
import json
from typing import Any

from .index import BrainIndex
from .operations import BrainOperations
from .paths import BrainPaths


def emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="cst-brain")
    root.add_argument("--brain-root")
    commands = root.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build-index")
    build.set_defaults(action="build-index")

    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--type", dest="page_type")
    search.add_argument("--status")

    context = commands.add_parser("context")
    context.add_argument("query")
    context.add_argument("--mode", choices=["quick", "standard", "deep"], default="standard")

    read = commands.add_parser("read")
    read.add_argument("identifier")

    get_case = commands.add_parser("get-case")
    get_case.add_argument("identifier")

    get_trace = commands.add_parser("get-trace")
    get_trace.add_argument("case_id")

    strategies = commands.add_parser("list-strategies")
    strategies.add_argument("--validated-only", action="store_true")

    ingest = commands.add_parser("ingest")
    ingest.add_argument("source_path")
    ingest.add_argument("--title")
    ingest.add_argument("--source-type", default="document")
    ingest.add_argument("--force", action="store_true")

    compile_run = commands.add_parser("compile-run")
    compile_run.add_argument("run_path")
    compile_run.add_argument("--case-id")
    compile_run.add_argument("--title")

    lint = commands.add_parser("lint")
    lint.set_defaults(action="lint")

    promote = commands.add_parser("promote")
    promote.add_argument("identifier")
    promote.add_argument("--human-approved", action="store_true")

    candidate = commands.add_parser("create-candidate")
    candidate.add_argument("title")
    candidate.add_argument("body")
    candidate.add_argument("--type", dest="page_type", default="claim")
    candidate.add_argument("--evidence", action="append", default=[])
    candidate.add_argument("--domain")

    publish_iteration = commands.add_parser(
        "publish-function-iteration",
        help="Project one finalized CST Function iteration into the Brain",
    )
    publish_iteration.add_argument("--history", required=True)
    publish_iteration.add_argument("--fact-file", required=True)
    publish_iteration.add_argument("--request-file", required=True)
    publish_iteration.add_argument("--job-ref", required=True)
    publish_iteration.add_argument("--workspace-root", required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    paths = BrainPaths.resolve(args.brain_root)
    index = BrainIndex(paths)
    operations = BrainOperations(paths)
    if args.command == "build-index":
        emit(index.build())
    elif args.command == "search":
        emit(index.search(args.query, args.limit, args.page_type, args.status))
    elif args.command == "context":
        emit(index.context_pack(args.query, args.mode))
    elif args.command == "read":
        emit(operations.read_page(args.identifier))
    elif args.command == "get-case":
        emit(operations.get_case(args.identifier))
    elif args.command == "get-trace":
        emit(operations.get_trace(args.case_id))
    elif args.command == "list-strategies":
        emit(operations.list_strategies(args.validated_only))
    elif args.command == "ingest":
        emit(operations.ingest_source(args.source_path, args.title, args.source_type, args.force))
    elif args.command == "compile-run":
        emit(operations.compile_run(args.run_path, args.case_id, args.title))
    elif args.command == "lint":
        emit(operations.lint())
    elif args.command == "promote":
        emit(operations.promote(args.identifier, args.human_approved))
    elif args.command == "create-candidate":
        emit(operations.create_candidate(args.title, args.body, args.page_type, args.evidence, args.domain))
    elif args.command == "publish-function-iteration":
        from .function_iterations import publish_function_iteration

        emit(
            publish_function_iteration(
                history=args.history,
                fact_file=args.fact_file,
                request_file=args.request_file,
                job_ref=args.job_ref,
                workspace_root=args.workspace_root,
                brain_root=args.brain_root,
            )
        )
