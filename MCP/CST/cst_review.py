"""Human review adapter used by the three-tool facade (no CST launch)."""
from __future__ import annotations

import getpass
from pathlib import Path
import sys

from pydantic import BaseModel, Field

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'MCP/CST-Lab/src'),str(ROOT/'MCP/CST-CAD/src')]
from cst_lab.approval import ReviewAuthority, prepare_review, complete_review, digest
from cst_lab.contracts.attempt import ApprovalError


class HumanReview(BaseModel):
    reviewed: bool = Field(default=False, description='I opened this audit, reviewed geometry/source/DRC, and approve exactly the displayed parameter ranges.')


async def approve_with_confirmation(attempt_path, ranges, *, context, authority, audit_html='audit.html', request=None):
    """Use a scoped explicit delegation, otherwise elicit the human operator.

    No reviewer, approval flag or signature is accepted from tool arguments.
    Clients without either authorization path fail closed; CLI callers must not fake a
    context to claim real approval. Unit tests use isolated temporary attempts.
    """
    binding=prepare_review(Path(attempt_path),audit_html,ranges,request=request)
    from cst_lab.standing_authorization import applicable
    grant=applicable(authority,attempt_path)
    if grant is not None:
        attempt=complete_review(binding,authority=authority,reviewer=grant['approved_by'],
            channel='standing-user-authorization',confirmation=digest(binding),authorization=grant)
        return dict(status='approved',approved=True,audit_sha256=binding['audit_sha256'],
            approved_ranges=attempt['approved_ranges'],approved_by=grant['approved_by'],
            approval_basis='standing-user-authorization',human_reviewed=False,
            authorization_sha256=digest(grant))
    message=(f'Review {Path(attempt_path).parent / binding["audit_html"]}\n'
             f'Audit SHA-256: {binding["audit_sha256"]}\n'
             f'Topology: {binding["topology_hash"]}\n'
             f'Allowed ranges: {binding["ranges"]}\n'
             'Unlisted independent parameters remain fixed. Approval covers this exact file; changed files, topology or out-of-range values require a new review.')
    try:
        result=await context.elicit(message=message,schema=HumanReview)
    except Exception as exc:
        raise ApprovalError('human elicitation unavailable; no approval recorded') from exc
    if result.action != 'accept' or result.data is None or result.data.reviewed is not True:
        return dict(status='awaiting_approval',audit_sha256=binding['audit_sha256'],approved=False)
    attempt=complete_review(binding,authority=authority,reviewer=getpass.getuser(),
                            channel='mcp-elicitation',confirmation=digest(binding))
    return dict(status='approved',approved=True,audit_sha256=binding['audit_sha256'],
                approved_ranges=attempt['approved_ranges'],approved_by=attempt['approval']['approved_by'])
