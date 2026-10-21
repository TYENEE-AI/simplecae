"""Adverse software contracts; native references live in bolt_friction_validation."""
import copy
import json
from pathlib import Path
import numpy as np
import pytest
from simplecae import bolts,contact
from simplecae.assembly import load_assembly_case
from simplecae.assessment import assess
from simplecae.signals import design_signal,structural_contract

ROOT=Path(__file__).resolve().parents[1]


def case(name='bolt-friction-combined'):
    return load_assembly_case(ROOT/'examples/joints'/f'{name}.case.json')


@pytest.mark.parametrize('damage',['negative_k','missing_reference','nonunit_axis','same_body','duplicate','no_contact'])
def test_bolt_input_cannot_infer_omitted_mechanics(damage):
    c=case();b=c['bolts'][0]
    if damage=='negative_k':b['axial_stiffness_n_mm']=-1
    elif damage=='missing_reference':b['reference']=' '
    elif damage=='nonunit_axis':b['axis']=[2,0,0]
    elif damage=='same_body':b['slave']['body']=b['master']['body']
    elif damage=='duplicate':c['bolts'].append(copy.deepcopy(b))
    else:c['connections'][0]['type']='bonded'
    with pytest.raises(ValueError):bolts.validate(c)


@pytest.mark.parametrize('name',['bolt-locked','bolt-preload-only','friction-stick','friction-motion-failure','bolt-world-frame'])
def test_shipped_joint_cases_match_exported_schema_and_semantics(name):
    from simplecae.api import check_case
    check_case(ROOT/'examples/joints'/f'{name}.case.json')


def test_negative_stiffness_diagnostic_identifies_the_actual_json_field(tmp_path):
    from simplecae.api import analyze_case
    from simplecae.case import write_json
    c=case('bolt-locked');c['bolts'][0]['axial_stiffness_n_mm']=-1
    write_json(tmp_path/'negative.json',c)
    with pytest.raises(ValueError) as e:analyze_case(tmp_path/'negative.json',tmp_path/'analysis')
    assert '$.bolts[0].axial_stiffness_n_mm: -1 is less than or equal to the minimum of 0' in str(e.value)
    assert not (tmp_path/'analysis').exists()


def test_native_controls_are_excluded_from_physical_displacement_fields(tmp_path):
    from simplecae.solver import parse_dat
    p=tmp_path/'job.dat'
    p.write_text('displacements (vx,vy,vz) for set NALL and time 3\n1 .01 0 0\n'
                 'displacements (vx,vy,vz) for set BOLT_STATE and time 3\n99 .02 0 0\n'
                 'forces (fx,fy,fz) time 3\n1 0 0 0\nstresses (s) time 3\n1 1 0 0 0 0 0 0\nstrains (e) time 3\n1 1 0 0 0 0 0 0\n')
    assert set(parse_dat(p,time=3,exclude_sets=('BOLT_STATE',))['displacements'])=={1}


def test_physical_fixture_reaction_excludes_internal_generalized_bolt_force():
    from simplecae.solver import summarize
    points=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1],[.5,0,0],[.5,.5,0],[0,.5,0],[0,0,.5],[.5,0,.5],[0,.5,.5]])
    coords={i+1:p for i,p in enumerate(points)};tets={1:list(coords)}
    b={'name':'b','axis':[1,0,0],'ports':{'master':{'weights':{1:1}},'slave':{'weights':{2:1}}}}
    meta={'fixed_dofs':{'1':[1,2,3]},'applied_force_n':[200,0,0],'applied_moment_n_mm':[0,0,0],
          'load_force_scale_n':200,'connection_data':{'bolts':[b]}}
    f={'displacements':{n:np.zeros(3) for n in coords},'reactions':{1:np.array([900.,0,0])},
       'stresses':{(1,i):np.zeros(6) for i in (1,2,3,4)},'strains':{(1,i):np.zeros(6) for i in (1,2,3,4)},
       '_bolt_states':[{'name':'b','force_n':1100}]}
    # Physical equilibrium is -200 fixture +200 external. The generalized
    # preload contribution in native RF is internal and is separately removed.
    r=summarize(f,(coords,tets,{1},{2:np.array([200.,0,0])},meta))
    assert r['reaction_force_n']==[-200.,0,0] and r['force_balance_relative_error']==0
    f['reactions'][1][0]+=20
    assert summarize(f,(coords,tets,{1},{2:np.array([200.,0,0])},meta))['force_balance_relative_error']==pytest.approx(.1)
    f.pop('_bolt_states')
    with pytest.raises(RuntimeError,match='bolt state'):summarize(f,(coords,tets,{1},{2:np.array([200.,0,0])},meta))


def bolt_state(tmp_path,elongation=.01,q=.015):
    p=tmp_path/'job.dat';p.write_text(f'displacements (vx,vy,vz) for set BOLT_STATE and time 1\n9 {elongation} 0 0\n10 {q} 0 0\n')
    b={'name':'b','stretch_node':9,'adjustment_node':10,'stiffness_n_mm':100000,'preload_n':1000,'allowable_tension_n':1500,
       'span_mm':100,'axis':[1,0,0],'ports':{'master':{'weights':{1:1.}},'slave':{'weights':{2:1.}}}}
    return p,b


