import asyncio
from types import SimpleNamespace
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'MCP/CST'),str(ROOT/'MCP/CST-Lab/tests')]
from cst_review import approve_with_confirmation
from cst_lab.contracts.attempt import ApprovalError
from test_approval import review  # isolated temporary fixture; not live approval


class Host:
    def __init__(self, action='decline', reviewed=False):self.action=action;self.reviewed=reviewed;self.message=''
    async def elicit(self,*,message,schema):
        self.message=message
        return SimpleNamespace(action=self.action,data=schema(reviewed=self.reviewed))


def test_decline_or_unchecked_form_never_writes_approval(review):
    path,authority,binding=review;before=path.read_bytes()
    for host in [Host(),Host('accept',False)]:
        result=asyncio.run(approve_with_confirmation(path,binding['ranges'],context=host,authority=authority))
        assert result['approved'] is False and path.read_bytes()==before


def test_confirmed_host_form_binds_displayed_hash_and_uses_os_identity(review):
    import getpass
    path,authority,binding=review;host=Host('accept',True)
    result=asyncio.run(approve_with_confirmation(path,binding['ranges'],context=host,authority=authority))
    assert result['approved_by']==getpass.getuser()
    assert binding['audit_sha256'] in host.message


def test_host_without_human_confirmation_fails_closed(review):
    path,authority,binding=review
    with pytest.raises(ApprovalError,match='unavailable'):
        asyncio.run(approve_with_confirmation(path,binding['ranges'],context=None,authority=authority))
