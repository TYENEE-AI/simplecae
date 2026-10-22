import json,os,signal,subprocess,sys,time
from pathlib import Path
from simplecae.execution import worker_group_options
from simplecae.process_lock import alive


def test_deadline_stops_worker_even_when_stop_evidence_cannot_be_written(tmp_path):
    record=tmp_path/'worker-ownership.json'
    code="""
import os,sys,time,json
from pathlib import Path
from simplecae.process_lock import identity,worker_guard
import simplecae.workbench as wb
path=Path(sys.argv[1])
path.write_text(json.dumps({'owner':identity(os.getppid()),'deadline_monotonic':time.monotonic()+1.}))
original=wb.atomic_json
def fail_stop_evidence(path,value):
    if value.get('stop_reason'):raise OSError('injected full disk on stop evidence')
    return original(path,value)
wb.atomic_json=fail_stop_evidence
os.environ['SIMPLECAE_WORKER_OWNERSHIP']=str(path)
worker_guard()
time.sleep(120)
"""
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'scripts'))
    process=subprocess.Popen([sys.executable,'-c',code,str(record)],env=env,**worker_group_options())
    try:
        process.wait(timeout=15)
        assert process.returncode==(130 if os.name=='nt' else -signal.SIGKILL)
        assert json.loads(record.read_text()).get('descendant_scope')
    finally:
        if process.poll() is None:process.kill();process.wait()


def test_hard_killed_worker_cannot_leave_native_descendants(tmp_path):
    worker=tmp_path/'worker.json';child=tmp_path/'child.json'
    code="from pathlib import Path; import sys,json,time,subprocess; from simplecae.process_lock import identity; from simplecae.process_scope import protect_worker\nowner=identity(); scope=protect_worker(owner); Path(sys.argv[1]).write_text(json.dumps(owner)); subprocess.Popen([sys.executable,'-c',\"import sys,time,json; from pathlib import Path; from simplecae.process_lock import identity; Path(sys.argv[1]).write_text(json.dumps(identity())); time.sleep(120)\",sys.argv[2]]); time.sleep(120)"
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'scripts'))
    process=subprocess.Popen([sys.executable,'-c',code,str(worker),str(child)],env=env,**worker_group_options())
    try:
        deadline=time.monotonic()+30
        while not child.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.05)
        assert child.exists(),'Worker descendant guard failed to initialize'
        owner=json.loads(worker.read_text());descendant=json.loads(child.read_text())
        assert alive(owner) and alive(descendant)
        os.kill(owner['pid'],signal.SIGTERM if os.name=='nt' else signal.SIGKILL)
        deadline=time.monotonic()+10
        while alive(descendant) and time.monotonic()<deadline:time.sleep(.05)
        assert not alive(descendant),'Native descendant outlived killed worker'
        process.wait(timeout=10)
    finally:
        if process.poll() is None:process.kill();process.wait()
        if child.exists():
            d=json.loads(child.read_text())
            if alive(d):os.kill(d['pid'],signal.SIGTERM)
