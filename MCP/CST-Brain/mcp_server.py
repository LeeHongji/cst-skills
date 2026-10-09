#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from cst_brain import BrainIndex, BrainOperations, BrainPaths


INSTRUCTIONS = """Use this local CST Brain as the evidence-backed memory plane.
Read-only search and context tools are safe. Ingest, compile, promote, and fix
operations mutate the Obsidian vault and must preserve raw evidence. Do not
promote single-run observations into universal engineering claims."""

mcp = FastMCP("cst-second-brain-mcp", instructions=INSTRUCTIONS)
paths = BrainPaths.resolve()
index = BrainIndex(paths)
operations = BrainOperations(paths)


@mcp.tool()
def brain_search_tool(
    query: str,
    limit: int = 8,
    page_type: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Search CST knowledge with Chinese/English BM25 and evidence-aware ranking."""
    return index.search(query, limit=limit, page_type=page_type, status=status)


@mcp.tool()
def brain_read_page_tool(identifier: str) -> dict[str, Any]:
    """Read a brain page by vault-relative path, stable ID, title, or filename."""
    return operations.read_page(identifier)


@mcp.tool()
def brain_context_pack_tool(query: str, mode: str = "standard") -> dict[str, Any]:
    """Build a quick, standard, or deep context pack for a CST task."""
    return index.context_pack(query, mode=mode)


@mcp.tool()
def brain_get_case_tool(identifier: str) -> dict[str, Any]:
    """Read a compiled CST case dossier."""
    return operations.get_case(identifier)


@mcp.tool()
def brain_get_trace_tool(case_id: str) -> dict[str, Any]:
    """Read the immutable manifest for a compiled CST trace snapshot."""
    return operations.get_trace(case_id)


@mcp.tool()
def brain_list_strategies_tool(validated_only: bool = False) -> dict[str, Any]:
    """List optimization strategies and their evidence status."""
    return operations.list_strategies(validated_only=validated_only)


@mcp.tool()
def brain_ingest_tool(
    source_path: str,
    title: str | None = None,
    source_type: str = "document",
    force: bool = False,
) -> dict[str, Any]:
    """Capture a local source immutably and create its candidate source page."""
    return operations.ingest_source(source_path, title, source_type, force)


@mcp.tool()
def brain_compile_run_tool(
    run_path: str,
    case_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Compile a completed cst_runs directory into a case and trace manifest."""
    return operations.compile_run(run_path, case_id, title)


@mcp.tool()
def brain_create_candidate_tool(
    title: str,
    body: str,
    page_type: str = "claim",
    evidence: list[str] | None = None,
    domain: str | None = None,
) -> dict[str, Any]:
    """Create an unpromoted evidence candidate in the CST Brain inbox."""
    return operations.create_candidate(title, body, page_type, evidence, domain)


@mcp.tool()
def brain_promote_claim_tool(
    identifier: str,
    human_approved: bool = False,
) -> dict[str, Any]:
    """Promote a candidate only when evidence or explicit human approval permits it."""
    return operations.promote(identifier, human_approved=human_approved)


@mcp.tool()
def brain_lint_fix_tool(fix_safe: bool = False) -> dict[str, Any]:
    """Audit schemas, links, IDs, and evidence; optionally rebuild the safe index."""
    result = operations.lint()
    if fix_safe:
        result["index_rebuild"] = index.build()
    return result


@mcp.tool()
def brain_rebuild_index_tool() -> dict[str, Any]:
    """Rebuild the derived BM25 index from canonical Markdown pages."""
    return index.build()


if __name__ == "__main__":
    mcp.run()

