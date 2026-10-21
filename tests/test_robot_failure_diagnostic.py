import json
import pytest
from pathlib import Path
from simplecae.case import write_json
from simplecae.benchmarks import bar_case
from simplecae.robot import analyze_robot
from simplecae.schemas import check_contract

@pytest.mark.parametrize('elastic',[False,True])
def test_invalid_component_error_reaches_the_robot_public_result(monkeypatch,tmp_path,elastic):
    urdf=tmp_path/'r.urdf';urdf.write_text('''<robot name="slider"><link name="base"/><link name="slide"><inertial><mass value="2"/><inertia ixx=".01" iyy=".01" izz=".01" ixy="0" ixz="0" iyz="0"/></inertial></link><joint name="lift" type="prismatic"><parent link="base"/><child link="slide"/><axis xyz="0 0 1"/><limit lower="0" upper="1" effort="100" velocity="1"/></joint></robot>''')
    (tmp_path/'part.step').write_text('Unused model fixture; component solve is replaced by the observed failure')
    write_json(tmp_path/'part.json',bar_case('part',[1,0,0],[5,4,3]))
    case={'schema_version':'robot-1.0','model':{'path':'r.urdf'},'massless_links':['base'],'poses':[{'name':'home','joints':{'lift':0}}],
        'gravity_m_s2':[0,0,-9.8],'base':{'type':'fixed'},'conditions':dict.fromkeys(('inertials_verified','actuator_ratings_verified','mount_verified','poses_verified'),False),
        'components':[{'link':'slide','case_path':'part.json','ports':{}}],'required_components':['slide']}
    if elastic:
        case['probes']=[{'name':'tip','type':'surface_average','link':'slide',
            'component_selector':{'type':'plane','axis':'x','position_mm':100},'max_displacement_mm':.1}]
        case['elastic_transfer']={'rigid_links':['base'],'rigid_joints':[],'joints_locked_verified':False,
            'joint_compliance':{'lift':{'linear_stiffness_n_m':10000,'reference':'Declared test stiffness, unmeasured','verified':False}},
            'reference':'Failure diagnostic fixture','max_rotation_rad':.01,'max_section_warping_mm':.001}
    p=tmp_path/'case.json';write_json(p,case)
    def failed(*args,**kwargs):return {'status':'invalid','error':'ValueError: probe point is outside modeled material (hole)',
        'robot_load_transfer':{'link':'slide','directory_name':'component-slide'}}
    monkeypatch.setattr('simplecae.robot.component_analysis',failed)
    r=analyze_robot(p,tmp_path/'out',preview=False)
    assert r['status']=='invalid' and 'home/slide' in r['error'] and 'hole' in r['error']
    check_contract(r,'result')
    assert r['evaluation_signal']['bottleneck_margin'] is None
    if elastic:assert r['coverage']['first_order_chain_displacement_available'] is False
