"""Real Windows process containment, including abrupt supervisor termination."""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from cst_guardian.windows_job import WindowsJobProcess
from cst_guardian.supervisor import run_guarded

HELPER=Path(__file__).with_name('owned_job_process.py')


def receipt(root,name,owner):
    deadline=time.monotonic()+8
    path=root/(name+'.json')
    while not path.exists():
        assert owner.poll() is None,'owned process ended before receipt'
        assert time.monotonic()<deadline,'owned process receipt timeout'
        time.sleep(.02)
    return json.loads(path.read_text(encoding='utf-8'))


class ObservedProcess:
    """Keep a native handle so PID reuse cannot satisfy or break death checks."""
    def __init__(self,pid):
        self.api=C.WinDLL('kernel32',use_last_error=True)
        self.api.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];self.api.OpenProcess.restype=W.HANDLE
        self.api.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];self.api.WaitForSingleObject.restype=W.DWORD
        self.api.TerminateProcess.argtypes=[W.HANDLE,W.UINT];self.api.TerminateProcess.restype=W.BOOL
        self.api.CloseHandle.argtypes=[W.HANDLE];self.api.CloseHandle.restype=W.BOOL
        self.handle=self.api.OpenProcess(0x100001,False,pid)  # SYNCHRONIZE | TERMINATE
        assert self.handle,C.get_last_error()
    def alive(self):return self.api.WaitForSingleObject(self.handle,0)==258
    def wait_dead(self):assert self.api.WaitForSingleObject(self.handle,5000)==0
    def terminate(self):
        if self.alive():assert self.api.TerminateProcess(self.handle,75)
    def close(self):self.api.CloseHandle(self.handle)


def test_native_create_preserves_unicode_arguments_environment_and_streams(tmp_path):
    script="import os,sys;print(sys.argv[1]);print(os.environ['OWNED_JOB_TEST']);print(os.getcwd());print('error-stream',file=sys.stderr)"
    with (tmp_path/'out.txt').open('w') as out,(tmp_path/'err.txt').open('w') as err:
        process=WindowsJobProcess([sys.executable,'-c',script,'中文 path with spaces "quoted"'],
            stdout=out,stderr=err,cwd=tmp_path,env=dict(os.environ,OWNED_JOB_TEST='参数 值',PYTHONIOENCODING='utf-8'))
        try:
            assert process.wait(timeout=5)==0
            assert process.poll()==0
        finally: cleanup=process.close()
    assert cleanup['after']['active_processes']==0
    assert (tmp_path/'out.txt').read_text(encoding='utf-8').splitlines()==[
        '中文 path with spaces "quoted"','参数 值',str(tmp_path)]
    assert (tmp_path/'err.txt').read_text(encoding='utf-8').strip()=='error-stream'


def test_abrupt_supervisor_death_kills_owned_tree_preserves_unrelated_process(tmp_path):
    flags={'creationflags':subprocess.CREATE_NO_WINDOW}
    sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],**flags)
    parent=subprocess.Popen([sys.executable,str(HELPER),'supervise',str(tmp_path)],**flags)
    observed=[]
    try:
        supervisor=ObservedProcess(receipt(tmp_path,'supervisor',parent)['pid']);observed.append(supervisor)
        worker=ObservedProcess(receipt(tmp_path,'worker',parent)['pid']);observed.append(worker)
        descendant=ObservedProcess(receipt(tmp_path,'grandchild',parent)['pid']);observed.append(descendant)
        assert all(p.alive() for p in observed)
        supervisor.terminate();supervisor.wait_dead()
        worker.wait_dead();descendant.wait_dead()
        parent.wait(timeout=5)
        assert sentinel.poll() is None
        assert not (tmp_path/'guardian/guard-report.json').exists()  # no finally required
    finally:
        for process in observed:process.terminate();process.close()
        if parent.poll() is None:parent.kill()
        parent.wait(timeout=5)
        sentinel.terminate();sentinel.wait(timeout=5)


def test_guardian_timeout_reaps_nested_python_launchers(tmp_path):
    report=run_guarded([sys.executable,str(HELPER),'worker',str(tmp_path)],
        log_dir=tmp_path/'guardian',scope_worker_descendants=True,timeout_s=.8,poll_interval_s=.02)
    assert report.outcome=='timeout'
    assert (tmp_path/'grandchild.json').exists()
    cleanup=next(e['kernel_job'] for e in report.events if e['action']=='owned-process-cleanup')
    assert cleanup['before']['total_processes']>=2
    assert cleanup['after']['active_processes']==0
    assert report.events[0]['kernel_job_containment'] is True


def test_normal_worker_exit_reaps_stranded_child(tmp_path):
    script="import subprocess,sys;subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);print('spawned',flush=True)"
    report=run_guarded([sys.executable,'-c',script],log_dir=tmp_path,
        scope_worker_descendants=True,poll_interval_s=.02)
    assert report.ok
    cleanup=next(e['kernel_job'] for e in report.events if e['action']=='owned-process-cleanup')
    assert cleanup['before']['active_processes']>=1
    assert cleanup['after']['active_processes']==0


def test_native_exit_259_is_not_misread_as_still_running(tmp_path):
    with (tmp_path/'out').open('w') as out:
        process=WindowsJobProcess([sys.executable,'-c','import os;os._exit(259)'],stdout=out,stderr=out)
        try: assert process.wait(timeout=5)==259
        finally:process.close()


def test_bad_executable_fails_before_any_worker_can_run(tmp_path):
    with (tmp_path/'out').open('w') as out:
        with pytest.raises(OSError):
            WindowsJobProcess([str(tmp_path/'missing.exe')],stdout=out,stderr=out)
        with pytest.raises(ValueError,match='absolute'):
            WindowsJobProcess(['python.exe'],stdout=out,stderr=out)
        with pytest.raises(ValueError,match='NUL'):
            WindowsJobProcess([sys.executable,'-c','pass\0ignored'],stdout=out,stderr=out)
