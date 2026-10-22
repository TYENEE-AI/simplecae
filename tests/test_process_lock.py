import json
import os
import subprocess
import sys
import time
from pathlib import Path
import pytest
from simplecae.process_lock import identity,alive,mutation_lock


def test_lock_checks_actual_owner_and_never_steals(tmp_path):
    path=tmp_path/'task.lock'
    with mutation_lock(path,tmp_path):
        record=json.loads(path.read_text());assert alive(record['owner'])
        with pytest.raises(ValueError,match='busy'): 
            with mutation_lock(path,tmp_path):pass
    assert not path.exists()


def test_dead_process_lock_archived_and_recovered(tmp_path):
    path=tmp_path/'task.lock';ready=tmp_path/'ready'
    script="from pathlib import Path; from simplecae.process_lock import mutation_lock; import time\nwith mutation_lock(Path("+repr(str(path))+"),Path("+repr(str(tmp_path))+")):\n Path("+repr(str(ready))+").write_text('ready')\n time.sleep(60)"
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'scripts'))
    child=subprocess.Popen([sys.executable,'-c',script],env=env)
    try:
        deadline=time.monotonic()+10
        while not ready.exists() and time.monotonic()<deadline:time.sleep(.02)
        assert ready.exists()
        # Windows venv launchers can remain a separate parent process. Kill
        # the recorded lock owner, not merely its launcher (which leaves the
        # actual owner alive and must correctly prevent lock recovery).
        owner=json.loads(path.read_text())['owner']
        os.kill(owner['pid'], __import__('signal').SIGTERM)
        child.wait(timeout=10)
        with mutation_lock(path,tmp_path):assert alive(json.loads(path.read_text())['owner'])
        assert len(list((tmp_path/'interrupted-locks').glob('*.json')))==1
    finally:
        if child.poll() is None:child.kill();child.wait()


def test_legacy_unknown_lock_stays_intact(tmp_path):
    path=tmp_path/'task.lock';path.write_text('old unknown lock')
    with pytest.raises(ValueError,match='Legacy/unknown'):
        with mutation_lock(path,tmp_path):pass
    assert path.read_text()=='old unknown lock'


def test_recovery_cancels_unclaimed_launch_before_late_worker_can_start(tmp_path,monkeypatch):
    import simplecae.process_lock as locks
    owner=identity();dead=dict(owner,pid=987654321)
    monkeypatch.setattr(locks,'alive',lambda value:value!=dead)
    path=tmp_path/'task.lock';path.write_text(json.dumps({'schema':'simplecae-process-lock/1','owner':dead,'workspace':str(tmp_path),'token':'old'}))
    record=tmp_path/'runs/attempt/worker-ownership.json';record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'owner':dead,'worker':None,'deadline_monotonic':time.monotonic()+1000}))
    with mutation_lock(path,tmp_path):pass
    assert json.loads(record.read_text())['cancelled_before_start']
    monkeypatch.setenv('SIMPLECAE_WORKER_OWNERSHIP',str(record))
    with pytest.raises(SystemExit,match='cancelled'):locks.worker_guard()
