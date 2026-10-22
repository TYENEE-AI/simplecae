"""First-use behavior, not a substitute for numerical verification."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def shell_root(tmp_path):
    if os.name!='nt':
        pytest.skip('Windows PowerShell integration requires Windows paths/runtime, not the WSL interoperability shim')
    ps = shutil.which('powershell.exe')
    if not ps:
        pytest.skip('Windows PowerShell integration')
    root = tmp_path / 'skill space'
    (root / 'scripts/simplecae').mkdir(parents=True)
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(root / '.venv')], check=True)
    for name in ('bootstrap.ps1', 'start_viewer.ps1'):
        shutil.copy2(ROOT / 'scripts' / name, root / 'scripts' / name)
    shutil.copy2(ROOT / 'scripts/download_verified.py', root / 'scripts/download_verified.py')
    # A stdlib-only runtime double records the launcher's calls. No solver/browser/network.
    (root / 'scripts/simplecae_cli.py').write_text('''
from pathlib import Path
import json,sys
root=Path(__file__).resolve().parents[1]
with (root/'calls.jsonl').open('a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
if '--out' in sys.argv:
 p=Path(sys.argv[sys.argv.index('--out')+1]);p.mkdir(parents=True)
 (p/'viewer.json').write_text('{}')
''', encoding='utf8')
    return ps, root


@pytest.mark.parametrize('incomplete', [False, True])
def test_viewer_opens_without_implicit_solve_or_overwriting_incomplete_output(shell_root, incomplete):
    ps, root = shell_root
    if incomplete:
        for folder in ('outputs/viewer-demo', 'outputs/first-001'):
            p = root / folder; p.mkdir(parents=True); (p / 'keep.txt').write_text('retained')
    result = subprocess.run([ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             str(root / 'scripts/start_viewer.ps1')], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
    assert len(calls) == 2 and all(call[0] == 'view' for call in calls)
    assert calls[0][1] == '--out' and '--serve' in calls[1]
    if incomplete:
        assert (root / 'outputs/first-001/keep.txt').read_text() == 'retained'
        assert (root / 'outputs/viewer-demo/keep.txt').read_text() == 'retained'


def test_bootstrap_reuses_runtime_and_configured_solver_without_system_python_or_pip(shell_root):
    ps, root = shell_root
    (root / 'scripts/runtime_ready.py').write_text('raise SystemExit(0)')
    (root / 'scripts/simplecae/__init__.py').write_text('')
    solver = root / 'custom-ccx.exe'; solver.write_text('fixture')
    (root / 'scripts/simplecae/solver.py').write_text(f'def find_ccx(): return {str(solver)!r}')
    (root / '.tools').mkdir()
    (root / '.tools/runtime.json').write_text('{"ccx_by_platform":{"Linux":"keep-linux"},"user_setting":42}')
    env = dict(os.environ, PIP_NO_INDEX='1')
    result = subprocess.run([ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             str(root / 'scripts/bootstrap.ps1'), '-Python', 'no-system-python'],
                            capture_output=True, text=True, timeout=30, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Reusing the existing runtime' in result.stdout
    # The environment contains no pip: a redundant dependency install would fail.
    calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
    assert calls == [['doctor', '--ccx', str(solver)]]
    config = json.loads((root / '.tools/runtime.json').read_text(encoding='utf-8-sig'))
    assert config['ccx_by_platform'] == {'Linux':'keep-linux', 'Windows':str(solver)}
    assert config['user_setting'] == 42


def test_bootstrap_rejects_bad_configured_solver_without_silent_download(shell_root):
    ps, root = shell_root
    (root / 'scripts/runtime_ready.py').write_text('raise SystemExit(0)')
    (root / 'scripts/simplecae/__init__.py').write_text('')
    (root / 'scripts/simplecae/solver.py').write_text('def find_ccx(): raise FileNotFoundError("missing")')
    (root / '.tools').mkdir(); (root / '.tools/runtime.json').write_text('{"ccx":"missing"}')
    result = subprocess.run([ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             str(root / 'scripts/bootstrap.ps1')], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'Configured solver unavailable' in result.stderr
    assert not (root / 'calls.jsonl').exists()
    assert not (root / '.tools/CalculiX-2.23.0-win-x64.zip').exists()


@pytest.mark.parametrize('corrupt', [False, True])
def test_bootstrap_cached_archive_does_not_depend_on_shell_archive_modules(shell_root, corrupt):
    import hashlib
    import zipfile
    ps, root = shell_root
    (root / 'scripts/runtime_ready.py').write_text('raise SystemExit(0)')
    (root / 'scripts/simplecae/__init__.py').write_text('')
    (root / 'scripts/simplecae/solver.py').write_text('def find_ccx(): raise FileNotFoundError("missing")')
    (root / '.tools').mkdir()
    archive = root / '.tools/CalculiX-2.23.0-win-x64.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('CalculiX-2.23.0-win-x64/bin/ccx.exe', b'test executable placeholder; doctor is doubled')
    script = root / 'scripts/bootstrap.ps1'
    script.write_text(script.read_text().replace(
        '79a674fdee735a22720bbd12bb9ccbadad1e8c8ad5b1de74e1c62f8808b2d395',
        hashlib.sha256(archive.read_bytes()).hexdigest()), encoding='utf-8')
    if corrupt:
        with archive.open('ab') as stream:
            stream.write(b'changed after pinning')
    wrapper = root / 'module-unavailable.ps1'
    wrapper.write_text("function Get-FileHash { throw 'Unavailable in this host' }\n"
                       "function Expand-Archive { throw 'Unavailable in this host' }\n"
                       "& (Join-Path $PSScriptRoot 'scripts/bootstrap.ps1')\n", encoding='utf-8')
    env = dict(os.environ, PIP_NO_INDEX='1')
    env.pop('SIMPLECAE_CCX', None)
    result = subprocess.run([ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(wrapper)],
                            capture_output=True, text=True, timeout=30, env=env)
    solver = root / '.tools/calculix-2.23/CalculiX-2.23.0-win-x64/bin/ccx.exe'
    if corrupt:
        assert result.returncode != 0 and 'SHA-256 mismatch' in result.stderr
        assert not solver.exists() and not (root / 'calls.jsonl').exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert solver.is_file()
        calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
        assert calls == [['doctor', '--ccx', str(solver)]]


@pytest.mark.parametrize('change', ['crlf', 'content', 'missing'])
def test_license_audit_tolerates_line_endings_but_rejects_content_changes(tmp_path, change):
    module = load('audit_dependencies')
    (tmp_path / 'licenses').mkdir()
    data = b'License terms\nCopyright holder\n'
    import hashlib
    item = {'notice_path':'licenses/NOTICE', 'sha256':hashlib.sha256(data).hexdigest(),
            'text_sha256_lf':module.notice_text_hash(data)}
    (tmp_path / 'licenses/dependency-inventory.json').write_text(json.dumps(
        {'dependencies':[{'name':'fixture','version':'1','notices':[item]}]}))
    (tmp_path / 'requirements-lock.txt').write_text('fixture==1\n')
    (tmp_path / 'LICENSE').write_text('GNU GENERAL PUBLIC LICENSE')
    if change != 'missing':
        (tmp_path / 'licenses/NOTICE').write_bytes(data.replace(b'\n', b'\r\n') if change=='crlf' else b'changed terms\n')
    if change == 'crlf':
        assert module.check(tmp_path)['passed']
    else:
        with pytest.raises((ValueError, FileNotFoundError)): module.check(tmp_path)


def test_bootstrap_interrupted_http_download_can_retry_without_removing_evidence(shell_root):
    import hashlib
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import io
    import threading
    import zipfile
    ps, root = shell_root
    (root / 'scripts/runtime_ready.py').write_text('raise SystemExit(0)')
    (root / 'scripts/simplecae/__init__.py').write_text('')
    (root / 'scripts/simplecae/solver.py').write_text('def find_ccx(): raise FileNotFoundError("missing")')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('CalculiX-2.23.0-win-x64/bin/ccx.exe', b'launcher fixture, not a native solver')
    payload = stream.getvalue()
    interrupted = [True]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload[:50] if interrupted[0] else payload)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    script = root / 'scripts/bootstrap.ps1'
    text = script.read_text(encoding='utf-8').replace(
        '79a674fdee735a22720bbd12bb9ccbadad1e8c8ad5b1de74e1c62f8808b2d395', hashlib.sha256(payload).hexdigest())
    import re
    text = re.sub(r"\$simplecaeUrl = '[^']+'", f"$simplecaeUrl = 'http://127.0.0.1:{server.server_port}/archive'", text)
    script.write_text(text, encoding='utf-8')
    env = dict(os.environ, PIP_NO_INDEX='1')
    env.pop('SIMPLECAE_CCX', None)
    command = [ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-DownloadTimeoutSeconds', '10']
    archive = root / '.tools/CalculiX-2.23.0-win-x64.zip'
    try:
        failed = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env)
        assert failed.returncode != 0 and 'retained' in failed.stderr
        assert not archive.exists() and not (root / 'calls.jsonl').exists()
        fragments = list((root / '.tools').glob('*.partial'))
        assert len(fragments) == 1
        original = fragments[0].read_bytes()
        interrupted[0] = False
        recovered = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env)
        assert recovered.returncode == 0, recovered.stdout + recovered.stderr
        assert archive.read_bytes() == payload
        assert fragments[0].read_bytes() == original
        assert (root / '.tools/calculix-2.23/CalculiX-2.23.0-win-x64/bin/ccx.exe').is_file()
        assert len((root / 'calls.jsonl').read_text(encoding='utf-8').splitlines()) == 1
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.parametrize('problem', ['version', 'missing'])
def test_runtime_reuse_rejects_incompatible_or_missing_dependency(tmp_path, monkeypatch, problem):
    module = load('runtime_ready')
    (tmp_path / 'pyproject.toml').write_text('[project]\nrequires-python=">=3.11"\ndependencies=["numpy>=2,<3"]')
    def version(_):
        if problem == 'missing':raise module.metadata.PackageNotFoundError('numpy')
        return '1.26.0'
    monkeypatch.setattr(module.metadata, 'version', version)
    if problem == 'version':assert module.ready(tmp_path) is False
    else:
        with pytest.raises(module.metadata.PackageNotFoundError):module.ready(tmp_path)


@pytest.mark.parametrize('origin_matches', [True, False])
def test_runtime_reuse_checks_actual_source_not_stale_version_label(tmp_path, monkeypatch, origin_matches):
    from types import SimpleNamespace
    from simplecae import gmsh_runtime
    module = load('runtime_ready')
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="simplecae-toolkit"\nversion="9.9"\nrequires-python=">=3.11"\ndependencies=["numpy>=2,<3"]')
    monkeypatch.setattr(module.metadata, 'version', lambda name: '0.1' if name=='simplecae-toolkit' else '2.0')
    origin = tmp_path if origin_matches else tmp_path / 'other-source'
    dist = SimpleNamespace(metadata={'Name':'simplecae-toolkit'}, read_text=lambda _: json.dumps(
        {'url':origin.as_uri(), 'dir_info':{'editable':True}}))
    monkeypatch.setattr(module.metadata, 'distributions', lambda **kwargs: [dist])
    monkeypatch.setitem(sys.modules, 'simplecae', SimpleNamespace(
        __file__=str(tmp_path / 'scripts/simplecae/__init__.py'), gmsh_runtime=gmsh_runtime))
    monkeypatch.setitem(sys.modules, 'gmsh', SimpleNamespace(initialize=lambda:None, finalize=lambda:None))
    assert module.ready(tmp_path) is origin_matches


def test_shell_entrypoints_preserve_posix_line_endings():
    scripts = list((ROOT / "scripts").rglob("*.sh"))
    assert scripts
    for script in scripts:
        assert b"\r" not in script.read_bytes(), f"Shell entrypoint must use LF: {script}"
