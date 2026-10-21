import json
import copy
from pathlib import Path
import pytest
from simplecae.schemas import contracts,check_contract
from simplecae.api import check_case
from simplecae.signals import design_signal,structural_contract
from simplecae.product import prepare,robot_visualization
from simplecae.robot import read_urdf,forward_kinematics,static_wrenches
from test_signals import result

ROOT=Path(__file__).resolve().parents[1]

def test_all_shipped_cases_pass_public_contracts():
    files=[p for p in (ROOT/'examples').rglob('*.json') if p.name.endswith(('.case.json','.robot.json','.component.json')) or p.parent.name=='assemblies' and '.case.' in p.name]
    assert len(files)>20
    for file in files:check_case(file)


def test_schema_definitions_and_invalid_signal_mask():
    from jsonschema import Draft202012Validator
    for schema in contracts().values():Draft202012Validator.check_schema(schema)
    r=result();r['status']='invalid';s=design_signal(r);check_contract(s,'signal')
    s['bottleneck_margin']=10
    with pytest.raises(ValueError):check_contract(s,'signal')


def test_contract_is_recorded_before_templates_can_change():
    r=result();r['task_contract']=copy.deepcopy(structural_contract(r['case']));original=design_signal(r)['task_contract_sha256']
    r['case']['loads'][0]['total_force_n']=[0,0,-1]
    assert design_signal(r)['task_contract_sha256']==original
    assert not design_signal(r)['valid_for_comparison']


def test_guidance_does_not_assign_physical_facts(tmp_path):
    prepare(ROOT/'examples/integration/cadgen-beam.step',tmp_path/'solid')
    prepare(ROOT/'examples/robots/one-link.urdf',tmp_path/'robot')
    data=json.loads((tmp_path/'solid/intake.json').read_text(encoding='utf-8'))
    assert 'material' not in data and len(data['geometry']['faces'])==6
    assert 'material_verified' in data['conditions']
    assert json.loads((tmp_path/'robot/intake.json').read_text())['joints'][0]['name']=='shoulder'


def test_robot_visual_matches_urdf_frames_and_units():
    robot=read_urdf(ROOT/'examples/robots/one-link.urdf');kin=forward_kinematics(robot,{'shoulder':0})
    c={'poses':[{'name':'extended','joints':{'shoulder':0}}],'base':{'type':'fixed'}}
    record={'name':'extended','status':'pass_under_stated_model','actuator_efforts':{},'center_of_mass_world_m':[0,0,0]}
    d=robot_visualization(robot,c,[record]);assert not d['display_omissions']
    p=d['poses'][0];assert p['triangles'] and len(p['triangle_links'])==len(p['triangles'])
    import numpy as np
    assert np.max(np.array(p['xyz'])[:,0])==pytest.approx(.1)
