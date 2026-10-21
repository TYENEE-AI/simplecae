"""Actual worker phase costs; measurements are not solver-fit predictions."""
import os
import time
from pathlib import Path
from .case import write_json


def peak_process_memory():
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
                    ('peak_working_set','working_set','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
            c=Counters();c.cb=ctypes.sizeof(c)
            kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=wintypes.HANDLE
            fn=ctypes.windll.psapi.GetProcessMemoryInfo
            fn.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
            if fn(kernel.GetCurrentProcess(),ctypes.byref(c),c.cb):return int(c.peak_working_set)
        else:
            import resource
            value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            import sys
            return int(value if sys.platform=='darwin' else value*1024)
    except (OSError,ImportError,AttributeError): pass
    return None


class Observation:
    def __init__(self,out,progress=None):
        self.out=Path(out);self.progress=progress;self.started=self.previous=time.monotonic()
        self.cpu=time.process_time();self.stage='input_validation';self.phases=[]
    def mark(self,stage,**context):
        stamp=time.monotonic()
        self.phases.append({'stage':self.stage,'wall_seconds':stamp-self.previous})
        self.previous=stamp;self.stage=stage
    def event(self,event):
        self.mark(event.get('stage','analysis'))
        if self.progress:self.progress(event)
    def finish(self,completed):
        self.mark('finished')
        if not self.out.is_dir():return
        write_json(self.out/'execution-observation.json',{
            'schema_version':'simplecae-execution-observation-1','completed':completed,
            'total_wall_seconds':time.monotonic()-self.started,'worker_cpu_seconds':time.process_time()-self.cpu,
            'peak_worker_resident_bytes':peak_process_memory(),'phases':self.phases,
            'native_children_peak_bytes':None,
            'meaning':'Measured intervals between emitted stages, including reporting and retention. Parent high-water memory may include earlier calls; native child peak is unknown. No memory-fit or engineering acceptance claim.'})
