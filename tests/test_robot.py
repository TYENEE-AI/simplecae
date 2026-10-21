from pathlib import Path
import numpy as np
import pytest
from simplecae.robot import read_urdf,forward_kinematics,static_wrenches,contact_equilibrium,transform,resolve_asset


def arm_urdf(mimic=''):
    return f'''<robot name="analytic_2R">
    <link name="base"/>
    <link name="upper"><inertial><origin xyz="0.1 0 0"/><mass value="1"/><inertia ixx="0.0000166667" iyy="0.0033416667" izz="0.0033416667" ixy="0" ixz="0" iyz="0"/></inertial></link>
    <link name="forearm"><inertial><origin xyz="0.075 0 0"/><mass value="0.5"/><inertia ixx="0.0000083333" iyy="0.0009416667" izz="0.0009416667" ixy="0" ixz="0" iyz="0"/></inertial></link>
    <joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/><axis xyz="0 -1 0"/><limit lower="-3.14" upper="3.14" effort="20" velocity="1"/></joint>
    <joint name="elbow" type="revolute"><parent link="upper"/><child link="forearm"/><origin xyz="0.2 0 0"/><axis xyz="0 -1 0"/><limit lower="-3.14" upper="3.14" effort="8" velocity="1"/>{mimic}</joint></robot>'''


def robot(tmp_path,mimic=''):
    path=tmp_path/'arm.urdf';path.write_text(arm_urdf(mimic),encoding='utf-8')
    return read_urdf(path,massless_links=['base'])


def test_two_link_closed_form_holding_torques_and_rotated_pose(tmp_path):
    r=robot(tmp_path);p=[{'name':'tool','link':'forearm','mass_kg':.8,'center_m':[.15,0,0]}]
    k=forward_kinematics(r,{'shoulder':0,'elbow':0})
    s=static_wrenches(r,k,[0,0,-9.80665],p)
    assert s['actuator_efforts']['shoulder']==pytest.approx(9.80665*(1*.1+.5*.275+.8*.35))
    assert s['actuator_efforts']['elbow']==pytest.approx(9.80665*(.5*.075+.8*.15))
    k=forward_kinematics(r,{'shoulder':np.pi/2,'elbow':0})
    s=static_wrenches(r,k,[0,0,-9.80665],p)
    assert max(abs(v) for v in s['actuator_efforts'].values())<1e-12


def test_mimic_actuator_effort_matches_independent_potential_derivative(tmp_path):
    r=robot(tmp_path,'<mimic joint="shoulder" multiplier="-0.5" offset="0.1"/>')
    payload=[{'name':'tool','link':'forearm','mass_kg':.8,'center_m':[.15,0,0]}]
    angle=.3
    k=forward_kinematics(r,{'shoulder':angle})
    s=static_wrenches(r,k,[0,0,-9.80665],payload)
    def potential(q):
        # Independent 2R geometry: shoulder q, elbow -0.5q+0.1.
        a=q; b=.5*q+.1
        return 9.80665*(1*.1*np.sin(a)+.5*(.2*np.sin(a)+.075*np.sin(b))+.8*(.2*np.sin(a)+.15*np.sin(b)))
    expected=(potential(angle+1e-6)-potential(angle-1e-6))/2e-6
    assert s['actuator_efforts']['shoulder']==pytest.approx(expected,rel=1e-7)
    assert k['positions']['elbow']==pytest.approx(-.05)
    assert 'elbow' not in s['actuator_efforts']


def test_frames_rpy_and_world_force_offset_moment(tmp_path):
    r=robot(tmp_path);k=forward_kinematics(r,{'shoulder':0,'elbow':0},transform([1,2,3],[0,0,np.pi/2]))
    assert np.allclose(k['frames']['forearm'][:3,3],[1,2.2,3])
    s=static_wrenches(r,k,[0,0,-1],loads=[{'name':'pull','link':'forearm','force_n':[10,0,0],'moment_n_m':[0,0,2],'position_m':[1,2.35,3],'frame':'world'}])
    assert s['world_external_wrench'][0]==pytest.approx(10)
    assert s['world_external_wrench'][5]==pytest.approx(-23.5+2)


def test_prismatic_holding_force(tmp_path):
    p=tmp_path/'slider.urdf'
    p.write_text('<robot name="slider"><link name="base"/><link name="slide"><inertial><mass value="2"/><inertia ixx=".01" iyy=".01" izz=".01" ixy="0" ixz="0" iyz="0"/></inertial></link><joint name="lift" type="prismatic"><parent link="base"/><child link="slide"/><axis xyz="0 0 1"/><limit lower="0" upper="1" effort="100" velocity="1"/></joint></robot>')
    r=read_urdf(p,massless_links=['base']);k=forward_kinematics(r,{'lift':.2});s=static_wrenches(r,k,[0,0,-9.80665])
    assert k['frames']['slide'][2,3]==pytest.approx(.2)
    assert s['actuator_efforts']['lift']==pytest.approx(19.6133)


@pytest.mark.parametrize('q',[{}, {'shoulder':4,'elbow':0},{'shoulder':False,'elbow':0},{'shoulder':0,'elbow':0,'extra':0}])
def test_unknown_missing_and_out_of_limit_pose_rejected(tmp_path,q):
    with pytest.raises(ValueError):forward_kinematics(robot(tmp_path),q)


def test_unknown_mass_not_assumed_zero_and_mimic_cycle_rejected(tmp_path):
    p=tmp_path/'arm.urdf';p.write_text(arm_urdf())
    with pytest.raises(ValueError,match='inertial'):read_urdf(p)
    r=robot(tmp_path,'<mimic joint="elbow"/>')
    with pytest.raises(ValueError,match='cycle'):forward_kinematics(r,{'shoulder':0})


def test_package_mesh_resolution_is_explicit(tmp_path):
    (tmp_path/'part.stl').write_bytes(b'fixture')
    assert resolve_asset('package://parts/part.stl',tmp_path/'r.urdf',{'parts':str(tmp_path)})==tmp_path/'part.stl'
    with pytest.raises(ValueError,match='package root'):resolve_asset('package://unknown/part.stl',tmp_path/'r.urdf',{})
    with pytest.raises(ValueError,match='escapes'):resolve_asset('package://parts/../part.stl',tmp_path/'r.urdf',{'parts':str(tmp_path)})


def test_point_contacts_tipping_and_payload_limit():
    points=[[-.1,-.1,0],[-.1,.1,0],[.1,-.1,0],[.1,.1,0]]
    fixed=np.array([0,0,-100,0,0,0.])
    variable=np.array([0,0,-10,0,3,0.]) # 10 N payload at x=0.3 m
    r=contact_equilibrium(points,.5,fixed+variable)
    assert r['feasible'] and r['relative_equilibrium_residual']<1e-8
    limit=contact_equilibrium(points,.5,fixed,variable)
    assert limit['payload_scale_limit']==pytest.approx(5.)
    assert not contact_equilibrium(points,.5,fixed+6*variable)['feasible']


def test_contact_friction_is_conservative_and_discloses_failure():
    points=[[-.1,-.1,0],[-.1,.1,0],[.1,-.1,0],[.1,.1,0]]
    assert contact_equilibrium(points,.5,[20,20,-100,0,0,0])['feasible']
    assert not contact_equilibrium(points,.5,[30,30,-100,0,0,0])['feasible']
