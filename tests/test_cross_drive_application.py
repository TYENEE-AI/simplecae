import json
from pathlib import Path
from simplecae.task_family import analyze_gripper_task
from simplecae.application import summarize_application


def test_cross_drive_overview_uses_explicit_file_uri_without_exposing_a_workspace(tmp_path,monkeypatch):
    from test_force_envelope import measured_task
    _,task=measured_task(tmp_path)
    r=analyze_gripper_task(task,tmp_path/'family',preview=False)
    assert r['status']=='pass_under_stated_model'
    result=tmp_path/'family'/r['cases'][1]['result_relative_path']
    def different_drive(*args):raise ValueError("path is on mount 'C:', start on mount 'F:'")
    monkeypatch.setattr('os.path.relpath',different_drive)
    out=tmp_path/'different-drive-overview'
    report=summarize_application([result],out)
    text=Path(report['application']).read_text(encoding='utf-8')
    assert (result.parent/'report.html').as_uri() in text
    assert json.loads((out/'application.json').read_text(encoding='utf-8'))['whole_product_rating_available'] is False
