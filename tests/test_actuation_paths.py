import copy
import numpy as np
import pytest
from simplecae.actuation import closed_statics,validate_reactions
from simplecae.robot import read_urdf,forward_kinematics,static_wrenches,transform
from simplecae.component_transfer import transfer_loads


def slider(tmp_path):
    path=tmp_path/'r.urdf'
    path.write_text('''<robot name="slider"><link name="base"/><link name="rear"/><link name="slide"/>
    <joint name="mount" type="fixed"><parent link="base"/><child link="rear"/></joint>
    <joint name="drive" type="prismatic"><parent link="base"/><child link="slide"/><axis xyz="1 0 0"/><limit lower="0" upper="1" effort="50" velocity="1"/></joint></robot>''')
    r=read_urdf(path,massless_links=['base','rear','slide']);k=forward_kinematics(r,{'drive':.2})
    c={'gravity_m_s2':[0,0,-9.81],'loads':[{'name':'external','link':'slide','position_m':[0,0,0],'force_n':[-10,0,0],'scalable':True}],
       'actuation_reactions':[{'name':'motor','joint':'drive','driven':{'link':'slide','point_link_m':[0,.03,0]},
                              'reaction':{'link':'rear','point_link_m':[.6,.03,0]}}]}
    return r,k,c


def statics(r,k,c):return static_wrenches(r,k,c['gravity_m_s2'],c.get('payloads',[]),c.get('loads',[]))


def test_axial_pair_reroutes_force_and_eccentric_moment_without_erasing_drive_rating(tmp_path):
    r,k,c=slider(tmp_path);bare=statics(r,k,c);s=closed_statics(r,c,k,bare)
    assert bare['actuator_efforts']['drive']==10
    assert s['joint_wrenches']['drive'][0]==pytest.approx(0)
    assert s['joint_wrenches']['mount'][0]==pytest.approx(-10)
    assert s['joint_wrenches']['mount'][5]==pytest.approx(.3) # actual eccentric rear attachment
    assert s['joint_wrenches']['drive'][5]==pytest.approx(-.3) # equal guide couple
    assert np.allclose(s['world_external_wrench'],bare['world_external_wrench'])
    assert np.allclose(s['reaction_paths'][0]['world_pair_resultant'],0)


def test_world_rotation_and_translation_preserve_load_path(tmp_path):
    r,k,c=slider(tmp_path);base=transform([1,2,3],[.4,-.5,.6]);k=forward_kinematics(r,{'drive':.2},base)
    bare=statics(r,k,c);s=closed_statics(r,c,k,bare)
    assert np.allclose(s['actuation_loads'][0]['force_n'],base[:3,:3]@[10,0,0])
    assert np.allclose(s['world_external_wrench'],bare['world_external_wrench'])


def test_component_transfer_fixed_and_variable_path_loads_uses_component_mm_frame(tmp_path):
    r,k,c=slider(tmp_path);c['loads'][0]['force_n']=[-4,0,0];c['loads'].append({'name':'fixed','link':'slide','position_m':[0,0,0],'force_n':[-6,0,0],'scalable':False})
    bare=statics(r,k,c);fixed=static_wrenches(r,k,c['gravity_m_s2'],loads=[c['loads'][1]])
    full=closed_statics(r,c,k,bare);f=closed_statics(r,c,k,fixed,fixed=True)
    component={'link':'rear','ports':{'actuation:motor:reaction':{'type':'plane','axis':'x','position_mm':0}},'link_from_component':{'xyz_m':[.1,0,0],'rpy_rad':[0,0,np.pi/2]}}
    t=transfer_loads(r,c,component,k,full,f);a,b=t['loads']
    assert np.allclose(a['total_force_n'],[0,6,0]);assert np.allclose(b['total_force_n'],[0,4,0])
    assert np.allclose(a['application_point_mm'],[30,-500,0])
    assert not a['scalable'] and b['scalable']
    component['ports']={}
    with pytest.raises(ValueError,match='missing load port actuation:motor:reaction'):transfer_loads(r,c,component,k,full,f)


@pytest.mark.parametrize('change,match',[
    (lambda c:c['actuation_reactions'][0]['reaction']['point_link_m'].__setitem__(1,.04),'off-axis'),
    (lambda c:c['actuation_reactions'][0]['reaction'].__setitem__('link','slide'),'outside'),
    (lambda c:c['actuation_reactions'][0]['driven'].__setitem__('link','base'),'child subtree')])
def test_ambiguous_paths_rejected(tmp_path,change,match):
    r,k,c=slider(tmp_path);change(c)
    with pytest.raises(ValueError,match=match):closed_statics(r,c,k,statics(r,k,c))


def test_zero_effort_keeps_attachment_mapping_mandatory(tmp_path):
    r,k,c=slider(tmp_path);c['loads']=[];bare=statics(r,k,c);s=closed_statics(r,c,k,bare)
    component={'link':'rear','ports':{'actuation:motor:reaction':{'type':'plane','axis':'x','position_mm':0}}}
    assert transfer_loads(r,c,component,k,s,s)['loads']==[]
    component['ports']={}
    with pytest.raises(ValueError,match='missing load port'):transfer_loads(r,c,component,k,s,s)


def test_verified_path_needs_evidence_and_duplicate_joint_rejected(tmp_path):
    _,_,c=slider(tmp_path);c['actuation_reactions'][0]['verified']=True
    with pytest.raises(ValueError,match='evidence'):validate_reactions(c)
    c['actuation_reactions'][0]['reference']='installation record'
    validate_reactions(c);c['actuation_reactions'].append(copy.deepcopy(c['actuation_reactions'][0]))
    with pytest.raises(ValueError,match='unique'):validate_reactions(c)


def test_revolute_direct_torque_and_cross_joint_reaction_rejected(tmp_path):
    from test_robot import robot
    r=robot(tmp_path);k=forward_kinematics(r,{'shoulder':0,'elbow':0})
    c={'gravity_m_s2':[0,0,-9.80665], 'actuation_reactions':[{'name':'elbow_motor','joint':'elbow','driven':{'link':'forearm','point_link_m':[0,0,0]},'reaction':{'link':'upper','point_link_m':[.2,0,0]}}]}
    bare=statics(r,k,c);s=closed_statics(r,c,k,bare)
    assert np.allclose(s['actuation_loads'][0]['force_n'],0)
    assert s['actuator_efforts']['elbow']==pytest.approx(0,abs=1e-12)
    assert s['actuator_efforts']['shoulder']==pytest.approx(bare['actuator_efforts']['shoulder'])
    c['actuation_reactions'][0]['reaction']['link']='base'
    with pytest.raises(ValueError,match='couples another moving joint'):closed_statics(r,c,k,bare)


def test_mimic_path_not_assumed_direct_motor(tmp_path):
    from test_robot import robot
    r=robot(tmp_path,'<mimic joint="shoulder" multiplier="-0.5"/>');k=forward_kinematics(r,{'shoulder':0})
    c={'gravity_m_s2':[0,0,-9.81],'actuation_reactions':[{'name':'motor','joint':'shoulder','driven':{'link':'upper','point_link_m':[0,0,0]},'reaction':{'link':'base','point_link_m':[0,0,0]}}]}
    with pytest.raises(ValueError,match='mimic transmission'):closed_statics(r,c,k,statics(r,k,c))
