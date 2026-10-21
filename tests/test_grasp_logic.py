import copy
import json
from pathlib import Path
import numpy as np
import pytest
from simplecae.grasp import compile_gripper_task,validate_grasp,assess_grasp
from simplecae.robot import analyze_robot,static_wrenches
from simplecae.case import write_json

def test_compiled_accelerating_gripper_passes_the_public_api_input_path(tmp_path):
    from simplecae.api import check_case
    robot_file(tmp_path/'gripper.urdf');t=task();t['acceleration_along_gravity_m_s2']=2
    c=compile_gripper_task(t,tmp_path/'task.json');write_json(tmp_path/'case.json',c)
    checked=check_case(tmp_path/'case.json')
    assert checked['grasp']['friction_coefficient']==.3
    assert next(x for x in checked['loads'] if x['name']=='workpiece_acceleration_0')['position_frame']=='link'

def task():
    return {'task_id':'grip-functional-reference','model_path':'gripper.urdf','poses':[{'name':'hold','joints':{'slide':.01}}],
     'contacts':[{'link':'left','position_m':[0,.004,.04],'normal_link':[-1,0,0]},
                 {'link':'right','position_m':[0,.004,.04],'normal_link':[1,0,0]}],
     'payload_mass_kg':.25,'normal_force_per_finger_n':12,'friction_coefficient':.3,'slip_safety_factor':2,
     'conditions':dict.fromkeys(('inertials_verified','actuator_ratings_verified','mount_verified','poses_verified'),True),
     'grasp_conditions':{'friction_verified':True,'force_verified':True}}

def robot_file(path):
    path.write_text('''<robot name="functional_gripper">
    <link name="base"><inertial><mass value=".1"/><inertia ixx=".001" iyy=".001" izz=".001" ixy="0" ixz="0" iyz="0"/></inertial></link>
    <link name="left"><inertial><mass value=".01"/><inertia ixx=".000001" iyy=".000001" izz=".000001" ixy="0" ixz="0" iyz="0"/></inertial></link>
    <link name="right"><inertial><mass value=".01"/><inertia ixx=".000001" iyy=".000001" izz=".000001" ixy="0" ixz="0" iyz="0"/></inertial></link>
    <joint name="left_mount" type="fixed"><parent link="base"/><child link="left"/><origin xyz="-.02 0 0"/></joint>
    <joint name="slide" type="prismatic"><parent link="base"/><child link="right"/><axis xyz="1 0 0"/><limit lower="0" upper=".04" effort="100" velocity=".1"/></joint>
    </robot>''',encoding='utf-8')

@pytest.mark.parametrize('mu,expected',[(.3,'pass_under_stated_model'),(.2,'fail_under_stated_model'),(0,'fail_under_stated_model')])
def test_friction_failure_overrules_passing_actuator(tmp_path,mu,expected):
    robot_file(tmp_path/'gripper.urdf');t=task();t['friction_coefficient']=mu
    c=compile_gripper_task(t,tmp_path/'task.json');write_json(tmp_path/'case.json',c)
    r=analyze_robot(tmp_path/'case.json',tmp_path/'result',preview=False)
    assert r['status']==expected
    assert r['poses'][0]['actuator_efforts']['slide']['utilization']<1
    signal=r['evaluation_signal'];assert signal['valid_for_comparison']
    assert signal['feasible_under_stated_model'] is (mu==.3)
    assert not signal['whole_installation_rating_available']
    if mu==.2:assert signal['bottleneck_margin']<1
    if mu==0:assert signal['bottleneck_margin'] is None

def test_unknown_friction_withholds_capacity_but_not_model_computation(tmp_path):
    robot_file(tmp_path/'gripper.urdf');t=task();t['grasp_conditions']['friction_verified']=False
    c=compile_gripper_task(t,tmp_path/'task.json');write_json(tmp_path/'case.json',c)
    r=analyze_robot(tmp_path/'case.json',tmp_path/'result',preview=False)
    assert r['status']=='pass_under_stated_model' and not r['conditional_payload_limit']['available']
    assert not r['evaluation_signal']['physical_conditions_verified']

def test_requested_grasp_without_assessment_gets_no_favorable_margin(tmp_path):
    from simplecae.signals import design_signal
    robot_file(tmp_path/'gripper.urdf');c=compile_gripper_task(task(),tmp_path/'task.json');write_json(tmp_path/'case.json',c)
    r=analyze_robot(tmp_path/'case.json',tmp_path/'result',preview=False)
    r['poses'][0].pop('grasp_assessment')
    signal=design_signal(r)
    assert not signal['valid_for_comparison'] and signal['bottleneck_margin'] is None

def test_acceleration_is_formula_generated_in_world_coordinates(tmp_path):
    t=task();t['acceleration_along_gravity_m_s2']=9.80665
    c=compile_gripper_task(t,tmp_path/'task.json')
    acceleration=[l for l in c['loads'] if l['name'].startswith('workpiece_acceleration')]
    assert all(l['frame']=='world' and l['position_frame']=='link' for l in acceleration)
    assert sum(l['force_n'][2] for l in acceleration)==pytest.approx(-.25*9.80665)
    identity={'frames':{n:np.eye(4) for n in ('left','right')}}
    assessment=assess_grasp(c,identity)
    assert assessment['required_tangential_force_n']==pytest.approx(2*.25*9.80665*2)

def test_normal_force_cannot_scale_to_fake_payload_capacity(tmp_path):
    c=compile_gripper_task(task(),tmp_path/'task.json');c['loads'][0]['scalable']=True
    with pytest.raises(ValueError,match='fixed'):validate_grasp(c)

def test_acceleration_wrench_uses_world_force_and_link_point_independently():
    transform=np.eye(4);transform[:3,:3]=[[0,-1,0],[1,0,0],[0,0,1]];transform[:3,3]=[.2,.3,0]
    robot={'links':{'base':{'com_m':np.zeros(3),'mass_kg':0}},'root':'base','children':{'base':[]},'joints':{}}
    kin={'frames':{'base':transform},'joint_frames':{},'axes':{},'drivers':{}}
    load={'link':'base','force_n':[0,0,-2],'position_m':[.1,0,0],'frame':'world','position_frame':'link'}
    r=static_wrenches(robot,kin,[0,0,-9.80665],loads=[load])
    assert r['world_external_wrench']==pytest.approx([0,0,-2,-.8,.4,0])
