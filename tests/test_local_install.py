import importlib.util,json
from pathlib import Path
import pytest


def installer():
    path=Path(__file__).resolve().parents[1]/'scripts/install_local.py'
    spec=importlib.util.spec_from_file_location('simplecae_local_install',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def source(tmp_path):
    root=tmp_path/'source';root.mkdir()
    for name,text in {'SKILL.md':'new skill','pyproject.toml':'[project]\nversion="1.2.0"','requirements-lock.txt':'locked','.gitignore':'outputs/','README.md':'first use'}.items():(root/name).write_text(text,encoding='utf-8')
    (root/'scripts').mkdir();(root/'scripts/tool.py').write_text('new tool')
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
    assert checked==[(root,'1.2.0'),(dest,'1.2.0')]


def test_incomplete_release_cannot_touch_existing_skill(tmp_path,monkeypatch):
    m=installer();root=source(tmp_path);skills=tmp_path/'skills';dest=skills/'simplecae';dest.mkdir(parents=True);(dest/'SKILL.md').write_text('original')
    def reject(*_):raise ValueError('qualification incomplete')
    monkeypatch.setattr(m,'check_qualification',reject)
    with pytest.raises(ValueError,match='qualification incomplete'):m.install(root,skills,tmp_path/'backups')
    assert (dest/'SKILL.md').read_text()=='original' and not (tmp_path/'backups').exists()


def test_install_never_places_backup_inside_target_or_overwrites_source(tmp_path,monkeypatch):
    m=installer();root=source(tmp_path);monkeypatch.setattr(m,'check_qualification',lambda *_:None)
    with pytest.raises(ValueError,match='backup must be outside'):m.install(root,tmp_path/'skills',tmp_path/'skills/simplecae/backup')
    source_name=tmp_path/'simplecae';root.rename(source_name)
    with pytest.raises(ValueError,match='separate from the source'):m.install(source_name,tmp_path,tmp_path/'backup')


def test_development_install_requires_current_snapshot_and_preserves_user_environment(tmp_path):
    m=installer();root=source(tmp_path)
    (root/'pyproject.toml').write_text('[project]\nversion="1.6.0.dev7"',encoding='utf8')
    (root/'validation').mkdir()
    from simplecae.case import write_json
    record={'passed':True,'toolkit_version':'1.6.0.dev7',
            'source_files_sha256':m.delivery_hashes(root,include_validation=False)}
    write_json(root/'validation/development-validation.json',record)
    skills=tmp_path/'skills';dest=skills/'simplecae';dest.mkdir(parents=True)
    (dest/'SKILL.md').write_text('old')
    for folder in ('.venv','.tools','outputs'):
        (dest/folder).mkdir();(dest/folder/'keep').write_bytes(b'unchanged user data')
    r=m.install(root,skills,tmp_path/'backups',development=True)
    assert r['qualification']=='source-bound development checkpoint'
    assert all((dest/folder/'keep').read_bytes()==b'unchanged user data' for folder in ('.venv','.tools','outputs'))
    assert (Path(r['backup'])/'SKILL.md').read_text()=='old'
    (root/'scripts/tool.py').write_text('unverified edit')
    with pytest.raises(ValueError,match='stale'):
        m.install(root,skills,tmp_path/'backups-again',development=True)
    assert not (tmp_path/'backups-again').exists()
