import json
from pathlib import Path
import pytest
from simplecae import cache

def evidence(tmp_path):
    source=tmp_path/'source';source.mkdir()
    result={'status':'pass_under_stated_model','evaluation_signal':{'valid_for_comparison':True}}
    (source/'result.json').write_text(json.dumps(result))
    cache.save(tmp_path/'cache','key',source,result)
    return tmp_path/'cache',source

def test_damaged_evidence_is_a_miss_not_a_favorable_reuse(tmp_path):
    root,source=evidence(tmp_path)
    index=json.loads((root/'key/latest.json').read_text())
    (root/'key'/index['directory']/'result.json').write_text('{}')
    out=tmp_path/'out'
    assert cache.load(root,'key',out) is None and not out.exists()

def test_restoration_io_failure_aborts_before_any_solver_fallback(tmp_path,monkeypatch):
    root,source=evidence(tmp_path)
    def failure(*args,**kwargs):raise OSError('disk full during cache restoration')
    monkeypatch.setattr(cache.shutil,'copytree',failure)
    with pytest.raises(OSError,match='disk full'):cache.load(root,'key',tmp_path/'out')