@pytest.mark.parametrize('damage',['preload','lock','equation','missing'])
def test_bolt_output_requires_preload_locked_adjustment_and_kinematic_consistency(tmp_path,damage):
    p,b=bolt_state(tmp_path);u={1:np.zeros(3),2:np.array([-.005,0,0])}
    initial=bolts.summarize(p,[b],1,displacements=u)
    assert initial[0]['force_n']==1000 and not initial[0]['locked']
    if damage=='preload':p,b=bolt_state(tmp_path,.009)
    elif damage=='lock':p,b=bolt_state(tmp_path,q=.0151)
    elif damage=='equation':u[2][0]=0
    else:p.write_text('')
    with pytest.raises(RuntimeError):bolts.summarize(p,[b],1,initial if damage!='preload' else None,displacements=u)

def test_native_decimal_roundoff_is_bounded_and_does_not_mask_actual_violation(tmp_path):
    p,b=bolt_state(tmp_path);b['preload_n']=400.
    p.write_text('displacements (vx,vy,vz) for set BOLT_STATE and time 1\n9 4.000000E-03 0 0\n10 1.500001E-02 0 0\n'
                 'displacements (vx,vy,vz) for set NALL and time 1\n1 0.000000E+00 0 0\n2 -1.100000E-02 0 0\n')
    # The printed q and U intervals contain q=.015000005, U=-.011000005,
    # whose sum is exactly e=.004. The parsed fields match the DAT tokens.
    u={1:np.zeros(3),2:np.array([-.011,0,0])}
    r=bolts.summarize(p,[b],1,displacements=u)[0]
    assert r['kinematic_residual_mm']>r['base_kinematic_tolerance_mm']
    assert r['kinematic_residual_mm']<=r['base_kinematic_tolerance_mm']+r['output_roundoff_bound_mm']
    p.write_text(p.read_text().replace('-1.100000E-02','-1.100100E-02'));u[2][0]=-.011001
    with pytest.raises(RuntimeError,match='roundoff'):bolts.summarize(p,[b],1,displacements=u)
    assert bolts.native_roundoff('1.234567E-02')==pytest.approx(5e-9)
    assert bolts.native_roundoff('1.234567-100')==pytest.approx(5e-107)
    assert bolts.native_roundoff('.015')==0


def friction_record(tmp_path,shear=2.,native=.0002):
    p=tmp_path/'job.dat';p.write_text(f'relative contact displacement (x) time 2\n7 1 -.0001 0 {native}\ncontact stress (x) time 2\n7 1 10 0 {shear}\n')
    c={'name':'s','type':'frictional_contact','surfaces':{'slave':[[7,1]]},'normal':[1,0,0],
       'initial_gap_mm':0,'friction_coefficient':.2,'footprint_extent_mm':10,
       'gap_samples':[{'slave_nodes':[1],'slave_weights':[1.],'master_nodes':[2],'master_weights':[1.]}]}
    return p,c


def test_friction_task_uses_actual_material_motion_preserving_native_readout(tmp_path):
    p,c=friction_record(tmp_path)
    r=contact.summarize(p,[c],2,displacements={1:np.array([-.0001,.002,0]),2:np.zeros(3)})[0]
    assert r['peak_tangential_displacement_mm']==pytest.approx(.002)
    assert r['peak_native_tangential_displacement_mm']==pytest.approx(.0002)
    assert r['coulomb_bound_passed'] and r['sliding_sample_count']==1
    with pytest.raises(RuntimeError,match='actual material'):contact.summarize(p,[c],2)


def test_friction_never_clips_violated_coulomb_bound_or_accepts_missing_pair_output(tmp_path):
    p,c=friction_record(tmp_path,shear=2.1)
    r=contact.summarize(p,[c],2,displacements={1:np.zeros(3),2:np.zeros(3)})[0]
    assert r['peak_shear_mpa']==2.1 and not r['coulomb_bound_passed']
    p.write_text('relative contact displacement (x) time 2\n7 1 -.0001 0 0\n')
    with pytest.raises(RuntimeError,match='paired'):contact.summarize(p,[c],2)


def test_partial_contact_tables_require_positive_opening_on_every_missing_slave_face(tmp_path):
    p,c=friction_record(tmp_path);c['surfaces']['slave'].append([8,1])
    c['gap_samples'][0]['slave_face']=[7,1]
    c['gap_samples'].append({'slave_nodes':[3],'slave_weights':[1.],'master_nodes':[2],'master_weights':[1.],'slave_face':[8,1]})
    u={1:np.array([-.0001,0,0]),2:np.zeros(3),3:np.array([-.0001,0,0])}
    with pytest.raises(RuntimeError,match='slave face'):contact.summarize(p,[c],2,displacements=u)
    u[3]=np.array([.001,0,0])
    assert contact.summarize(p,[c],2,displacements=u)[0]['output_coverage_verified']


