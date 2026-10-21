import copy,json
from pathlib import Path
import numpy as np
import pytest
from simplecae.contact import completed_steps,summarize as contact_summary,validate_control
from simplecae.elastic_transfer import fit_section,propagate,add_ancestor_motion,validate
from simplecae.solver import dat_real,parse_dat
from simplecae.signals import structural_contract,robot_contract,recorded_contract_matches
from simplecae.robot import transform


@pytest.mark.parametrize('token,value',[('1.234567-100',1.234567e-100),('-1.234567+103',-1.234567e103),('.123D-12',.123e-12),('1.2E-03',.0012),('14',14)])
def test_ccx_fortran_real_keeps_finite_extreme_exponents(token,value):
    assert dat_real(token)==pytest.approx(value,rel=1e-14,abs=0)


def test_partial_contact_load_steps_cannot_be_called_complete(tmp_path):
    p=tmp_path/'job.sta';p.write_text('1 1 1 2 1.0 1.0 1.0\n2 1 1 3 1.5 .5 .5\n')
    with pytest.raises(RuntimeError,match='full load'):completed_steps(p,2)
    p.write_text('1 1 1 2 1.0 1.0 1.0\n2 1 1 3 2.0 1.0 1.0\n')
    assert completed_steps(p,2)[2]['step_time']==1


def test_stage_fields_do_not_leak_previous_steps_or_contact_tables(tmp_path):
    p=tmp_path/'job.dat'
    def block(time,u):return f'displacements (vx,vy,vz) time {time}\n1 {u} 0 0\nforces (fx,fy,fz) time {time}\n1 0 0 0\nstresses (elem,ip,s) time {time}\n1 1 0 0 0 0 0 0\nstrains (elem,ip,e) time {time}\n1 1 0 0 0 0 0 0\n'
    p.write_text(block(1,'1.2-100')+'relative contact displacement (x) time 1\n99 10 20 30\n'+block(2,'2.0'))
    assert parse_dat(p,time=1)['displacements'][1][0]==pytest.approx(1.2e-100,abs=0)
    assert parse_dat(p)['displacements'][1][0]==2
    assert set(parse_dat(p,time=1)['reactions'])=={1}
    with pytest.raises(RuntimeError,match='incomplete'):parse_dat(p,time=3)


def test_empty_contact_output_never_means_zero_pressure_without_material_opening(tmp_path):
    p=tmp_path/'job.dat';p.write_text('')
    c={'name':'pair','surfaces':{'slave':[[1,1]]},'normal':[1,0,0],'initial_gap_mm':0,
       'gap_samples':[{'slave_nodes':[1],'slave_weights':[1.],'master_nodes':[2],'master_weights':[1.]}]}
    assert not contact_summary(p,[c])[0]['available']
    assert not contact_summary(p,[c],displacements={1:np.zeros(3),2:np.zeros(3)})[0]['available']
    result=contact_summary(p,[c],displacements={1:np.array([.01,0,0]),2:np.zeros(3)})[0]
    assert result['available'] and result['minimum_gap_mm']==.01 and result['peak_pressure_mpa']==0
    assert not contact_summary(p,[c],displacements={1:np.array([-.01,0,0]),2:np.zeros(3)})[0]['available']


@pytest.mark.parametrize('control',[{'initial_increment':.01,'minimum_increment':.1},{'maximum_increment':2},{'max_increments':True},{'max_increments':0}])
def test_invalid_contact_time_controls_rejected(control):
    with pytest.raises(ValueError):validate_control({'connections':[{'type':'frictionless_contact'}],'contact_control':control})


def test_rigid_section_fit_recovers_translation_and_three_rotations():
    p=np.array([[0,-2,-1],[0,2,-1],[0,2,1],[0,-2,1]],float)+[50,10,20]
    theta=np.array([.002,-.003,.004]);t=np.array([.01,.02,-.03]);center=p.mean(axis=0)
    fit=fit_section(p,t+np.cross(theta,p-center),np.ones(4))
    assert np.allclose(fit['rotation_rad'],theta,atol=1e-14)
    assert np.allclose(fit['translation_mm'],t,atol=1e-14)
    assert fit['warping_rms_mm']<1e-14
    u=np.cross(theta,p-center);u[:,0]+=.001*(p[:,1]-10)*(p[:,2]-20)
    assert fit_section(p,u,np.ones(4))['warping_rms_mm']>.001


def test_collinear_section_cannot_hide_unobservable_rotation():
    with pytest.raises(ValueError,match='resolve'):fit_section([[0,0,0],[1,0,0],[2,0,0]],np.zeros((3,3)),[1,1,1])


@pytest.mark.parametrize('yaw',[0,np.pi/2])
def test_transmitted_rotation_moves_downstream_points_at_actual_posed_lever_arm(yaw):
    r=transform([0,0,0],[0,0,yaw]);rot=r[:3,:3]
    frames={n:transform((rot@np.array([x,0,0])).tolist(),[0,0,yaw]) for n,x in [('a',0),('b',.05),('c',.1)]}
    robot={'root':'a','children':{'a':['ab'],'b':['bc'],'c':[]},'joints':{'ab':{'child':'b'},'bc':{'child':'c'}}}
    component={'a':{'robot_load_transfer':{'world_from_component':r.tolist()}}}
    fit={('a','ab'):{'center_mm':[50,0,0],'translation_mm':[0,.01,0],'rotation_rad':[0,0,.001]}}
    states=propagate(robot,{'frames':frames},component,fit)
    assert np.allclose(states['c'][0],rot@[0,.06,0])
    vectors={'point':np.zeros(3)};metadata={'point':{'link':'c','point_world_m':(rot@np.array([.15,0,0])).tolist()}}
    add_ancestor_motion(vectors,metadata,{'frames':frames},states)
    assert np.allclose(vectors['point'],rot@[0,.11,0])


