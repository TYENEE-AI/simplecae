"""Installation recovery must not turn native failures into pip retry loops."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('failure,expected', [
    ('python', 1), ('native_os', 2), ('native_import', 2), ('native_init', 2),
    ('metadata', 3), ('unknown', 3), ('ready', 0),
])
def test_readiness_classifies_cause_without_installing(monkeypatch, tmp_path, failure, expected, capsys):
    module = load('runtime_ready')
    from simplecae import gmsh_runtime
    def check(_):
        if failure == 'python': raise module.metadata.PackageNotFoundError('gmsh')
        if failure == 'metadata': raise ValueError('invalid metadata')
        if failure == 'unknown': raise RuntimeError('inspection failure')
        return True
    def native():
        if failure == 'native_os': raise OSError('libGLU.so.1 missing')
        if failure == 'native_import': raise ImportError('DLL load failed')
        if failure == 'native_init': raise RuntimeError('native initialize failed')
    monkeypatch.setattr(module, 'ready', check)
    monkeypatch.setattr(gmsh_runtime, 'initialize', native)
    monkeypatch.setattr(gmsh_runtime, 'finalize', lambda: None)
    assert module.main(tmp_path) == expected
    message = capsys.readouterr().out
    if expected == 2: assert 'not pip' in message
    if expected == 3: assert 'inspection failed' in message


@pytest.mark.parametrize('before,after,expected_pip,success', [
    (0, 0, False, True), (1, 0, True, True), (2, 2, False, False),
    (3, 3, False, False), (99, 99, False, False), (1, 2, True, False),
])
def test_real_bootstrap_routes_readiness_status(tmp_path, before, after, expected_pip, success):
    root=tmp_path/'skill space'; scripts=root/'scripts'; scripts.mkdir(parents=True)
    envdir=root/('.venv' if os.name=='nt' else '.venv-linux')
    subprocess.run([sys.executable,'-m','venv','--without-pip',str(envdir)],check=True)
    bootstrap='bootstrap.ps1' if os.name=='nt' else 'bootstrap.sh'
    shutil.copy2(ROOT/'scripts'/bootstrap,scripts/bootstrap)
    # Fake pip records an invocation; it never downloads anything. Readiness
    # changes only after that invocation, testing the real shell's branching.
    (root/'pip.py').write_text("from pathlib import Path\np=Path(__file__).parent/'pip-called'\np.write_text('called')\n",encoding='utf-8')
    (scripts/'runtime_ready.py').write_text(
        f"from pathlib import Path\np=Path(__file__).resolve().parents[1]\nraise SystemExit({after} if (p/'pip-called').exists() else {before})\n",encoding='utf-8')
    package=scripts/'simplecae';package.mkdir()
    (package/'__init__.py').write_text('',encoding='utf-8')
    solver=root/'ccx';solver.write_text('fixture',encoding='utf-8')
    (package/'solver.py').write_text(f'def find_ccx(*args): return {str(solver)!r}\n',encoding='utf-8')
    (scripts/'simplecae_cli.py').write_text("from pathlib import Path\n(Path(__file__).resolve().parents[1]/'doctor-called').write_text('called')\n",encoding='utf-8')
    if os.name=='nt':
        command=[shutil.which('powershell.exe'),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(scripts/bootstrap),'-Ccx',str(solver)]
    else:
        command=['bash',str(scripts/bootstrap),'--ccx',str(solver)]
    completed=subprocess.run(command,cwd=root,env=dict(os.environ,PYTHONPATH=str(scripts),PIP_NO_INDEX='1'),
                             capture_output=True,text=True,timeout=30)
    assert (completed.returncode==0) is success, completed.stdout+completed.stderr
    assert (root/'pip-called').exists() is expected_pip
    assert (root/'doctor-called').exists() is success
    assert not (root/'.tools/CalculiX-2.23.0-win-x64.zip').exists()


@pytest.mark.parametrize('delay,args,code,banner,expected', [
    (2.5, [], 0, 'This is Version 2.23', 0),
    (0, [], 201, 'This is Version 2.23', 0),
    (1, ['--timeout','.1'], 0, 'This is Version 2.23', 2),
    (0, [], 0, 'loader error', 2),
    (0, [], 1, 'This is Version 2.23', 2),
])
def test_addon_probe_real_child_deadline_and_banner(monkeypatch, delay, args, code, banner, expected, capsys):
    module=load('addon_probe')
    from simplecae import gmsh_runtime, solver
    monkeypatch.setattr(gmsh_runtime,'initialize',lambda:None)
    monkeypatch.setattr(gmsh_runtime,'finalize',lambda:None)
    monkeypatch.setattr(solver,'find_ccx',lambda:Path(sys.executable))
    real_run=subprocess.run
    def run(command,**kwargs):
        return real_run([sys.executable,'-c',f'import time,sys; time.sleep({delay}); print({banner!r}); sys.exit({code})'],**kwargs)
    monkeypatch.setattr(module.subprocess,'run',run)
    assert module.main(args)==expected
    report=json.loads(capsys.readouterr().out)
    assert report['status']==('ready' if expected==0 else 'unavailable')


@pytest.mark.parametrize('value',['0','-1','nan','inf'])
def test_addon_probe_rejects_invalid_deadline(value):
    with pytest.raises(SystemExit) as exc: load('addon_probe').main(['--timeout',value])
    assert exc.value.code==2