def synthetic_joint_result():
    from test_signals import result
    r=result();r['case']=case();r['analysis']='staged_contact_assembly'
    for level in r['levels']:
        level['results']['bolts']=[{'name':'tie','force_n':1100.,'adjustment_mm':.0151,'utilization':.55,'locked':True,'lock_error_mm':0.,'axis_screen_passed':True}]
        level['results']['contact']=[{'name':'joint','available':True,'output_coverage_verified':True,'peak_pressure_mpa':9.,'minimum_gap_mm':-.00009,
            'peak_tangential_displacement_mm':.00005,'peak_shear_mpa':.5,'sliding_sample_count':0,'coulomb_bound_passed':True,'small_sliding_screen_passed':True}]
        level['solver']={'completed_load_steps':{str(i):{'step_time':1.} for i in (1,2,3)}}
    a=assess(r['case'],r['levels']);r['assessment']=a;r['status']=a['status']
    pre=copy.deepcopy(a);locked=copy.deepcopy(a);r['preload_assessment']=pre;r['stage_assessments']={'preload':pre,'locked':locked,'service':copy.deepcopy(a)}
    a['criterion_assessments'].update({'preload:'+k:v for k,v in pre['criterion_assessments'].items()})
    a['criterion_assessments'].update({'locked:'+k:v for k,v in locked['criterion_assessments'].items()})
    return r


@pytest.mark.parametrize('damage',['missing_lock','q_drift','bolt_axis','missing_bolt','missing_stage','missing_lock_assessment','missing_service_assessment','friction_field','contact_coverage','coulomb','small_slide','capacity','bolt_criterion','wrong_analysis'])
def test_advanced_signal_cannot_promote_incomplete_history_or_scope(damage):
    r=synthetic_joint_result();assert design_signal(r)['valid_for_comparison']
    b=r['levels'][0]['results']['bolts'][0];p=r['levels'][0]['results']['contact'][0]
    if damage=='missing_lock':b['locked']=False
    elif damage=='q_drift':b['lock_error_mm']=.0001
    elif damage=='bolt_axis':b['axis_screen_passed']=False
    elif damage=='missing_bolt':r['levels'][0]['results']['bolts']=[]
    elif damage=='missing_stage':r['levels'][0]['solver']['completed_load_steps'].pop('2')
    elif damage=='missing_lock_assessment':r['stage_assessments'].pop('locked')
    elif damage=='missing_service_assessment':r['stage_assessments'].pop('service')
    elif damage=='friction_field':p.pop('peak_shear_mpa')
    elif damage=='contact_coverage':p['output_coverage_verified']=False
    elif damage=='coulomb':p['coulomb_bound_passed']=False
    elif damage=='small_slide':p['small_sliding_screen_passed']=False
    elif damage=='capacity':r['assessment']['conditional_body_limit'].update(available=True,load_pattern_scale_factor=2.)
    elif damage=='bolt_criterion':r['assessment']['criterion_assessments'].pop('bolt:tie')
    else:r['analysis']='linear_static'
    s=design_signal(r)
    assert not s['valid_for_comparison'] and s['bottleneck_margin'] is None and s['feasible_under_stated_model'] is None


def test_shear_mesh_divergence_cannot_hide_behind_converged_normal_pressure():
    r=synthetic_joint_result();r['levels'][0]['results']['contact'][0]['peak_shear_mpa']=.1
    a=assess(r['case'],r['levels'])
    assert a['status']=='indeterminate' and not a['verification']['mesh_converged']


def test_zero_shear_roundoff_uses_existing_native_resolution_without_clipping():
    r=synthetic_joint_result()
    for l,value in zip(r['levels'],[1e-9,3e-9,8e-9]):l['results']['contact'][0]['peak_shear_mpa']=value
    a=assess(r['case'],r['levels'])
    assert a['verification']['mesh_converged']
    assert r['levels'][-1]['results']['contact'][0]['peak_shear_mpa']==8e-9
    r['levels'][-1]['results']['contact'][0]['peak_shear_mpa']=1e-5
    assert not assess(r['case'],r['levels'])['verification']['mesh_converged']


@pytest.mark.parametrize('option',['cache','reuse_levels'])
def test_contact_history_cannot_use_linear_cache_or_partial_level_reuse(tmp_path,option):
    from simplecae.api import analyze_case
    with pytest.raises(ValueError,match='not qualified'):
        analyze_case(ROOT/'examples/joints/bolt-locked.case.json',tmp_path/'analysis',**{option:tmp_path/'cache'})
    assert not (tmp_path/'analysis').exists()


@pytest.mark.parametrize('field',['bolts','fixture','friction','allowable'])
def test_joint_iteration_contract_retains_all_task_physics_and_allowables(field):
    c=case();other=copy.deepcopy(c)
    if field=='bolts':other['bolts'][0]['axial_stiffness_n_mm']*=2
    elif field=='fixture':other['supports'][1]['service_displacement_mm'][1]*=2
    elif field=='friction':other['connections'][0]['friction_coefficient']*=2
    else:other['bolts'][0]['allowable_tension_n']*=2
    assert structural_contract(c)!=structural_contract(other)
