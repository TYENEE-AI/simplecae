import copy
import math
import numpy as np
import pytest
from simplecae.joint_compliance import validate, solve, evidence_matches, ROTATIONAL, LINEAR
from simplecae.robot import transform, forward_kinematics, static_wrenches
from simplecae.elastic_transfer import propagate, add_ancestor_motion


def fixture(kind='revolute', yaw=0.):
    joint={'name':'hinge','type':kind,'parent':'base','child':'arm','origin':transform(),
           'axis':np.array([0.,0.,1.]),'mimic':None,'lower':-2.,'upper':2.,'effort_limit':100.}
    robot={'root':'base','joints':{'hinge':joint},'children':{'base':['hinge'],'arm':[]},
           'links':{'base':{'mass_kg':0.,'com_m':np.zeros(3)},'arm':{'mass_kg':2.,'com_m':np.array([.05,0,0])}}}
    kin=forward_kinematics(robot,{'hinge':0.},transform([.3,-.2,.1],[0,0,yaw]))
    key=LINEAR if kind=='prismatic' else ROTATIONAL
    case={'gravity_m_s2':[0,0,-10.],'loads':[{'name':'tip','link':'arm','force_n':[-2.,10.,5.],'position_m':[.1,0,0],'frame':'link','position_frame':'link'}],
          'elastic_transfer':{'joint_compliance':{'hinge':{key:1000.,'reference':'calibrated prescribed spring at held pose','verified':False}},
                              'rigid_joints':[],'max_rotation_rad':.01}}
    return case,robot,kin


@pytest.mark.parametrize('yaw',[0.,.7,math.pi/2])
def test_rotation_torque_sign_world_frame_and_actual_lever_arm(yaw):
    case,robot,kin=fixture(yaw=yaw);validate(case,robot)
    motions,records,ok=solve(case,robot,kin)
    assert ok and records[0]['external_generalized_effort']==pytest.approx(1.)
    assert records[0]['deflection']==pytest.approx(.001)
    holding=static_wrenches(robot,kin,case['gravity_m_s2'],loads=case['loads'])['joint_efforts']['hinge']
    assert records[0]['external_generalized_effort']==-holding
    states=propagate(robot,kin,{}, {},motions);r=kin['frames']['arm'][:3,:3]
    vectors={'tip':np.zeros(3)};metadata={'tip':{'link':'arm','point_world_m':(kin['frames']['arm'][:3,3]+r@[.1,0,0]).tolist()}}
    add_ancestor_motion(vectors,metadata,kin,states)
    assert np.allclose(vectors['tip'],r@[0,.1,0])
    # Incremental virtual work/strain energy: F dot du = tau*dq.
    assert (r@[-2,10,5])@vectors['tip']/1000==pytest.approx(.001)


def test_linear_spring_units_fixed_gravity_and_variable_force_stay_separate():
    case,robot,kin=fixture('prismatic')
    case['elastic_transfer']['joint_compliance']['hinge'][LINEAR]=100000.
    motions,full,ok=solve(case,robot,kin);_,fixed,fixed_ok=solve(case,robot,kin,True)
    assert ok and fixed_ok
    assert full[0]['deflection']==pytest.approx(-.00015)
    assert fixed[0]['deflection']==pytest.approx(-.0002)
    assert np.allclose(motions['hinge'][0],[0,0,-.15]) and np.allclose(motions['hinge'][1],0)


@pytest.mark.parametrize('damage',['missing_rigid','unknown','overlap','wrong_type','fixed','mimic','zero','negative','nan','both','no_source','boolean','verified_string'])
def test_incomplete_or_unsupported_joint_data_rejected(damage):
    case,robot,_=fixture();s=case['elastic_transfer'];spring=s['joint_compliance']['hinge']
    if damage=='missing_rigid':s.pop('rigid_joints')
    elif damage=='unknown':s['rigid_joints']=['unknown']
    elif damage=='overlap':s['rigid_joints']=['hinge']
    elif damage=='wrong_type':spring[LINEAR]=spring.pop(ROTATIONAL)
    elif damage=='fixed':robot['joints']['hinge']['type']='fixed'
    elif damage=='mimic':robot['joints']['hinge']['mimic']={'joint':'other'}
    elif damage=='both':spring[LINEAR]=1000.
    elif damage=='no_source':spring['reference']=' '
    elif damage=='verified_string':spring['verified']='true'
    else:spring[ROTATIONAL]={'zero':0,'negative':-1,'nan':float('nan'),'boolean':True}[damage]
    with pytest.raises(ValueError):validate(case,robot)


