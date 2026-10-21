import pytest
from simplecae.solver import execution_threads

@pytest.mark.parametrize('raw',['0','-1','1.5','junk','9'])
def test_invalid_resource_request_is_not_silently_reinterpreted(monkeypatch,raw):
    monkeypatch.setattr('simplecae.solver.os.cpu_count',lambda:8)
    monkeypatch.setenv('SIMPLECAE_SOLVER_THREADS',raw)
    with pytest.raises(ValueError):execution_threads()

def test_default_is_serial_and_explicit_request_is_preserved(monkeypatch):
    monkeypatch.setattr('simplecae.solver.os.cpu_count',lambda:8)
    monkeypatch.delenv('SIMPLECAE_SOLVER_THREADS',raising=False)
    assert execution_threads()==1
    monkeypatch.setenv('SIMPLECAE_SOLVER_THREADS','4')
    assert execution_threads()==4

def test_cache_never_reuses_a_different_parallel_execution(monkeypatch,tmp_path):
    from simplecae.cache import cache_key
    from simplecae.case import load_case
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    c=load_case(root/'examples/cantilever.case.json')
    binary=tmp_path/'solver.exe';binary.write_bytes(b'not executed')
    monkeypatch.setattr('simplecae.solver.os.cpu_count',lambda:8)
    monkeypatch.setenv('SIMPLECAE_SOLVER_THREADS','1');a=cache_key(c,binary)
    monkeypatch.setenv('SIMPLECAE_SOLVER_THREADS','4');b=cache_key(c,binary)
    assert a!=b


def test_native_log_is_observable_during_run_and_retained_on_timeout(monkeypatch,tmp_path):
    import subprocess
    from simplecae.solver import execute
    binary=tmp_path/'ccx.exe';binary.write_bytes(b'not executed')
    inp=tmp_path/'job.inp';inp.write_text('dummy')
    monkeypatch.setenv('SIMPLECAE_SOLVER_THREADS','1')
    monkeypatch.setenv('CCX_NPROC_STIFFNESS','99')
    def timed_out(*args,**kwargs):
        assert kwargs['env']['CCX_NPROC_STIFFNESS']=='1'
        kwargs['stdout'].write('iteration 4\nno convergence\n');kwargs['stdout'].flush()
        assert 'iteration 4' in inp.with_suffix('.solver.log').read_text()
        assert kwargs['stderr']==subprocess.STDOUT
        raise subprocess.TimeoutExpired(args[0],1)
    monkeypatch.setattr('simplecae.solver.subprocess.run',timed_out)
    with pytest.raises(RuntimeError,match='exceeded'):execute(binary,inp,timeout=1)
    log=inp.with_suffix('.solver.log').read_text()
    assert 'iteration 4' in log and 'no convergence' in log and 'TIMEOUT' in log
