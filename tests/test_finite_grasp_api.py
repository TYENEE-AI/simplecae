import copy
import numpy as np
import pytest
from test_grasp_logic import task,robot_file
from simplecae.grasp import compile_gripper_task,validate_grasp,assess_grasp
from simplecae.robot import read_urdf,forward_kinematics
from simplecae.api import analyze_case,check_case
from simplecae.case import write_json

def finite_case(tmp_path,mode='declared_per_pad'):
    robot_file(tmp_path/'gripper.urdf');t=task();t['normal_force_per_finger_n']=13
    c=compile_gripper_task(t,tmp_path/'task.json');c['grasp']['model']='finite_pad_wrench';c['grasp']['pad_wrench_mode']=mode
    c['grasp']['conditions']['pad_contact_verified']=False
    c['grasp']['pad_contacts']=[{'normal_load_name':f'normal_{i}','center_link_m':[0,.004,.04],
        'tangent_u_link':[0,1,0],'tangent_v_link':[0,0,1],'half_extents_m':[.008,.012]} for i in range(2)]
    return c

def test_finite_contact_model_runs_through_public_json_api_and_keeps_physical_gaps(tmp_path):
    c=finite_case(tmp_path);p=tmp_path/'case.json';write_json(p,c)
    checked=check_case(p);assert checked['grasp']['model']=='finite_pad_wrench'
    r=analyze_case(p,tmp_path/'result',preview=False)
    assert r['status']=='pass_under_stated_model'
    g=r['poses'][0]['grasp_assessment']
    assert g['declared_component_load_pattern_checked'] is True
    assert g['limiting_contact_solution']['relative_moment_residual']<1e-8
    assert not r['conditional_payload_limit']['available'] and not r['evaluation_signal']['physical_conditions_verified']

def test_pure_rotation_demand_fails_even_with_enough_vertical_friction(tmp_path):
    c=finite_case(tmp_path,mode='total_wrench')
    c['loads'].append({'name':'twist','link':'left','force_n':[0,0,0],'moment_n_m':[0,0,.5],'position_m':[0,.004,.04],'frame':'link','scalable':True})
    c['grasp']['additional_tangential_load_names']=['twist'];p=tmp_path/'case.json';write_json(p,c)
    r=analyze_case(p,tmp_path/'out',preview=False)
    assert r['status']=='fail_under_stated_model'
    assert r['poses'][0]['grasp_assessment']['available_friction_n']>r['poses'][0]['grasp_assessment']['required_tangential_force_n']
    assert r['evaluation_signal']['feasible_under_stated_model'] is False
    assert r['evaluation_signal']['bottleneck_margin'] is None or r['evaluation_signal']['bottleneck_margin']<1

def test_declared_load_shares_are_not_replaced_by_an_optimized_different_pattern(tmp_path):
    c=finite_case(tmp_path);c['payloads'][0]['mass_kg']=.23;c['payloads'][1]['mass_kg']=.02
    r=read_urdf(c['model']['path']);k=forward_kinematics(r,{'slide':.01})
    exact=assess_grasp(c,k)
    optimized=copy.deepcopy(c);optimized['grasp']['pad_wrench_mode']='total_wrench';free=assess_grasp(optimized,k)
    assert not exact['feasible'] and free['feasible']
    assert free['declared_component_load_pattern_checked'] is False

def test_half_extents_or_duplicate_pad_mapping_are_not_guessed(tmp_path):
    c=finite_case(tmp_path);c['grasp']['pad_contacts'][0]['half_extents_m']=[.008,-.012]
    with pytest.raises(ValueError):validate_grasp(c)
    c=finite_case(tmp_path);c['grasp']['pad_contacts'][1]['normal_load_name']='normal_0'
    with pytest.raises(ValueError,match='bijectively'):validate_grasp(c)
