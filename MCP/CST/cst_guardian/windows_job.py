"""Windows 10+ process lifetime containment for a newly owned CST worker.

The kernel assigns the job during CreateProcess (JOB_LIST), before child code
can run. The uniquely named, non-inherited job has KILL_ON_JOB_CLOSE and no breakaway
permission. Abrupt supervisor death therefore does not depend on Python cleanup.
Existing or externally attached CST processes are never assigned to this job.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import math
import msvcrt
import os
import subprocess
import time
import uuid


class _BasicLimits(C.Structure):
    _fields_=[('process_time',C.c_int64),('job_time',C.c_int64),('flags',W.DWORD),
              ('min_working_set',C.c_size_t),('max_working_set',C.c_size_t),
              ('active_limit',W.DWORD),('affinity',C.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]


class _IOCounters(C.Structure):
    _fields_=[(name,C.c_uint64) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]


class _ExtendedLimits(C.Structure):
    _fields_=[('basic',_BasicLimits),('io',_IOCounters),('process_memory',C.c_size_t),
              ('job_memory',C.c_size_t),('peak_process_memory',C.c_size_t),('peak_job_memory',C.c_size_t)]


class _StartupInfo(C.Structure):
    _fields_=[('cb',W.DWORD),('reserved',W.LPWSTR),('desktop',W.LPWSTR),('title',W.LPWSTR),
        ('x',W.DWORD),('y',W.DWORD),('xsize',W.DWORD),('ysize',W.DWORD),
        ('xchars',W.DWORD),('ychars',W.DWORD),('fill',W.DWORD),('flags',W.DWORD),
        ('show',W.WORD),('reserved_size',W.WORD),('reserved_bytes',C.c_void_p),
        ('stdin',W.HANDLE),('stdout',W.HANDLE),('stderr',W.HANDLE)]


class _StartupInfoEx(C.Structure):
    _fields_=[('base',_StartupInfo),('attributes',C.c_void_p)]


class _ProcessInfo(C.Structure):
    _fields_=[('process',W.HANDLE),('thread',W.HANDLE),('pid',W.DWORD),('tid',W.DWORD)]


class _Accounting(C.Structure):
    _fields_=[(name,C.c_int64) for name in ('user','kernel','period_user','period_kernel')]+[
        (name,W.DWORD) for name in ('page_faults','total_processes','active_processes','terminated_processes')]


def _api():
    kernel=C.WinDLL('kernel32',use_last_error=True)
    signatures={
        'CreateJobObjectW':([C.c_void_p,W.LPCWSTR],W.HANDLE),
        'OpenJobObjectW':([W.DWORD,W.BOOL,W.LPCWSTR],W.HANDLE),
        'IsProcessInJob':([W.HANDLE,W.HANDLE,C.POINTER(W.BOOL)],W.BOOL),
        'SetInformationJobObject':([W.HANDLE,C.c_int,C.c_void_p,W.DWORD],W.BOOL),
        'QueryInformationJobObject':([W.HANDLE,C.c_int,C.c_void_p,W.DWORD,C.c_void_p],W.BOOL),
        'TerminateJobObject':([W.HANDLE,W.UINT],W.BOOL),
        'CloseHandle':([W.HANDLE],W.BOOL),
        'GetCurrentProcess':([],W.HANDLE),
        'DuplicateHandle':([W.HANDLE,W.HANDLE,W.HANDLE,C.POINTER(W.HANDLE),W.DWORD,W.BOOL,W.DWORD],W.BOOL),
        'InitializeProcThreadAttributeList':([C.c_void_p,W.DWORD,W.DWORD,C.POINTER(C.c_size_t)],W.BOOL),
        'UpdateProcThreadAttribute':([C.c_void_p,W.DWORD,C.c_size_t,C.c_void_p,C.c_size_t,C.c_void_p,C.c_void_p],W.BOOL),
        'DeleteProcThreadAttributeList':([C.c_void_p],None),
        'CreateProcessW':([W.LPCWSTR,W.LPWSTR,C.c_void_p,C.c_void_p,W.BOOL,W.DWORD,
                           C.c_void_p,W.LPCWSTR,C.POINTER(_StartupInfoEx),C.POINTER(_ProcessInfo)],W.BOOL),
        'WaitForSingleObject':([W.HANDLE,W.DWORD],W.DWORD),
        'GetExitCodeProcess':([W.HANDLE,C.POINTER(W.DWORD)],W.BOOL),
        'TerminateProcess':([W.HANDLE,W.UINT],W.BOOL),
    }
    for name,(args,result) in signatures.items():
        function=getattr(kernel,name);function.argtypes=args;function.restype=result
    return kernel


def _check(value):
    if not value: raise C.WinError(C.get_last_error())
    return value


def require_current_job_containment():
    """Refuse native Function writes outside a non-breakaway kill-on-close job.

    Python's Windows venv launcher creates an inner job with silent breakaway.
    Query the exact Guardian job and membership, not the immediate inner job.
    Open only a query handle and close it before launching CST; it must not keep
    the parent-owned kill-on-close job alive for the duration of execution.
    """
    name=os.environ.get('CST_GUARDIAN_JOB_NAME')
    if not name: raise RuntimeError('native Function worker has no Guardian job identity')
    kernel=_api();limits=_ExtendedLimits();member=W.BOOL()
    handle=_check(kernel.OpenJobObjectW(4,False,name))  # JOB_OBJECT_QUERY
    try:
        _check(kernel.IsProcessInJob(kernel.GetCurrentProcess(),handle,C.byref(member)))
        _check(kernel.QueryInformationJobObject(handle,9,C.byref(limits),C.sizeof(limits),None))
        flags=limits.basic.flags
        if not member.value or not flags & 0x2000 or flags & (0x800 | 0x1000):
            raise RuntimeError(f'worker is outside required Guardian containment (member={member.value}, flags={flags:#x})')
        return dict(kill_on_job_close=True,breakaway=False,limit_flags=flags,job_name=name)
    finally: kernel.CloseHandle(handle)


class WindowsJobProcess:
    """The small Popen interface used by Guardian, with an owned kernel job."""

    def __init__(self,argv,*,stdout,stderr,cwd=None,env=None):
        if not argv or not os.path.isabs(str(argv[0])):
            raise ValueError('owned worker executable must be an absolute path')
        self.args=list(map(str,argv));self.returncode=None
        if any('\0' in value for value in self.args):
            raise ValueError('worker arguments must not contain NUL')
        self._kernel=_api();self._job=None;self._process=None;self.pid=None
        k=self._kernel;duplicates=[];attributes=None
        try:
            job_name='Local\\CST-Guardian-'+uuid.uuid4().hex
            self._job=_check(k.CreateJobObjectW(None,job_name))
            if C.get_last_error()==183: raise RuntimeError('Guardian job name already exists')
            limits=_ExtendedLimits();limits.basic.flags=0x2000  # KILL_ON_JOB_CLOSE
            _check(k.SetInformationJobObject(self._job,9,C.byref(limits),C.sizeof(limits)))
            with open(os.devnull,'rb') as null:
                for stream in (null,stdout,stderr):
                    target=W.HANDLE()
                    _check(k.DuplicateHandle(k.GetCurrentProcess(),msvcrt.get_osfhandle(stream.fileno()),
                        k.GetCurrentProcess(),C.byref(target),0,True,2))
                    duplicates.append(target.value)
            size=C.c_size_t()
            k.InitializeProcThreadAttributeList(None,2,0,C.byref(size))
            if not size.value: raise C.WinError(C.get_last_error())
            buffer=C.create_string_buffer(size.value)
            _check(k.InitializeProcThreadAttributeList(buffer,2,0,C.byref(size)))
            attributes=buffer
            streams=(W.HANDLE*3)(*duplicates);jobs=(W.HANDLE*1)(self._job)
            _check(k.UpdateProcThreadAttribute(buffer,0,0x20002,streams,C.sizeof(streams),None,None))
            _check(k.UpdateProcThreadAttribute(buffer,0,0x2000D,jobs,C.sizeof(jobs),None,None))
            startup=_StartupInfoEx();startup.base.cb=C.sizeof(startup)
            startup.base.flags=0x100  # STARTF_USESTDHANDLES
            startup.base.stdin,startup.base.stdout,startup.base.stderr=duplicates
            startup.attributes=C.cast(buffer,C.c_void_p)
            environment=dict(os.environ if env is None else env)
            environment['CST_GUARDIAN_JOB_NAME']=job_name
            if any('\0' in str(key)+str(value) or '=' in str(key) for key,value in environment.items()):
                raise ValueError('invalid worker environment')
            env_block=C.create_unicode_buffer('\0'.join(f'{key}={value}' for key,value in
                sorted(environment.items(),key=lambda item:item[0].upper()))+'\0\0')
            command=C.create_unicode_buffer(subprocess.list2cmdline(self.args))
            info=_ProcessInfo()
            # EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW
            _check(k.CreateProcessW(self.args[0],command,None,None,True,0x8080400,
                env_block,str(cwd) if cwd else None,C.byref(startup),C.byref(info)))
            self._process=info.process;self.pid=int(info.pid)
            k.CloseHandle(info.thread)
        except BaseException:
            self.close()
            raise
        finally:
            if attributes is not None:k.DeleteProcThreadAttributeList(attributes)
            for handle in duplicates:k.CloseHandle(handle)

    def poll(self):
        if self.returncode is not None or self._process is None:return self.returncode
        state=self._kernel.WaitForSingleObject(self._process,0)
        if state==258:return None
        if state!=0:raise C.WinError(C.get_last_error())
        value=W.DWORD();_check(self._kernel.GetExitCodeProcess(self._process,C.byref(value)))
        self.returncode=int(value.value)
        return self.returncode

    def wait(self,timeout=None):
        if self.returncode is not None:return self.returncode
        millis=0xFFFFFFFF if timeout is None else min(0xFFFFFFFE,max(0,math.ceil(timeout*1000)))
        state=self._kernel.WaitForSingleObject(self._process,millis)
        if state==258:raise subprocess.TimeoutExpired(self.args,timeout)
        if state!=0:raise C.WinError(C.get_last_error())
        return self.poll()

    def terminate(self):
        if self.poll() is None:
            if not self._kernel.TerminateProcess(self._process,1) and self.poll() is None:
                raise C.WinError(C.get_last_error())

    kill=terminate

    def accounting(self):
        info=_Accounting()
        _check(self._kernel.QueryInformationJobObject(self._job,1,C.byref(info),C.sizeof(info),None))
        return dict(total_processes=int(info.total_processes),active_processes=int(info.active_processes))

    def close(self):
        if self._job is None:return None
        try:
            before=self.accounting()
            if before['active_processes']:
                _check(self._kernel.TerminateJobObject(self._job,1))
            deadline=time.monotonic()+5.
            while (after:=self.accounting())['active_processes']:
                if time.monotonic()>=deadline:raise TimeoutError('owned job processes did not terminate')
                time.sleep(.02)
            self.poll()
            return dict(before=before,after=after)
        finally:
            self._kernel.CloseHandle(self._job);self._job=None
            if self._process is not None:
                self._kernel.CloseHandle(self._process);self._process=None
