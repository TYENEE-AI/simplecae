import importlib.util,json
from pathlib import Path
import pytest


def installer():
    path=Path(__file__).resolve().parents[1]/'scripts/install_local.py'
    spec=importlib.util.spec_from_file_location('simplecae_local_install',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def source(tmp_path):
    root=tmp_path/'source';root.mkdir()
    for name,text in {'SKILL.md':'new skill','pyproject.toml':'[project]\nversion="1.2.0"','requirements-lock.txt':'locked','.gitignore':'outputs/','README.md':'first use'}.items():(root/name).write_text(text,encoding='utf-8')
    (root/'scripts/simplecae').mkdir(parents=True);(root/'scripts/simplecae/cli.py').write_text('new tool')
    return root


def test_install_preserves_runtime_and_results_with_recoverable_old_files(tmp_path,monkeypatch):
    m=installer();root=source(tmp_path);skills=tmp_path/'skills';dest=skills/'simplecae';dest.mkdir(parents=True)
    (dest/'SKILL.md').write_text('old skill');(dest/'scripts').mkdir();(dest/'scripts/old.py').write_text('old source')
    for folder in ('.venv','.tools','outputs'):
        (dest/folder).mkdir();(dest/folder/'keep').write_text('user runtime/results')
    (dest/'personal.txt').write_text('unmanaged user file')
    checked=[];monkeypatch.setattr(m,'check_qualification',lambda p,v:checked.append((p,v)))
    r=m.install(root,skills,tmp_path/'backups');backup=Path(r['backup'])
    assert (dest/'SKILL.md').read_text()=='new skill' and (backup/'SKILL.md').read_text()=='old skill'
    assert (backup/'scripts/old.py').read_text()=='old source' and not (dest/'scripts/old.py').exists()
    assert all((dest/folder/'keep').read_text()=='user runtime/results' for folder in ('.venv','.tools','outputs'))
    assert (dest/'personal.txt').read_text()=='unmanaged user file'
    assert checked==[]
    assert r['qualification']=='not requested (local installation)'
    assert 'files_sha256' not in json.loads((backup/'installation-backup.json').read_text())


def test_explicit_release_audit_cannot_touch_existing_skill_on_failure(tmp_path,monkeypatch):
    m=installer();root=source(tmp_path);skills=tmp_path/'skills';dest=skills/'simplecae';dest.mkdir(parents=True);(dest/'SKILL.md').write_text('original')
    def reject(*_):raise ValueError('qualification incomplete')
    monkeypatch.setattr(m,'check_qualification',reject)
    with pytest.raises(ValueError,match='qualification incomplete'):m.install(root,skills,tmp_path/'backups',verify_release=True)
    assert (dest/'SKILL.md').read_text()=='original' and not (tmp_path/'backups').exists()


def test_explicit_release_audit_verifies_source_once(tmp_path,monkeypatch):
    m=installer();root=source(tmp_path);checked=[]
    monkeypatch.setattr(m,'check_qualification',lambda p,v:checked.append((p,v)))
    result=m.install(root,tmp_path/'skills',tmp_path/'backups',verify_release=True)
    assert checked==[(root,'1.2.0')]
    assert result['qualification']=='source release verified'


def test_install_never_places_backup_inside_target_or_overwrites_source(tmp_path,monkeypatch):
    m=installer();root=source(tmp_path);monkeypatch.setattr(m,'check_qualification',lambda *_:None)
    with pytest.raises(ValueError,match='backup must be outside'):m.install(root,tmp_path/'skills',tmp_path/'skills/simplecae/backup')
    source_name=tmp_path/'simplecae';root.rename(source_name)
    with pytest.raises(ValueError,match='separate from the source'):m.install(source_name,tmp_path,tmp_path/'backup')


@pytest.mark.parametrize('receipt',['missing','stale','malformed'])
@pytest.mark.parametrize('development',[False,True])
def test_normal_install_needs_no_receipt_or_hashing(tmp_path,monkeypatch,receipt,development):
    m=installer();root=source(tmp_path)
    (root/'pyproject.toml').write_text('[project]\nversion="1.6.0.dev7"',encoding='utf8')
    if receipt!='missing':
        (root/'validation').mkdir()
        for name in ('public-release.json','development-validation.json'):
            (root/'validation'/name).write_text('{broken' if receipt=='malformed' else '{"source_files_sha256":{"old":"stale"}}')
    import simplecae.case,simplecae.release
    def forbidden(*args,**kwargs):raise AssertionError('ordinary install must not hash or qualify sources')
    monkeypatch.setattr(simplecae.case,'sha256',forbidden)
    monkeypatch.setattr(simplecae.release,'sha256',forbidden)
    monkeypatch.setattr(simplecae.release,'delivery_hashes',forbidden)
    monkeypatch.setattr(m,'check_qualification',forbidden)
    skills=tmp_path/'skills';dest=skills/'simplecae';dest.mkdir(parents=True)
    (dest/'SKILL.md').write_text('old')
    for folder in ('.venv','.tools','outputs'):
        (dest/folder).mkdir();(dest/folder/'keep').write_bytes(b'unchanged user data')
    r=m.install(root,skills,tmp_path/'backups',development=development)
    assert r['qualification']=='not requested (local installation)'
    assert all((dest/folder/'keep').read_bytes()==b'unchanged user data' for folder in ('.venv','.tools','outputs'))
    assert (Path(r['backup'])/'SKILL.md').read_text()=='old'
    (root/'scripts/simplecae/cli.py').write_bytes(b'edited checkout\r\n')
    m.install(root,skills,tmp_path/'backups-again',development=development)
    assert (dest/'scripts/simplecae/cli.py').read_bytes()==b'edited checkout\r\n'


@pytest.mark.parametrize('name',['Open_Viewer.cmd','打开Viewer.cmd'])
def test_install_includes_both_launcher_spellings(tmp_path,name):
    m=installer();root=source(tmp_path);(root/name).write_bytes(b'@echo off\r\n')
    result=m.install(root,tmp_path/'skills',tmp_path/'backups')
    assert (Path(result['installed'])/name).read_bytes()==b'@echo off\r\n'


def test_missing_cli_fails_before_touching_target(tmp_path):
    m=installer();root=source(tmp_path);(root/'scripts/simplecae/cli.py').unlink()
    dest=tmp_path/'skills/simplecae';dest.mkdir(parents=True);(dest/'SKILL.md').write_text('keep')
    with pytest.raises(ValueError,match='missing required skill file'):
        m.install(root,dest.parent,tmp_path/'backups')
    assert (dest/'SKILL.md').read_text()=='keep' and not (tmp_path/'backups').exists()


def test_copy_failure_keeps_recoverable_backup(tmp_path,monkeypatch):
    m=installer();root=source(tmp_path);dest=tmp_path/'skills/simplecae';dest.mkdir(parents=True)
    (dest/'SKILL.md').write_text('old skill')
    copy=m.shutil.copy2
    def fail_on_source(src,dst):
        if Path(src).is_relative_to(root):raise OSError('simulated disk full')
        return copy(src,dst)
    monkeypatch.setattr(m.shutil,'copy2',fail_on_source)
    with pytest.raises(OSError,match='disk full'):m.install(root,dest.parent,tmp_path/'backups')
    assert next((tmp_path/'backups').glob('*/SKILL.md')).read_text()=='old skill'


@pytest.mark.parametrize('escape',['source','target'])
def test_symlink_escape_rejected_before_any_install_changes(tmp_path,escape):
    m=installer();root=source(tmp_path);outside=tmp_path/'outside.py';outside.write_text('untouched')
    dest=tmp_path/'skills/simplecae';dest.mkdir(parents=True);(dest/'SKILL.md').write_text('old')
    link=(root if escape=='source' else dest)/'scripts/escape.py'
    link.parent.mkdir(parents=True,exist_ok=True)
    try:link.symlink_to(outside)
    except OSError:pytest.skip('symlink creation requires OS permission')
    with pytest.raises(ValueError,match='escapes'):
        m.install(root,dest.parent,tmp_path/'backups')
    assert outside.read_text()=='untouched' and (dest/'SKILL.md').read_text()=='old'
    assert not (tmp_path/'backups').exists()
