"""Shared Windows/Ubuntu checkouts retain independent solver configuration."""
import json
import pytest
from simplecae import solver


def test_platform_solver_does_not_replace_other_os(tmp_path,monkeypatch):
    monkeypatch.setattr(solver,'ROOT',tmp_path)
    monkeypatch.delenv('SIMPLECAE_CCX',raising=False)
    windows=tmp_path/'windows-ccx.exe';windows.write_text('fixture')
    linux=tmp_path/'linux-ccx';linux.write_text('fixture')
    tools=tmp_path/'.tools';tools.mkdir()
    config={'ccx':str(windows),'ccx_by_platform':{'Linux':str(linux)}}
    path=tools/'runtime.json';path.write_text(json.dumps(config))
    monkeypatch.setattr(solver.platform,'system',lambda:'Linux')
    assert solver.find_ccx()==linux
    monkeypatch.setattr(solver.platform,'system',lambda:'Windows')
    assert solver.find_ccx()==windows
    assert json.loads(path.read_text())==config


@pytest.mark.parametrize('value',[[],{'ccx_by_platform':[]},{'ccx':42}])
def test_bad_runtime_configuration_has_actionable_error(tmp_path,monkeypatch,value):
    monkeypatch.setattr(solver,'ROOT',tmp_path)
    monkeypatch.delenv('SIMPLECAE_CCX',raising=False)
    (tmp_path/'.tools').mkdir()
    (tmp_path/'.tools/runtime.json').write_text(json.dumps(value))
    with pytest.raises(ValueError,match='runtime.json|CalculiX'):
        solver.find_ccx()
