"""OS-released mutation locks with durable interruption/worker evidence."""
from contextlib import contextmanager
from pathlib import Path
import ctypes
import json
import os
import platform
import secrets
import socket
import time


def identity(pid=None):
    pid=os.getpid() if pid is None else pid
    if os.name=='nt':
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            if ctypes.get_last_error()==87:return None
            raise OSError('Process identity is unavailable; cannot prove owner exit')
        try:
            values=[wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle,*[ctypes.byref(v) for v in values]):raise OSError('Cannot read process birth time')
            created=(values[0].dwHighDateTime<<32)|values[0].dwLowDateTime
            if values[1].dwHighDateTime or values[1].dwLowDateTime:return None
        finally:kernel.CloseHandle(handle)
    elif platform.system()=='Linux':
        try:
            stat=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
            if stat[0]=='Z':return None
            created=Path('/proc/sys/kernel/random/boot_id').read_text().strip()+':'+stat[19]
        except FileNotFoundError:return None
    else:
        import subprocess
        probe=subprocess.run(['ps','-p',str(pid),'-o','lstart='],capture_output=True,text=True,timeout=5)
        if probe.returncode==1:return None
        if probe.returncode or not probe.stdout.strip():raise OSError('Cannot establish process identity')
        created=probe.stdout.strip()
    return {'pid':pid,'created':created,'host':socket.gethostname(),'platform':platform.system()}


def alive(owner):
    if owner.get('host')!=socket.gethostname() or owner.get('platform')!=platform.system():
        raise ValueError('Lock belongs to another host/platform; confirm its worker stopped before recovery')
    return identity(owner['pid'])==owner


@contextmanager
def mutation_lock(path, workspace):
    path=Path(path);workspace=Path(workspace).resolve()
    guard=path.with_name('.'+path.name+'.guard')
    guard.parent.mkdir(parents=True,exist_ok=True)
    with guard.open('a+b') as stream:
        stream.seek(0,2)
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise ValueError('Task/budget busy/interrupted: active mutation owns '+str(path)) from None
        token=secrets.token_hex(12)
        try:
            if path.exists():
                try:old=json.loads(path.read_text(encoding='utf-8'))
                except (ValueError,UnicodeError):raise ValueError('Legacy/unknown lock cannot be recovered automatically: '+str(path)) from None
                if old.get('schema')!='simplecae-process-lock/1' or alive(old['owner']):
                    raise ValueError('Task/budget lock owner is active or unknown')
                old_workspace=Path(old['workspace']).resolve()
                for record in (old_workspace/'runs').glob('*/worker-ownership.json'):
                    value=json.loads(record.read_text(encoding='utf-8'))
                    if value.get('owner')!=old['owner']:continue
                    # Serialize startup and recovery. A late-launching worker
                    # must see cancellation before it can start native tools.
                    with mutation_lock(record.with_suffix('.launch.lock'),record.parent):
                        value=json.loads(record.read_text(encoding='utf-8'))
                        if value.get('worker') and alive(value['worker']):
                            raise ValueError('Interrupted task worker is still running; wait for its owner/deadline guard before retrying: '+str(record))
                        if not value.get('worker'):
                            from .workbench import atomic_json
                            value['cancelled_before_start']=True;atomic_json(record,value)
                recovery=path.parent/'interrupted-locks';recovery.mkdir(exist_ok=True)
                path.rename(recovery/(path.name+'.'+old['token']+'.json'))
            from .workbench import atomic_json
            atomic_json(path,{'schema':'simplecae-process-lock/1','token':token,'owner':identity(),
                              'workspace':str(workspace),'created_at_epoch':time.time()})
            try:yield
            finally:
                if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('token')==token:path.unlink()
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def worker_guard():
    """Watch only the owned process group; survive supervisor hard termination."""
    raw=os.environ.pop('SIMPLECAE_WORKER_OWNERSHIP',None)
    if not raw:return
    import threading
    import signal
    import sys
    from .workbench import atomic_json
    path=Path(raw)
    with mutation_lock(path.with_suffix('.launch.lock'),path.parent):
        record=json.loads(path.read_text(encoding='utf-8'))
        if record.get('cancelled_before_start') or not alive(record['owner']):
            raise SystemExit('Worker launch cancelled before native work: supervisor exited or task recovered')
        record['worker']=identity()
        from .process_scope import protect_worker
        record['descendant_scope']=protect_worker(record['worker'])
        atomic_json(path,record)
    def watch():
        while True:
            try:stop=not alive(record['owner']) or time.monotonic()>=record['deadline_monotonic']
            except (OSError,ValueError):stop=True
            if stop:
                record['stop_reason']='supervisor_exit_or_deadline'
                try:
                    atomic_json(path,record)
                    print('Owned worker stopped: supervisor exited or its total deadline expired.',file=sys.stderr,flush=True)
                finally:
                    # Evidence I/O (full disk, revoked access, broken stderr)
                    # must never prevent the actual budget/owner stop. Windows
                    # exit closes the worker's kill-on-close Job Object.
                    try:
                        if os.name!='nt' and os.getpgrp()==os.getpid():os.killpg(os.getpgrp(),signal.SIGKILL)
                    finally:os._exit(130)
            time.sleep(.25)
    threading.Thread(target=watch,daemon=True,name='simplecae-owner-guard').start()
