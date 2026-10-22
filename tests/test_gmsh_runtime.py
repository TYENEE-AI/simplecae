"""Real POSIX broken-pipe behavior, not Python's potentially stale signal cache."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name == 'nt', reason='POSIX SIGPIPE behavior')
@pytest.mark.parametrize('policy', ['ignore', 'custom'])
def test_native_session_preserves_caller_broken_pipe_behavior(policy):
    code = '''
import os,signal,sys
from simplecae.geometry import session
calls=[]
def handler(signum, frame): calls.append(signum)
selected=signal.SIG_IGN if sys.argv[1]=='ignore' else handler
signal.signal(signal.SIGPIPE, selected)
def check():
    r,w=os.pipe()
    os.close(r)
    try:
        try: os.write(w,b'x')
        except BrokenPipeError: pass
        else: raise AssertionError('Broken pipe was not reported')
    finally: os.close(w)
    assert signal.getsignal(signal.SIGPIPE)==selected
with session() as g:
    g.model.occ.addBox(0,0,0,1,1,1)
    g.model.occ.synchronize()
    assert len(g.model.getEntities(3))==1
    check()
check()
assert len(calls)==(0 if sys.argv[1]=='ignore' else 2),calls
print('Native geometry and caller pipe policy preserved')
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'scripts'))
    completed = subprocess.run([sys.executable, '-c', code, policy], env=env,
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
