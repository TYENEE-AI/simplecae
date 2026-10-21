"""Host selection changes discovery placement, never the skill or its evidence gates."""
import importlib.util
import json
from pathlib import Path
import pytest


def installer():
    path=Path(__file__).resolve().parents[1]/'scripts/install_local.py'
    spec=importlib.util.spec_from_file_location('installer_paths',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('agent,suffix',[
    ('codex','.codex/skills'),('claude','.claude/skills'),
    ('deepseek','.agents/skills'),('omp','.omp/agent/skills'),('pi','.agents/skills'),
])
def test_stock_host_targets(agent,suffix,tmp_path,monkeypatch):
    module=installer()
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    monkeypatch.delenv('CODEX_HOME',raising=False)
    monkeypatch.delenv('CLAUDE_CONFIG_DIR',raising=False)
    assert module.default_skills_root(agent)==tmp_path/suffix


def test_custom_target_preview_does_not_install(tmp_path,monkeypatch,capsys):
    module=installer();target=tmp_path/'project skills'
    monkeypatch.setattr('sys.argv',['install_local.py','--agent','pi','--skills-root',str(target),'--show-target'])
    assert module.main()==0
    receipt=json.loads(capsys.readouterr().out)
    assert receipt['target']==str(target/'simplecae')
    assert receipt['installed'] is False and not target.exists()
