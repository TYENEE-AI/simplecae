import copy
import json
from pathlib import Path
import pytest
from simplecae.robot import load_robot_case,read_urdf,forward_kinematics,static_wrenches
from simplecae.component_transfer import transfer_loads
from simplecae.signals import robot_contract,recorded_contract_matches


def fixture(tmp_path):
    examples=Path(__file__).resolve().parents[1]/'examples/robots'
    c=json.loads((examples/'one-link.robot.json').read_text())
    c['model']['path']=str(examples/'one-link.urdf')
    c['components'][0]['case_path']=str(examples/'arm.component.json')
    c['components'][0]['port_load_policies']={'tool':{'allow_opposite_traction':True,'reference':'Declared bilateral attachment, not a compression-only bearing'}}
    p=tmp_path/'robot.json';p.write_text(json.dumps(c))
    return p,c


def test_explicit_policy_reaches_full_and_fixed_loads_and_contract(tmp_path):
    p,c=fixture(tmp_path);c=load_robot_case(p);r=read_urdf(c['model']['path'])
    kin=forward_kinematics(r,c['poses'][0]['joints'])
    full=static_wrenches(r,kin,c['gravity_m_s2'],c['payloads'],[])
    fixed=static_wrenches(r,kin,c['gravity_m_s2'],[],[])
    transfer=transfer_loads(r,c,c['components'][0],kin,full,fixed)
    assert transfer['loads'] and all(l['allow_opposite_traction'] for l in transfer['loads'])
    assert all(p['load_policy']['reference'] for p in transfer['ports'])
    contract=robot_contract(c,r)
    assert recorded_contract_matches(c,contract,robot=True)
    changed=copy.deepcopy(c);changed['components'][0]['port_load_policies']['tool']['allow_opposite_traction']=False
    assert robot_contract(changed,r)!=contract
    assert not recorded_contract_matches(changed,contract,robot=True)


@pytest.mark.parametrize('policy',[
    {'wrong_port':{'allow_opposite_traction':True,'reference':'test'}},
    {'tool':{'allow_opposite_traction':True}},
    {'tool':{'allow_opposite_traction':1,'reference':'test'}},
    {'tool':{'distribution':'invented','reference':'test'}}])
def test_invalid_or_unjustified_policy_rejected(tmp_path,policy):
    p,c=fixture(tmp_path);c['components'][0]['port_load_policies']=policy;p.write_text(json.dumps(c))
    with pytest.raises(ValueError):load_robot_case(p)


def test_missing_joint_stiffness_gives_action_without_masking_invalid_model():
    from simplecae.design_check import joint_displacement_guidance
    r={'status':'pass_under_stated_model','case':{'probes':[{'name':'tip'}],
        'elastic_transfer':{'joints_locked_verified':False}}}
    guidance=joint_displacement_guidance(r,None,{})
    assert guidance['focus']=='joint_compliance' and guidance['evidence_status']=='needs_information'
    r['status']='invalid';assert joint_displacement_guidance(r,None,{}) is None
