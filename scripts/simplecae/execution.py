"""Small resource observations and empirical cost estimates, never engineering gates."""
import math
import os
import platform
import signal
import subprocess


def worker_group_options():
    return ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt" else {"start_new_session": True})


def stop_worker(process):
    """Terminate the owned supervisor and native descendants, never unrelated jobs."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=15)


def run_owned_worker(command, *, timeout, **kwargs):
    """Unlike subprocess.run timeout cleanup, also stop nested solver processes."""
    process = subprocess.Popen(command, **kwargs, **worker_group_options())
    try:
        process.wait(timeout=timeout)
    except BaseException:
        stop_worker(process)
        raise
    return subprocess.CompletedProcess(command, process.returncode)


def processor_label():
    """Optional CPU observation without spawning uname/other helper programs."""
    if os.name == 'nt':
        return os.environ.get('PROCESSOR_IDENTIFIER', '')
    try:
        with open('/proc/cpuinfo', encoding='utf-8', errors='replace') as stream:
            for line in stream:
                key, separator, value = line.partition(':')
                if separator and key.strip().lower() in ('model name', 'hardware'):
                    return value.strip()
    except OSError:
        pass
    return ''


def hardware_snapshot():
    result={'logical_cpus':os.cpu_count(),'platform':platform.system(),
            'available_memory_bytes':None,'total_memory_bytes':None,
            'processor':processor_label(),
            'meaning':'Snapshot only. Logical CPUs are not a recommended thread count; available memory is not a solver memory prediction.'}
    try:
        if os.name=='nt':
            import ctypes
            class Memory(ctypes.Structure):
                _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[
                    (n,ctypes.c_ulonglong) for n in ('total','available','page_total','page_available',
                                                   'virtual_total','virtual_available','extended')]
            info=Memory();info.length=ctypes.sizeof(info)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):
                raise OSError('GlobalMemoryStatusEx failed')
            result.update(available_memory_bytes=info.available,total_memory_bytes=info.total)
        elif os.path.isfile('/proc/meminfo'):
            with open('/proc/meminfo') as stream:
                values={line.split(':')[0]:int(line.split()[1])*1024 for line in stream}
            result.update(available_memory_bytes=values.get('MemAvailable'),total_memory_bytes=values.get('MemTotal'))
    except (OSError,ValueError,AttributeError) as exc:
        result['observation_error']=str(exc)
    return result


def cost_projection(mesh, levels):
    """Use timings from this same run; predictions never terminate or approve a solve."""
    observations=[]
    for level in levels:
        seconds=level.get('solver',{}).get('elapsed_seconds')
        nodes=level.get('mesh',{}).get('node_count')
        if isinstance(seconds,(int,float)) and math.isfinite(seconds) and seconds>0 and nodes:
            observations.append({'nodes':nodes,'seconds':seconds})
    estimate=None;exponent=None
    if observations:
        exponent=2.
        if len(observations)>=2 and observations[-1]['nodes']>observations[-2]['nodes']:
            exponent=max(1.,min(3.,math.log(observations[-1]['seconds']/observations[-2]['seconds'])/
                                      math.log(observations[-1]['nodes']/observations[-2]['nodes'])))
        last=observations[-1]
        estimate=last['seconds']*(mesh['node_count']/last['nodes'])**exponent
    return {'node_count':mesh['node_count'],'element_count':mesh['element_count'],
            'observations':observations,'estimated_native_seconds':estimate,'scaling_exponent':exponent,
            'estimate_is_guarantee':False,
            'meaning':'Same-run node/time extrapolation only, exponent bounded to 1..3 (one sample uses 2). Contact active sets, fill, cutbacks and machine load may dominate. No early stop or mesh/criterion change based on this estimate.'}