@pytest.mark.parametrize('kind',['revolute','prismatic'])
def test_large_joint_motion_withholds_small_response_evidence(kind):
    case,robot,kin=fixture(kind);spring=case['elastic_transfer']['joint_compliance']['hinge']
    spring[LINEAR if kind=='prismatic' else ROTATIONAL]=.01
    assert not solve(case,robot,kin)[2]


@pytest.mark.parametrize('damage',['missing','duplicate','stiffness','deflection','nan','units','source','screen'])
def test_link_pass_cannot_mask_missing_or_inconsistent_spring_evidence(damage):
    case,robot,kin=fixture();_,full,ok=solve(case,robot,kin);_,fixed,_=solve(case,robot,kin,True)
    evidence={'full':full,'fixed':fixed,'small_response_passed':ok}
    assert evidence_matches(case,evidence)
    if damage=='missing':evidence['fixed']=[]
    elif damage=='duplicate':evidence['full']*=2
    elif damage=='stiffness':full[0][ROTATIONAL]*=2
    elif damage=='deflection':full[0]['deflection']=0.
    elif damage=='nan':full[0]['deflection']=float('nan')
    elif damage=='units':full[0]['deflection_units']='mm'
    elif damage=='source':full[0]['reference']='other'
    elif damage=='screen':full[0]['small_response_passed']=False
    assert not evidence_matches(case,evidence)


def test_multiple_springs_branch_transfer_and_common_relative_cancellation():
    case,robot,kin=fixture();robot['children']['arm']=['elbow']
    robot['joints']['elbow']=dict(robot['joints']['hinge'],name='elbow',parent='arm',child='tip',origin=transform([.05,0,0]))
    robot['links']['tip']={'mass_kg':0.,'com_m':np.zeros(3)};robot['children']['tip']=[]
    robot['joints']['branch']=dict(robot['joints']['hinge'],name='branch',parent='base',child='other',origin=transform([0,.1,0]))
    robot['children']['base'].append('branch');robot['children']['other']=[];robot['links']['other']={'mass_kg':0.,'com_m':np.zeros(3)}
    kin=forward_kinematics(robot,{'hinge':0,'elbow':0,'branch':0})
    states=propagate(robot,kin,{}, {},{'hinge':(np.zeros(3),np.array([0,0,.001])),'elbow':(np.zeros(3),np.array([0,0,.002]))})
    assert np.allclose(states['tip'][0],[0,.05,0]) and np.allclose(states['tip'][1],[0,0,.003])
    assert np.allclose(states['other'][0],0) and np.allclose(states['other'][1],0)
    vectors={'p':np.zeros(3),'q':np.zeros(3)}
    add_ancestor_motion(vectors,{'p':{'link':'tip','point_world_m':[.1,0,0]},'q':{'link':'tip','point_world_m':[.1,.01,0]}},kin,states)
    assert np.allclose(vectors['q']-vectors['p'],[-.03,0,0])


def test_joint_stiffness_is_bound_to_comparison_task_contract():
    from simplecae.signals import robot_contract, recorded_contract_matches
    case,robot,_=fixture();case['components']=[]
    contract=robot_contract(case,robot);changed=copy.deepcopy(case)
    changed['elastic_transfer']['joint_compliance']['hinge'][ROTATIONAL]*=2
    assert not recorded_contract_matches(changed,contract,True)


def test_actual_runtime_schema_accepts_new_contract_and_export_agrees():
    import json
    from pathlib import Path
    from simplecae.schemas import check_contract,contracts
    root=Path(__file__).resolve().parents[1]
    case=json.loads((root/'examples/mechanics/elastic-tree.json').read_text(encoding='utf-8'))
    case['elastic_transfer'].update(rigid_joints=['mount'],joint_compliance={'elbow':{
        ROTATIONAL:100.,'reference':'prescribed held-pose reference','verified':False}})
    check_contract(case)
    assert contracts()['case']==json.loads((root/'assets/schemas/case.schema.json').read_text(encoding='utf-8'))
    case['elastic_transfer'].pop('rigid_joints')
    with pytest.raises(ValueError,match='rigid_joints'):check_contract(case)


@pytest.mark.parametrize('yaw',[0.,.4,math.pi/2])
def test_applicability_span_is_invariant_for_noncollinear_world_frame_points(yaw):
    case,robot,kin=fixture('prismatic',yaw)
    case['loads'].append({'name':'side','link':'arm','force_n':[1,0,0],'position_m':[0,.1,0],'frame':'link','position_frame':'link'})
    _,records,_=solve(case,robot,kin)
    assert records[0]['linear_screen_span_mm']==pytest.approx(math.sqrt(2)*100)
