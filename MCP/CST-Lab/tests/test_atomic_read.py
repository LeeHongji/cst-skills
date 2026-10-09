import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from cst_lab import atomic


@pytest.mark.parametrize('winerror',[5,32,33])
def test_json_snapshot_retries_windows_contention(tmp_path,monkeypatch,winerror):
    path=tmp_path/'state.json';atomic.atomic_json(path,{'state':'finalizing'})
    original=Path.read_text;calls=[]
    def read(self,**kwargs):
        calls.append(self)
        if len(calls)<3:
            error=PermissionError('simulated Windows replace conflict');error.winerror=winerror
            raise error
        return original(self,**kwargs)
    monkeypatch.setattr(Path,'read_text',read)
    monkeypatch.setattr(atomic.time,'sleep',lambda _:None)
    assert atomic.read_json(path)=={'state':'finalizing'}
    assert calls==[path]*3


def test_read_contention_has_bounded_retry_and_no_default_state(tmp_path,monkeypatch):
    calls=[]
    def read(*args,**kwargs):
        calls.append(1)
        error=PermissionError('busy');error.winerror=32
        raise error
    clock=iter([0.,.5,1.5,2.5])
    monkeypatch.setattr(Path,'read_text',read)
    monkeypatch.setattr(atomic.time,'monotonic',lambda:next(clock))
    monkeypatch.setattr(atomic.time,'sleep',lambda _:None)
    with pytest.raises(PermissionError):atomic.read_json(tmp_path/'state.json',timeout=2.)
    assert len(calls)==3


@pytest.mark.parametrize('error',[PermissionError('unix permission'),FileNotFoundError('missing'),
                                 json.JSONDecodeError('corrupt','{',0)])
def test_read_does_not_hide_missing_corrupt_or_other_permission_errors(tmp_path,monkeypatch,error):
    calls=[]
    def read(*args,**kwargs):calls.append(1);raise error
    monkeypatch.setattr(Path,'read_text',read)
    with pytest.raises(type(error)):atomic.read_json(tmp_path/'state.json')
    assert len(calls)==1


@pytest.mark.skipif(os.name!='nt',reason='Windows file-sharing contract')
def test_native_exclusive_handle_then_read_retry(tmp_path,monkeypatch):
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
        wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    path=tmp_path/'state.json';atomic.atomic_json(path,{'state':'finalizing'})
    handle=kernel.CreateFileW(str(path),0x80000000,0,None,3,0,None)
    assert handle!=ctypes.c_void_p(-1).value,ctypes.get_last_error()
    blocked=threading.Event();errors=[];original=Path.read_text
    def read(self,**kwargs):
        try:return original(self,**kwargs)
        except PermissionError as exc:
            errors.append((exc.errno,exc.winerror));blocked.set();raise
    monkeypatch.setattr(Path,'read_text',read)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(atomic.read_json,path)
            try:
                assert blocked.wait(2)
                assert errors and errors[0][0]==13
                assert errors[0][1] in (None,5,32,33)
                assert not pending.done()
            finally:
                kernel.CloseHandle(handle);handle=None
            assert pending.result(timeout=4)=={'state':'finalizing'}
    finally:
        if handle is not None:kernel.CloseHandle(handle)
