from pathlib import Path
import json
import pytest
from simplecae.scaffold import scaffold
from simplecae.task import start_task
from simplecae.mesh_policy import mesh_policy

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('preset',['hook','bracket','plate'])
def test_missing_physics_generates_startable_information_plan(tmp_path,preset):
    report=scaffold(tmp_path/'draft',preset=preset,material='reference-steel')
    assert not report['ready_for_body_check'] and report['case'] is None
    status=start_task(Path(report['task']),tmp_path/'workspace')
    assert status['whole_product_pass_available'] is False
    assert not (tmp_path/'workspace/inputs/check-001.case.json').exists()


def test_complete_scaffold_starts_but_cannot_claim_product_pass(tmp_path):
    data=ROOT/'examples/integration'
    report=scaffold(tmp_path/'draft',preset='bracket',material='reference-steel',
                    model=data/'simplecad-beam.step',interfaces=data/'simplecad-beam.interfaces.json',
                    force_n=[0,0,-49],max_displacement_mm=.3,mesh_sizes=[5,4,3])
    assert report['ready_for_body_check']
    c=json.loads(Path(report['case']).read_text())
    assert not any(c['conditions'].values())
    status=start_task(Path(report['task']),tmp_path/'workspace')
    assert status['whole_product_pass_available'] is False
    assert (tmp_path/'workspace/inputs/check-001.case.json').exists()


def test_cad_label_is_not_a_material_source(tmp_path):
    with pytest.raises(ValueError,match='CAD labels'):
        scaffold(tmp_path/'draft',preset='hook',material='6061')
    assert not (tmp_path/'draft').exists()


def test_display_rounding_preserves_actual_requested_sizes():
    case={'schema_version':'2.0','mesh':{'sizes_mm':[4.,2.8,1.9599999999999997]}}
    result=mesh_policy(case)
    assert result['legal_example_sizes_mm']==[4.,2.8,1.96]
    assert result['requested_sizes_mm'][-1]==1.9599999999999997
