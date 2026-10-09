from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading

import pytest

from cst_lab.atomic import atomic_json,_replace_retry
import cst_lab.atomic as atomic


def test_windows_sharing_violation_retries_without_removing_old_state(tmp_path,monkeypatch):
    path=tmp_path/'state.json';atomic_json(path,{'state':'old'})
    original=atomic.os.replace;calls=0
    def busy(source,target):
        nonlocal calls
        calls+=1
        if calls<3:
            assert json.loads(path.read_text())=={'state':'old'}
            error=PermissionError('sharing violation');error.winerror=32
            raise error
        return original(source,target)
    monkeypatch.setattr(atomic.os,'replace',busy)
    atomic_json(path,{'state':'new'})
    assert calls==3 and json.loads(path.read_text())=={'state':'new'}
    assert not list(tmp_path.glob('*.tmp'))


def test_real_open_reader_and_writer_preserve_complete_documents(tmp_path,monkeypatch):
    path=tmp_path/'state.json';atomic_json(path,{'state':'old'})
    attempted=threading.Event();sharing_errors=[]
    original=atomic.os.replace
    def observed(source,target):
        try: return original(source,target)
        except PermissionError as exc:
            sharing_errors.append(getattr(exc,'winerror',None));raise
        finally: attempted.set()
    monkeypatch.setattr(atomic.os,'replace',observed)
    def write():
        atomic_json(path,{'state':'new'})
    with ThreadPoolExecutor(max_workers=1) as pool:
        with path.open('rb') as reader:
            future=pool.submit(write);assert attempted.wait(2)
            assert json.loads(reader.read())=={'state':'old'}
            if os.name=='nt': assert sharing_errors and sharing_errors[0] in (5,32,33)
        future.result(timeout=5)
    assert json.loads(path.read_text())=={'state':'new'}


def test_persistent_or_non_windows_permission_failure_remains_an_error(tmp_path,monkeypatch):
    old=tmp_path/'old';old.write_text('original')
    new=tmp_path/'new';new.write_text('replacement')
    def denied(*args):
        error=PermissionError('access denied');error.winerror=5
        raise error
    monkeypatch.setattr(atomic.os,'replace',denied)
    with pytest.raises(PermissionError): _replace_retry(new,old,timeout=0)
    assert old.read_text()=='original' and new.read_text()=='replacement'
