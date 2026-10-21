"""Boundary probes must be actionable without manufacturing physical acceptance."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from simplecae.case import write_json
from simplecae.schemas import check_contract, ContractError

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('version',['cfd-1.0','thermal-stress-1.0',None,[],{}])
def test_unknown_physics_has_one_actionable_discriminator_error(version):
    with pytest.raises(ContractError) as raised:
        check_contract({'schema_version':version})
    d=raised.value.details
    assert d['code']=='unsupported_schema_version'
    assert 'thermal-solid-1.0' in d['supported_schema_versions']
    assert 'Do not rename' in d['next_action']
    assert 'material' not in str(raised.value)  # No irrelevant branches' missing fields.


def test_discriminator_follows_reordered_contracts(monkeypatch):
    import simplecae.schemas as module
    original=module.contracts()
    original['case']['oneOf'].reverse()
    monkeypatch.setattr(module,'contracts',lambda:original)
    with pytest.raises(ContractError) as raised:module.check_contract({'schema_version':'thermal-solid-1.0'})
    assert any('boundaries' in x for x in raised.value.details['issues'])
    assert not any('supports' in x for x in raised.value.details['issues'])


def test_cli_returns_structured_contract_repair(tmp_path):
    p=tmp_path/'unsupported.json';write_json(p,{'schema_version':'cfd-1.0'})
    proc=subprocess.run([sys.executable,str(ROOT/'scripts/simplecae_cli.py'),'check',str(p)],capture_output=True,encoding='utf-8')
    result=json.loads(proc.stdout)
    assert proc.returncode==2 and result['status']=='invalid'
    assert result['diagnostic']['code']=='unsupported_schema_version'


def test_multi_solid_error_names_existing_recovery_commands(tmp_path):
    from simplecae.geometry import session,inventory
    with session() as g:
        g.model.occ.addBox(0,0,0,1,1,1);g.model.occ.addBox(2,0,0,1,1,1);g.model.occ.synchronize()
        with pytest.raises(ValueError,match='inspect --all-bodies.*assembly-1.0'):inventory(g,tmp_path/'unused.step')


def motion_case():
    from simplecae.assembly import load_assembly_case
    c=load_assembly_case(ROOT/'examples/joints/friction-motion-failure.case.json')
    c['loads']=[];c['supports']=c['supports'][:2]
    c['supports'][1].update(selector={'type':'plane','axis':'x','position_mm':50},dofs=[1,2,3],service_displacement_mm=[-.01,0,0])
    con=c['connections'][0];con['type']='frictionless_contact'
    for key in ('friction_coefficient','tangential_stiffness_n_mm3','max_tangential_displacement_mm'):con.pop(key,None)
    return c


def test_motion_is_valid_loading_but_zero_motion_is_not(tmp_path):
    from simplecae.api import check_case
    c=motion_case();p=tmp_path/'motion.json';write_json(p,c)
    assert check_case(p)['loads']==[]
    c['supports'][1]['service_displacement_mm']=[0,0,0];write_json(p,c)
    with pytest.raises(ValueError,match='nonzero prescribed fixture motion'):check_case(p)


def test_cylindrical_port_rejected_before_mesh(tmp_path,monkeypatch):
    from simplecae.geometry import session,inventory
    from simplecae.assembly import validate_cad_interfaces
    from simplecae.case import sha256
    p=tmp_path/'cylinder.step'
    with session() as g:
        g.model.occ.addCylinder(0,0,0,0,0,10,2);g.model.occ.synchronize();g.write(str(p))
        info=inventory(g,p)
    face=next(f['id'] for f in info['faces'] if f['type']=='Cylinder')
    port={'body':'cylinder','selector':{'type':'face_ids','ids':[face],'geometry_sha256':sha256(p)}}
    c={'bodies':[{'name':'cylinder','model':{'path':str(p)}}], 'connections':[{'name':'bore','master':port,'slave':port}]}
    with pytest.raises(ValueError,match='Cylindrical bore contact.*unsupported'):validate_cad_interfaces(c)


def test_fixture_balance_uses_opposing_reactions_not_residual():
    from simplecae.solver import summarize
    coords={i:np.array(p,dtype=float) for i,p in enumerate([(0,0,0),(1,0,0),(0,1,0),(0,0,1),(.5,0,0),(.5,.5,0),(0,.5,0),(0,0,.5),(.5,0,.5),(0,.5,.5)],1)}
    fields={'displacements':{n:np.zeros(3) for n in coords},'reactions':{1:np.array([-10.,0,0]),2:np.array([10.,0,0])},'stresses':{(1,i):np.zeros(6) for i in range(1,5)},'strains':{(1,i):np.zeros(6) for i in range(1,5)}}
    meta={'load_force_scale_n':0,'service_boundary':{'2:1':-.01},'applied_force_n':[0,0,0],'applied_moment_n_mm':[0,0,0]}
    mesh=(coords,{1:list(coords)},[1,2],{},meta)
    r=summarize(fields,mesh)
    assert r['equilibrium_force_scale_n']==10 and r['force_balance_relative_error']==0
    fields['reactions'][2][0]=9
    assert summarize(fields,mesh)['force_balance_relative_error']==pytest.approx(1/9.5)
    fields['reactions']={1:np.zeros(3),2:np.zeros(3)}
    with pytest.raises(ValueError,match='No positive'):summarize(fields,mesh)


def test_native_pure_displacement_reference(tmp_path):
    from simplecae.api import analyze_case
    from simplecae.solver import find_ccx
    try:ccx=find_ccx()
    except (ValueError,FileNotFoundError):pytest.skip('CalculiX unavailable')
    c=motion_case();p=tmp_path/'motion.json';write_json(p,c)
    result=analyze_case(p,tmp_path/'run',ccx=ccx,predict_capacity=False)
    assert result['status']=='pass_under_stated_model',result.get('error') or result.get('assessment')
    expected=.01/(100/(200000*100)+1/(100000*100))
    for level in result['levels']:
        r=level['results']
        assert r['equilibrium_scale_basis']=='half_sum_fixture_reaction_magnitudes'
        assert r['equilibrium_force_scale_n']==pytest.approx(expected,rel=.015)
        assert r['force_balance_relative_error']<.005
        assert r['moment_balance_relative_error']<.005


def test_brief_retains_assumptions_and_unsupported_reason(tmp_path):
    from simplecae.task import start_task,brief_task_status
    task=json.loads((ROOT/'examples/tasks/bench-fixture.task.json').read_text(encoding='utf-8'))
    check=task['checks'][0]
    check.update(method='information',decision='needs_information',reason='Material supplied by Agent only',assumptions=['Unconfirmed Q235'])
    for k in ('load_path','load_basis','support_basis','result_criteria'):check.pop(k,None)
    task['cases']={};task['sources']=[str(ROOT/'examples/preview/beam.step')]
    p=tmp_path/'task.json';write_json(p,task)
    r=brief_task_status(start_task(p,tmp_path/'task'))
    assert r['checks'][0]['assumptions']==['Unconfirmed Q235']
    assert r['checks'][0]['reason']=='Material supplied by Agent only'
    assert r['checks'][0]['required_for_claim']
    assert r['status']=='insufficient_evidence' and not r['whole_product_pass_available']


def test_curved_heat_power_matches_native_nodal_loads(tmp_path):
    from simplecae.geometry import session,inventory
    from simplecae.case import sha256
    from simplecae.api import analyze_case
    from simplecae.solver import find_ccx
    try:ccx=find_ccx()
    except (ValueError,FileNotFoundError):pytest.skip('CalculiX unavailable')
    step=tmp_path/'hole-plate.step'
    with session() as g:
        box=g.model.occ.addBox(-50,-50,-2.5,100,100,5)
        hole=g.model.occ.addCylinder(0,0,-2.5,0,0,5,5)
        g.model.occ.cut([(3,box)],[(3,hole)]);g.model.occ.synchronize();g.write(str(step))
        info=inventory(g,step)
    selector={'type':'face_ids','ids':[f['id'] for f in info['faces'] if f['type']=='Cylinder'],'geometry_sha256':sha256(step)}
    boundaries=[{'name':'hole','target':'bore','basis':'Five watt benchmark','selector':selector,'type':'heat_power','total_heat_w':5.}]
    for a in ('x','y'):
        for x in (-50,50):boundaries.append({'name':f'{a}{x}','target':'sink','basis':'Prescribed reservoir','selector':{'type':'plane','axis':a,'position_mm':x},'type':'temperature','temperature_c':20.})
    c={'schema_version':'thermal-solid-1.0','mode':'steady','model':{'path':str(step),'units':'mm','expected_bbox_mm':info['bbox_mm']},
       'material':{'name':'reference','basis':'Numerical test only','conductivity_w_mk':167.,'temperature_range_c':[0.,200.]},
       'boundaries':boundaries,'mesh':{'sizes_mm':[8,6.4,5.12]},'criteria':[{'id':'temperature','target':'plate','region':{'type':'body'},'max_temperature_c':100.}],
       'assumptions':['Constant properties'],'not_assessed':['Thermal stress'],
       'conditions':{'properties_verified':False,'boundaries_verified':False},'provenance':{'task_id':'curved-heat-reference'}}
    p=tmp_path/'case.json';write_json(p,c);r=analyze_case(p,tmp_path/'run',ccx=ccx,predict_capacity=False)
    assert r['status']=='pass_under_stated_model',r.get('error') or r.get('verification')
    for level in r['levels']:
        assert level['energy_passed'] and level['quadrature_passed']
        assert level['surface_quadrature_relative_error']<.001
        assert level['energy'][0]['surface_input_w']['hole']==pytest.approx(5.)
    # The same source without a thermal sink must stop before allocating a mesh.
    c['boundaries']=c['boundaries'][:1];write_json(p,c)
    with pytest.raises(ValueError,match='mechanical fixation is not a thermal sink'):
        analyze_case(p,tmp_path/'no-sink',ccx=ccx,predict_capacity=False)
    assert not (tmp_path/'no-sink').exists()
