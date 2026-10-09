"""Synthetic grants in temporary workspaces only; never live human consent."""
import asyncio
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'MCP/CST'),str(ROOT/'MCP/CST-Lab/tests')]
from cst_review import approve_with_confirmation
from cst_lab.approval import prepare_review, verify_approval, complete_review, digest
from cst_lab.contracts.attempt import ApprovalError
from cst_lab.validation import SchemaValidationError
from cst_lab.standing_authorization import enroll, applicable
from test_approval import review


@pytest.fixture
def delegated(review,tmp_path):
    source,authority,_=review
    root=tmp_path/'workspace'
    path=root/'projects/validation/designs/coupon/attempts/a01/attempt.json'
    shutil.copytree(source.parent,path.parent)
    grant=enroll(authority,workspace_root=root,topic_id='validation',approved_by='synthetic-test-user',
        statement='Synthetic scoped delegation for unit tests only',source='pytest fixture')
    return path,authority,grant


def approve(path,authority):
    # No elicitation host exists: an active scoped grant is required.
    return asyncio.run(approve_with_confirmation(path,{'w':[1.6,2.4]},context=None,authority=authority))


def test_delegation_binds_artifact_without_claiming_human_viewing(delegated):
    path,authority,grant=delegated
    result=approve(path,authority)
    assert result['approved'] and result['human_reviewed'] is False
    attempt=verify_approval(path,authority=authority)
    assert attempt['approval']['authorization']==grant
    assert attempt['approval']['audit_sha256']==result['audit_sha256']


@pytest.mark.parametrize('change',['signature','revoke','scope','audit','false-viewing'])
def test_delegation_cannot_bypass_integrity_or_revocation(delegated,change):
    path,authority,grant=delegated;approve(path,authority)
    grant_path=authority.directory/'standing/validation.json'
    if change=='revoke':grant_path.unlink()
    elif change=='signature':
        grant['statement']='changed';grant_path.write_text(json.dumps(grant))
    elif change=='scope':
        other=path.parents[6]/'outside'/path.name
        shutil.copytree(path.parent,other.parent);path=other
    elif change=='audit':
        with (path.parent/'audit.html').open('a',encoding='utf-8') as handle:handle.write('changed')
    else:
        a=json.loads(path.read_text());a['approval']['human_reviewed']=True
        signed=dict(a['approval']);signed.pop('signature')
        a['approval']['signature']=authority.sign(signed);path.write_text(json.dumps(a))
    with pytest.raises((ApprovalError,SchemaValidationError)):verify_approval(path,authority=authority)


def test_ranges_and_pending_artifact_changes_still_fail(delegated):
    path,authority,grant=delegated
    with pytest.raises(ApprovalError):
        asyncio.run(approve_with_confirmation(path,{'w':[0,4]},context=None,authority=authority))
    binding=prepare_review(path,'audit.html',{'w':[1.6,2.4]})
    a=json.loads(path.read_text());a['max_iterations']=7;path.write_text(json.dumps(a))
    with pytest.raises(ApprovalError,match='changed while'):
        complete_review(binding,authority=authority,reviewer=grant['approved_by'],
            channel='standing-user-authorization',confirmation=digest(binding),authorization=grant)


def test_delegation_does_not_cover_other_topic_or_workspace(delegated,tmp_path):
    path,authority,grant=delegated
    other=tmp_path/'other/projects/validation/designs/coupon/attempts/a01/attempt.json'
    shutil.copytree(path.parent,other.parent)
    with pytest.raises(ApprovalError,match='outside'):approve(other,authority)
    a=json.loads(path.read_text());a['topic_id']='unrelated';path.write_text(json.dumps(a))
    assert applicable(authority,path) is None
    with pytest.raises(ApprovalError,match='unavailable'):approve(path,authority)


def test_no_grant_can_be_supplied_as_confirmation(delegated):
    path,authority,_=delegated
    binding=prepare_review(path,'audit.html',{'w':[1.6,2.4]})
    with pytest.raises(ApprovalError):
        complete_review(binding,authority=authority,reviewer='someone',
            channel='standing-user-authorization',confirmation=digest(binding))