def test_incomplete_elastic_path_or_closed_actuation_loop_cannot_silently_use_rigid_links():
    c={'elastic_transfer':{'rigid_links':['base'],'joints_locked_verified':False,'max_rotation_rad':.01,'max_section_warping_mm':.01,'reference':'declared model'},'base':{'type':'fixed'},'probes':[{}]}
    with pytest.raises(ValueError,match='every URDF link'):validate(c,{'links':{'base':{},'arm':{}}})
    c['actuation_reactions']=[{}]
    with pytest.raises(ValueError,match='fixed-base tree'):validate(c)


def test_new_mechanics_controls_are_part_of_task_contract_not_geometry_metadata():
    c={'contact_control':{'initial_increment':.1}}
    assert structural_contract(c)!=structural_contract(dict(c,contact_control={'initial_increment':.2}))
    robot={'joints':{},'links':{}};c={'components':[],'elastic_transfer':{'joints_locked_verified':False}}
    contract=robot_contract(c,robot)
    assert recorded_contract_matches(c,contract,True)
    changed=copy.deepcopy(c);changed['elastic_transfer']['joints_locked_verified']=True
    assert not recorded_contract_matches(changed,contract,True)


def test_campaign_cli_exposes_invalid_items_and_nonzero_exit(monkeypatch,tmp_path,capsys):
    from simplecae import cli,campaign
    monkeypatch.setattr(campaign,'run_campaign',lambda *a,**kw:{'status':'invalid','status_counts':{'invalid':1},'all_results_valid':False,'completed_count':1,'requested_count':1})
    assert cli.main(['campaign',str(tmp_path/'missing.json'),'--out',str(tmp_path/'out')])==2
    output=json.loads(capsys.readouterr().out)
    assert output['completed_count']==1 and output['status_counts']['invalid']==1 and not output['all_results_valid']


@pytest.mark.parametrize('damage',['linear_record','missing_step','missing_contact_output','capacity'])
def test_contact_signal_cannot_promote_linear_or_incomplete_history(damage):
    from test_signals import result
    from simplecae.signals import design_signal
    r=result();r['analysis']='frictionless_contact_assembly';r['case']['connections']=[{'name':'seat','type':'frictionless_contact'}]
    r['assessment']['conditional_body_limit']={'available':False,'load_pattern_scale_factor':None,'withheld_reasons':[]}
    for level in r['levels']:
        level['solver']={'completed_load_steps':{'1':{'step_time':1.}}}
        level['results']['contact']=[{'name':'seat','available':True}]
    assert design_signal(r)['valid_for_comparison']
    if damage=='linear_record':r['analysis']='linear_static'
    elif damage=='missing_step':r['levels'][0]['solver']['completed_load_steps']={}
    elif damage=='missing_contact_output':r['levels'][0]['results']['contact']=[]
    else:r['assessment']['conditional_body_limit'].update(available=True,load_pattern_scale_factor=100.)
    signal=design_signal(r)
    assert not signal['valid_for_comparison'] and signal['bottleneck_margin'] is None
    assert not signal['conditional_limit']['available'] and signal['conditional_limit']['load_pattern_scale_factor'] is None


@pytest.mark.parametrize('damage',['scope','frames','screen','probe_coverage'])
def test_robot_signal_requires_actual_qualified_transfer_and_named_probe_coverage(damage):
    from test_signals import result
    from simplecae.signals import design_signal
    from simplecae.robot import load_robot_case
    root=Path(__file__).resolve().parents[1];c=load_robot_case(root/'examples/robots/one-link.robot.json');c['poses']=c['poses'][:1]
    c['probes']=[{'name':'tip','type':'point','link':'arm','point_m':[.1,0,0]}]
    c['elastic_transfer']={'rigid_links':['base'],'joints_locked_verified':False,'max_rotation_rad':.01,'max_section_warping_mm':.001,'reference':'numerical fixture'}
    child=result();child['robot_load_transfer']={'link':'arm'}
    measured={'status':'pass_under_stated_model','measurement_scope':'first_order_section_frames','probes':[{'name':'tip'}],'criterion_assessments':{},
              'elastic_transfer':{'rotation_and_warping_screens_passed':True,'frame_mesh_comparisons':[True,True]}}
    pose={'name':c['poses'][0]['name'],'status':'pass_under_stated_model','actuator_efforts':{'shoulder':{'utilization':.03}},'contact_equilibrium':None,'components':[child],'task_probe_assessment':measured}
    r={'analysis':'urdf_static','case':c,'status':'pass_under_stated_model','poses':[pose]}
    assert design_signal(r)['valid_for_comparison']
    if damage=='scope':measured['measurement_scope']='independent_component_fields'
    elif damage=='frames':measured['elastic_transfer']['frame_mesh_comparisons']=[]
    elif damage=='screen':measured['elastic_transfer']['rotation_and_warping_screens_passed']=False
    else:measured['probes']=[]
    signal=design_signal(r)
    assert not signal['valid_for_comparison'] and signal['bottleneck_margin'] is None and signal['feasible_under_stated_model'] is None
