"""General regressions observed with multi-part CAD and posed robot tasks."""
import copy,json
from pathlib import Path
import pytest
from simplecae.api import check_case
from simplecae.case import write_json
from simplecae.schemas import check_contract
from simplecae.task import start_task,task_status,brief_task_status,_analysis_note
from test_task import request

ROOT=Path(__file__).resolve().parents[1]

def robot_task(tmp_path):
    path=request(tmp_path,fem=True)
    asset=tmp_path/'link.stl';asset.write_bytes(b'Explicit asset fixture; no meshing in preflight')
    urdf=tmp_path/'robot.urdf'
    urdf.write_text('''<robot name="reference"><link name="base"/><link name="arm"><inertial><mass value="1"/><inertia ixx=".1" iyy=".1" izz=".1" ixy="0" ixz="0" iyz="0"/></inertial><visual><geometry><mesh filename="link.stl"/></geometry></visual></link><joint name="mount" type="fixed"><parent link="base"/><child link="arm"/></joint></robot>''')
    manifest=json.loads(path.read_text(encoding='utf8'))
    manifest['cases']['task-deflection']={'schema_version':'robot-1.0','model':{'path':'robot.urdf'},'massless_links':['base'],
       'poses':[{'name':'held','joints':{}}],'gravity_m_s2':[0,0,-9.80665],'base':{'type':'fixed'},
       'conditions':{key:False for key in ('inertials_verified','actuator_ratings_verified','mount_verified','poses_verified')}}
    write_json(path,manifest)
    return path,asset,manifest

def test_robot_assets_are_bound_even_when_agent_lists_only_cad_source(tmp_path):
    path,asset,_=robot_task(tmp_path)
    s=start_task(path,tmp_path/'workspace')
    state=json.loads((tmp_path/'workspace/task-state.json').read_text(encoding='utf8'))
    assert str(asset.resolve()) in state['bindings']
    asset.write_bytes(b'Changed between source preparation and solve')
    s=task_status(tmp_path/'workspace')
    assert str(asset.resolve()) in s['changed_inputs'] and s['status']=='insufficient_evidence'
    assert all(c['next_action']=='start_fresh_revision' for c in s['checks'])
    assert not s['whole_product_pass_available'] and not (tmp_path/'workspace/runs').exists()

def test_missing_urdf_asset_fails_before_workspace_or_worker(tmp_path):
    path,asset,_=robot_task(tmp_path);asset.unlink()
    with pytest.raises(ValueError,match='asset|mesh'):
        start_task(path,tmp_path/'workspace')
    assert not (tmp_path/'workspace').exists()

def test_legacy_workspace_without_asset_binding_is_withheld_not_migrated_to_pass(tmp_path):
    from simplecae.signals import digest
    path,asset,_=robot_task(tmp_path);start_task(path,tmp_path/'workspace')
    sp=tmp_path/'workspace/task-state.json';state=json.loads(sp.read_text(encoding='utf8'))
    del state['bindings'][str(asset.resolve())];state['revision_sha256']=digest(state['bindings']);write_json(sp,state)
    s=task_status(tmp_path/'workspace')
    assert any('Unbound numerical dependency' in p for p in s['changed_inputs'])
    assert s['status']=='insufficient_evidence' and sp.exists()

def test_brief_external_failure_retains_bounded_explanation_and_full_record_path(tmp_path):
    from test_task import evidence
    from simplecae.task import record_task_check
    s=start_task(request(tmp_path),tmp_path/'workspace')
    p=evidence(tmp_path,s,outcome='fail');e=json.loads(p.read_text(encoding='utf8'))
    e['summary']='Actual gap0.2mm below0.5mm requirement. '+('Detail '*100);write_json(p,e)
    s=record_task_check(tmp_path/'workspace',s['checks'][0]['id'],p)
    brief=brief_task_status(s)['checks'][0]
    assert brief['outcome']=='fail' and 'gap0.2mm' in brief['summary']
    assert brief['summary_truncated'] and len(brief['summary'])==500
    assert Path(brief['evidence_record_path']).is_file() and not s['whole_product_pass_available']

def test_nested_component_units_are_checked_before_worker(tmp_path):
    path,_,manifest=robot_task(tmp_path)
    case=json.loads((ROOT/'examples/preview/fail.case.json').read_text())
    case['model']['path']=str(ROOT/'examples/preview/beam.step')
    case['loads'][0]['total_force_n'][0]='2kg'
    write_json(tmp_path/'component.json',case)
    manifest['cases']['task-deflection']['components']=[{'link':'arm','case_path':'component.json','ports':{}}]
    write_json(path,manifest)
    with pytest.raises(ValueError,match='invalid numerical input'):
        start_task(path,tmp_path/'workspace')
    assert not (tmp_path/'workspace').exists()

@pytest.mark.parametrize('value',[True,False,'true',1,None])
def test_mesh_boundary_option_is_explicit_boolean_and_never_changes_limits(tmp_path,value):
    case=json.loads((ROOT/'examples/preview/fail.case.json').read_text())
    case['model']['path']=str(ROOT/'examples/preview/beam.step')
    criteria=copy.deepcopy(case['criteria']);case['mesh']['preserve_boundary_nodes']=value
    write_json(tmp_path/'case.json',case)
    if type(value) is bool:
        result=check_case(tmp_path/'case.json')
        assert result['mesh']['preserve_boundary_nodes'] is value and result['criteria']==criteria
    else:
        with pytest.raises(ValueError):check_case(tmp_path/'case.json')

def test_short_analysis_note_keeps_raw_error_and_missing_criteria(tmp_path):
    p=tmp_path/'result.json';write_json(p,{'status':'invalid','error':'Native mesh rejected; actual diagnostic'})
    review={'execution':{'state':'analysis_failed','worker_started':True},'result':{'path':str(p)}}
    usage={'status':'insufficient_evidence','governing':None,'confirmed_failed_criteria':{},'missing_result_criteria':['probe:tip'],
       'unresolved_result_criteria':[],'cad_iteration':{'reanalysis_trigger':'after_input_or_analysis_repair_if_needed'}}
    note=_analysis_note(review,usage)
    assert note['error']=='Native mesh rejected; actual diagnostic'
    assert note['missing_result_criteria']==['probe:tip'] and note['result_path']==str(p)
    assert note['reanalysis_trigger']=='after_input_or_analysis_repair_if_needed'

def test_partial_confirmed_failures_survive_an_unresolved_aggregate(tmp_path):
    review={'execution':{'state':'completed','worker_started':True}}
    usage={'status':'insufficient_evidence','governing':{'name':'strength'},'confirmed_failed_criteria':{'strength':{'status':'fail_under_stated_model'}},
       'missing_result_criteria':['probe:tip'],'unresolved_result_criteria':[],'cad_iteration':{'reanalysis_trigger':'after_input_or_analysis_repair_if_needed'}}
    note=_analysis_note(review,usage)
    assert note['confirmed_failed_criteria']['strength']['status']=='fail_under_stated_model'
    assert note['missing_result_criteria']==['probe:tip']
