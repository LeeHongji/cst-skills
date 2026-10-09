"""Production three-tool task facade for CST Automation."""
from pathlib import Path
from typing import Any
from mcp.server.fastmcp import FastMCP, Context
from cst_agent_api import FunctionService
from cst_workspace import WorkspaceRouter
from cst_review import approve_with_confirmation
from cst_lab.approval import ReviewAuthority
from cst_lab.function_audit import latest_review
from cst_trace import install_fastmcp_trace

service=WorkspaceRouter()
mcp=FastMCP('cst-function',instructions='Use cst_run for tasks, cst_get for evidence and progress, and cst_approve for artifact-bound approval. Approval uses individual human confirmation or explicit scoped standing user authorization; delegated approval never claims personal viewing. Offline analysis/comparison is connected. Screen requests may reuse exact verified native evidence without CST and reevaluate current gates; confirm requests always execute independently. Other approved simulation requests dispatch an owned Guardian worker. Missing core native readback or any observed mismatch blocks solving; unavailable detailed setting getters remain explicitly deferred. New simulation completion requires convergence, exported curves, a verified independent cache-free CST reopen and immutable evidence publication. Cache results cite the original simulation and claim no new solve/reopen. Core verification does not claim full setting coverage. A queued job or diagnostic archive is not a simulation result.')
install_fastmcp_trace(mcp)


@mcp.tool()
def cst_run(request: dict[str, Any]) -> dict[str, Any]:
    """Submit an idempotent request and return a job reference without blocking on execution."""
    return service.run(request)


@mcp.tool()
def cst_get(ref: str) -> dict[str, Any]:
    """Read job progress, metrics or hash-verified artifact evidence."""
    return service.get(ref)


@mcp.tool()
async def cst_approve(attempt: str, ranges: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Bind audit/ranges using explicit scoped user delegation or individual human confirmation."""
    scoped=service.service(service.attempt_root(attempt))
    path=(scoped.root/attempt).resolve()
    relative=path.relative_to(scoped.root)
    parts=relative.parts
    if len(parts)!=7 or (parts[0],parts[2],parts[4],parts[6])!=('projects','designs','attempts','attempt.json'):
        raise ValueError('attempt must be a projects/<topic>/designs/<design>/attempts/<attempt>/attempt.json path')
    return await approve_with_confirmation(path,ranges,context=ctx,
        authority=ReviewAuthority(scoped.paths.registry_root/'approval'),audit_html=latest_review(path,scoped.paths))


if __name__=='__main__':
    mcp.run()
