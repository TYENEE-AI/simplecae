"""Keep native descendants inside the lifetime of an owned analysis worker."""
import ctypes
import json
import os
import subprocess
import sys

_job_handle=None


def protect_worker(owner):
    """Called before the worker may launch native tools; fail closed on error."""
    global _job_handle
    if os.name=='nt':
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),
                ('flags',w.DWORD),('min_working_set',ctypes.c_size_t),('max_working_set',ctypes.c_size_t),
                ('active_limit',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(k,ctypes.c_ulonglong) for k in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];kernel.CreateJobObjectW.restype=w.HANDLE
        kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
        kernel.GetCurrentProcess.restype=w.HANDLE;kernel.CloseHandle.argtypes=[w.HANDLE]
        handle=kernel.CreateJobObjectW(None,None)
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        limits=Extended();limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle,kernel.GetCurrentProcess()):
            error=ctypes.get_last_error();kernel.CloseHandle(handle);raise ctypes.WinError(error)
        # Non-inheritable handle belongs to this worker only. Kernel closure on
        # normal exit or hard kill terminates every process in this nested job.
        _job_handle=handle
        return 'windows_kill_on_close_job'
    group=os.getpgrp()
    if group!=os.getpid():raise RuntimeError('Owned worker requires its own process group before native tools start')
    from pathlib import Path
    script='import sys; sys.path.insert(0,sys.argv[3]); from simplecae.process_scope import watch_group; import json; watch_group(json.loads(sys.argv[1]),int(sys.argv[2]))'
    # Same group; this small guardian survives a killed worker and reaps the
    # native descendants with itself. It never searches unrelated processes.
    process=subprocess.Popen([sys.executable,'-c',script,json.dumps(owner),str(group),str(Path(__file__).resolve().parents[1])],stdin=subprocess.DEVNULL,
                     stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    import select
    if not select.select([process.stdout],[],[],30)[0] or process.stdout.readline()!=b'READY\n':
        process.kill();process.wait();raise RuntimeError('Owned descendant guardian did not become ready; native work was not started')
    process.stdout.close()
    return 'posix_owned_group_guardian'


def watch_group(owner,group):
    import signal,time
    from .process_lock import alive
    if os.getpgrp()!=group:return
    print('READY',flush=True)
    while True:
        try:running=alive(owner)
        except (OSError,ValueError):running=False
        if not running:
            os.killpg(group,signal.SIGKILL)
        time.sleep(.1)
