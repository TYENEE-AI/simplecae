"""A development archive must not inherit another version's passing record."""
import importlib.util
import json
import re
from pathlib import Path
import zipfile
import pytest
from simplecae.case import write_json
from simplecae.release import delivery_hashes, delivery_files

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def development_tree(tmp_path):
    # Synthetic integrity fixture only; this is not numerical validation.
    for folder in ('scripts','references','validation'):(tmp_path/folder).mkdir()
    for name in ('SKILL.md','requirements-lock.txt','.gitignore'):(tmp_path/name).write_text('fixture')
    (tmp_path/'pyproject.toml').write_text('[project]\nversion="1.6.0.dev4"\n')
    (tmp_path/'references/guide.md').write_text('original')
    write_json(tmp_path/'validation/development-validation.json',{
        'passed':True,'toolkit_version':'1.6.0.dev4',
        'source_files_sha256':delivery_hashes(tmp_path,include_validation=False)})
    spec=importlib.util.spec_from_file_location('development_package_probe',ROOT/'scripts/package_skill.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.__file__=str(tmp_path/'scripts/package_skill.py')
    return tmp_path,module


def test_development_archive_binds_current_sources(development_tree,monkeypatch,capsys):
    root,module=development_tree;out=root/'checkpoint.zip'
    monkeypatch.setattr('sys.argv',['package_skill.py','--development','--out',str(out)])
    module.main()
    receipt=json.loads(capsys.readouterr().out)
    assert receipt['qualification']=='development checkpoint'
    with zipfile.ZipFile(out) as archive:
        assert archive.read('simplecae/references/guide.md')==b'original'
        assert archive.testzip() is None


@pytest.mark.parametrize('change',['version','failed','missing-hashes','docs','added','removed'])
def test_stale_development_record_cannot_create_archive(development_tree,monkeypatch,change):
    root,module=development_tree;out=root/'must-not-exist.zip'
    record_path=root/'validation/development-validation.json'
    record=json.loads(record_path.read_text())
    if change=='version':record['toolkit_version']='1.6.0.dev3'
    elif change=='failed':record['passed']=False
    elif change=='missing-hashes':record.pop('source_files_sha256')
    elif change=='docs':(root/'references/guide.md').write_text('changed')
    elif change=='added':(root/'scripts/extra.py').write_text('new')
    else:(root/'references/guide.md').unlink()
    write_json(record_path,record)
    monkeypatch.setattr('sys.argv',['package_skill.py','--development','--out',str(out)])
    with pytest.raises(ValueError):module.main()
    assert not out.exists()


def test_skill_entrypoint_guides_are_in_the_source_package():
    """Agents must be able to follow routing links after extracting the skill."""
    shipped = {p.resolve() for p in delivery_files(ROOT, include_validation=False)}
    for name in ("SKILL.md", "README.md"):
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", (ROOT/name).read_text(encoding="utf-8"))
        for link in links:
            if "://" in link or link.startswith("#"):
                continue
            target = (ROOT/link.split("#", 1)[0]).resolve()
            assert target in shipped, f"{name} links to an unpackaged guide: {link}"
