"""Observable contradictions, missing coverage and real filesystem resume boundaries."""
from pathlib import Path
from copy import deepcopy
import json,shutil
from types import SimpleNamespace
import pytest
from simplecae.case import write_json,sha256
from simplecae.signals import design_signal,structural_contract,compare_results
from test_signals import result

def test_stored_contract_cannot_hide_relaxed_criteria(tmp_path):
    a=result();a['task_contract']=deepcopy(structural_contract(a['case']))
    b=deepcopy(a);b['case']['criteria']['max_displacement_mm']*=10
    paths=[tmp_path/'a.json',tmp_path/'b.json']
    for p,r in zip(paths,[a,b]):write_json(p,r)
    comparison=compare_results(paths)
    assert not comparison['comparable']
    assert comparison['candidates'][1]['signal']['feasible_under_stated_model'] is None

@pytest.mark.parametrize('damage',['status','verification','contract'])
def test_unresolved_evidence_never_keeps_an_available_capacity(damage):
    r=result();r['assessment']['conditional_body_limit']={'available':True,'load_pattern_scale_factor':9.,'vertical_payload_mass_equivalent_kg':90.,'withheld_reasons':[]}
    if damage=='status':r['status']='invalid'
    if damage=='verification':r['assessment']['verification']['mesh_converged']=False
    if damage=='contract':
        r['task_contract']=deepcopy(structural_contract(r['case']));r['case']['loads'][0]['total_force_n'][2]*=2
    s=design_signal(r)
    assert not s['valid_for_comparison'] and s['bottleneck_margin'] is None
    assert not s['conditional_limit']['available']
    assert s['conditional_limit']['load_pattern_scale_factor'] is None
    assert s['conditional_limit']['vertical_payload_mass_equivalent_kg'] is None

def test_absent_robot_poses_do_not_pass():
    r={'analysis':'urdf_static','status':'pass_under_stated_model',
       'case':{'poses':[{'name':'home','joints':{}}]},'task_contract':{'effective_actuator_limits':{}},'poses':[]}
    s=design_signal(r);assert not s['valid_for_comparison'] and s['feasible_under_stated_model'] is None

@pytest.mark.parametrize('missing',['actuator','component','contact'])
def test_missing_requested_robot_evidence_is_not_usable(missing):
    from simplecae.robot import load_robot_case
    root=Path(__file__).resolve().parents[1]
    c=load_robot_case(root/'examples/robots/one-link.robot.json');c['poses']=c['poses'][:1]
    child=result();child['robot_load_transfer']={'link':'arm'}
    pose={'name':'extended','status':'pass_under_stated_model','actuator_efforts':{'shoulder':{'utilization':.03}},'contact_equilibrium':None,'components':[child]}
    r={'analysis':'urdf_static','case':c,'status':'pass_under_stated_model','poses':[pose]}
    assert design_signal(r)['valid_for_comparison']
    if missing=='actuator':pose['actuator_efforts']={}
    if missing=='component':pose['components']=[]
    if missing=='contact':c['base']['type']='contacts'
    s=design_signal(r);assert not s['valid_for_comparison'] and s['feasible_under_stated_model'] is None

def test_omitted_alternative_case_cannot_pass_envelope():
    r=result();c=r['case'];c['load_cases']=[{'name':'left','loads':c['loads']},{'name':'right','loads':c['loads']}]
    s=design_signal({'analysis':'load_case_envelope','case':c,'status':'pass_under_stated_model',
        'cases':[{'name':'left','case':c,'status':r['status'],'assessment':r['assessment']}],'common_payload_scale_limit':2})
    assert not s['valid_for_comparison'] and not s['conditional_limit']['available']

def test_low_space_preflight_retains_files_and_does_not_delete(tmp_path,monkeypatch):
    from simplecae.resources import require_storage,RESERVE_BYTES
    p=tmp_path/'existing-evidence.dat';p.write_bytes(b'preserve original evidence')
    monkeypatch.setattr('simplecae.resources.shutil.disk_usage',lambda p:SimpleNamespace(free=RESERVE_BYTES-1))
    with pytest.raises(OSError,match='Insufficient disk space'):require_storage(tmp_path)
    assert p.read_bytes()==b'preserve original evidence'

def test_aggregate_pass_cannot_hide_failed_child():
    r=result();r['assessment']['status']=r['status']='fail_under_stated_model'
    s=design_signal({'analysis':'load_case_envelope','case':r['case'],'status':'pass_under_stated_model',
        'cases':[{'name':'failed','case':r['case'],'status':r['status'],'assessment':r['assessment']}],'common_payload_scale_limit':2})
    assert not s['valid_for_comparison'] and s['feasible_under_stated_model'] is None

def test_campaign_resume_requires_recorded_sources_not_just_physics(tmp_path,monkeypatch):
    from simplecae.campaign import run_campaign
    # Exercise actual immutable attempt/receipt I/O; replace only numerical work.
    model=tmp_path/'part.step';model.write_text('source-bound fixture')
    case=tmp_path/'case.json';write_json(case,{'schema_version':'fixture','model':{'path':str(model)},'provenance':{'task_id':'original'}})
    manifest=tmp_path/'campaign.json'
    def manifest_write():write_json(manifest,{'schema_version':'simplecae-campaign-1.0','title':'resume','items':[{'id':'part','case_path':str(case),'case_sha256':sha256(case)}]})
    manifest_write();solver=tmp_path/'ccx';solver.write_text('fixture')
    monkeypatch.setattr('simplecae.api.check_case',lambda p:json.loads(Path(p).read_text()))
    monkeypatch.setattr('simplecae.cache.cache_key',lambda *a:'same-numerical-physics')
    monkeypatch.setattr('simplecae.solver.find_ccx',lambda p:solver)
    def child(command,**kwargs):
        d=Path(command[command.index('--out')+1]);d.mkdir()
        c=json.loads(case.read_text());write_json(d/'signal.json',{'analysis_status':'pass_under_stated_model','valid_for_comparison':True,'physical_conditions_verified':False,'task_id':c['provenance']['task_id']})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('simplecae.campaign.run_owned_worker',child)
    first=run_campaign(manifest,tmp_path/'runs',preview=False)
    unchanged=run_campaign(manifest,tmp_path/'runs',preview=False,resume=True)
    assert unchanged['items'][0]['resumed']
    c=json.loads(case.read_text());c['provenance']['task_id']='new-task';write_json(case,c);manifest_write()
    changed=run_campaign(manifest,tmp_path/'runs',preview=False,resume=True)
    assert not changed['items'][0]['resumed']
    assert changed['items'][0]['signal']['task_id']=='new-task'
    assert changed['items'][0]['output_relative_path']!=first['items'][0]['output_relative_path']
