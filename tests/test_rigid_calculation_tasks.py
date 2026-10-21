"""Generic task/contract behavior; no robot-product routing or fixture exceptions."""
import copy
import json
from pathlib import Path
import pytest
from simplecae.api import analyze_case
from simplecae.case import write_json
from simplecae.signals import compare_results,design_signal
from simplecae.task import start_task,run_task_check,record_task_check
from simplecae.use_plan import validate_computation
from simplecae.design_check import feedback
from test_design_check import context

ROOT=Path(__file__).resolve().parents[1]
def rigid(tmp_path,mass=1,com=(0,0,.1)):
    tmp_path.mkdir(exist_ok=True)
    model=tmp_path/'body.urdf';model.write_text(f'<robot name="rigid"><link name="body"><inertial><origin xyz="{com[0]} {com[1]} {com[2]}"/><mass value="{mass}"/><inertia ixx=".01" iyy=".01" izz=".01" ixy="0" ixz="0" iyz="0"/></inertial></link></robot>')
    c={'schema_version':'robot-1.0','model':{'path':str(model)},'poses':[{'name':'held','joints':{}}],'gravity_m_s2':[0,0,-9.80665], 'base':{'type':'contacts','points_world_m':[[x,y,0] for x in [-.1,.1] for y in [-.1,.1]],'friction_coefficient':.4},'payloads':[{'name':'load','link':'body','mass_kg':1,'center_m':[.22,0,.1]}],'conditions':dict.fromkeys(['inertials_verified','actuator_ratings_verified','mount_verified','poses_verified'],False),'provenance':{'task_id':'same-rigid-load'}}
    path=tmp_path/'case.json';write_json(path,c);return path
def manifest(tmp_path):
    case=rigid(tmp_path)
    p=json.loads((ROOT/'examples/tasks/bench-fixture.task.json').read_text(encoding='utf8'))
    selected=next(c for c in p['checks'] if c['method']=='fem');p['checks']=[selected];selected['id']='balance';selected['method']='calculation';selected['result_criteria']=['held/ground_equilibrium'];p['task_id']='same-rigid-load';p['sources']=[str(case)];p['cases']={'balance':str(case)}
    path=tmp_path/'task.json';write_json(path,p);return path
def test_typed_calculation_completes_and_keeps_ground_failure(tmp_path):
    request=manifest(tmp_path);out=tmp_path/'task'
    s=start_task(request,out)
    plan=json.loads((out/'plan/plan-review.json').read_text(encoding='utf8'))
    assert plan['recommendation']=='targeted_calculation' and plan['calculation_checks']==['balance'] and not plan['fem_checks']
    assert s['checks'][0]['next_action']=='run_calculation'
    s=run_task_check(out,'balance',budget_seconds=30)
    row=s['checks'][0]
    assert row['outcome']=='fail' and row['method']=='calculation'
    assert row['latest']['kind']=='computed' and not s['whole_product_pass_available']
    assert row['latest']['analysis']['governing']=={'name':'held/ground_equilibrium','utilization':None}
    with pytest.raises(ValueError,match='computed'):
        record_task_check(out,'balance',artifacts=[str(request)],outcome='pass',observations=['Override forbidden'],revision_sha256=s['revision_sha256'])
@pytest.mark.parametrize('field,value',[('components',[{}]),('elastic_transfer',{'rigid_links':[]}),('probes',[{}]),('schema_version','2.0')])
def test_calculation_cannot_hide_structural_physics(field,value):
    case={'schema_version':'robot-1.0'};case[field]=value
    with pytest.raises(ValueError,match='rigid robot'):
        validate_computation({'method':'calculation'},case)
@pytest.mark.parametrize('change', ['mass','com','none'])
def test_rigid_mass_or_COM_changes_are_not_a_same_task_design_improvement(tmp_path,change):
    paths=[];rs=[]
    for i in range(2):
        folder=tmp_path/str(i);path=rigid(folder,mass=5 if i and change=='mass' else 1,com=(-.08,0,.1) if i and change=='com' else (0,0,.1))
        rs.append(analyze_case(path,folder/'result',preview=False,predict_capacity=False));paths.append(folder/'result/result.json')
    result=compare_results(paths)
    assert result['comparable'] is (change=='none')
    assert rs[0]['status']=='fail_under_stated_model'
    if change!='none':assert rs[1]['status']=='pass_under_stated_model'
def test_legacy_robot_without_frozen_mass_is_not_ranked(tmp_path):
    path=rigid(tmp_path);r=analyze_case(path,tmp_path/'result',preview=False,predict_capacity=False)
    del r['task_contract']['rigid_link_inertials'];p=tmp_path/'legacy.json';write_json(p,r)
    assert not design_signal(r)['valid_for_comparison']
    assert not compare_results([p,p])['comparable']

def test_FEM_mass_alignment_tolerances_cannot_be_relaxed_between_candidates(monkeypatch):
    from simplecae.signals import robot_contract
    monkeypatch.setattr('simplecae.case.load_case',lambda path:{'schema_version':'2.0'})
    robot={'joints':{},'links':{'part':{'mass_kg':1.,'com_m':[0,0,0]}}}
    c={'components':[{'link':'part','case_path':'unused.json','ports':{}}]}
    original=robot_contract(c,robot)
    c['components'][0]['mass_relative_tolerance']=.8
    assert robot_contract(c,robot)!=original
    c['components'][0].pop('mass_relative_tolerance');c['components'][0]['com_tolerance_mm']=100
    assert robot_contract(c,robot)!=original
    c['components'][0].pop('com_tolerance_mm');robot['links']['part']['mass_kg']=2.
    # Geometry/density/COM alignment is still independently checked by component_analysis;
    # legitimately changing a FEM-covered CAD part is not frozen like an unmodeled ballast.
    assert robot_contract(c,robot)==original
def test_passing_actuator_does_not_generate_a_forced_CAD_change():
    from test_signals import result
    from unittest.mock import patch
    r=result();s=design_signal(r);s['utilizations']={'pose/actuator/axis':.1};s['criterion_assessments']={}
    with patch('simplecae.design_check.design_signal',return_value=s):f=feedback(r,context(),'completed')
    assert not any(x.get('scope')=='actuator_load_path' for x in f['findings'])

def test_unresolved_robot_compact_note_retains_actual_component_location(tmp_path):
    from simplecae.task import _analysis_note
    raw={'poses':[{'name':'pose-a','components':[{'status':'indeterminate','robot_load_transfer':{'link':'body-a'},'assessment':{'verification':{'mesh_converged':False}},'levels':[{'directory':'actual-level','results':{'max_von_mises_mpa':12.,'peak_element_centroid_mm':[1,2,3]}}]}]}]}
    path=tmp_path/'raw.json';write_json(path,raw)
    review={'execution':{'state':'completed'},'result':{'path':str(path)}}
    usage={'status':'insufficient_evidence','cad_iteration':{'reanalysis_trigger':'after_input_or_analysis_repair_if_needed'}}
    note=_analysis_note(review,usage)
    d=note['component_diagnostics'][0]
    assert d['last_field']['peak_element_centroid_mm']==[1,2,3]
    assert d['verification']['mesh_converged'] is False
    assert not note['component_diagnostics_truncated']

def test_large_JSON_compaction_is_lossless_and_keeps_Viewer_size_gate(tmp_path,monkeypatch):
    import simplecae.case as case
    from simplecae.workbench import atomic_json,read_json,MAX_FILE
    monkeypatch.setattr(case,'JSON_PRETTY_LIMIT',16)
    value={'nested':[[1e-200,-1e200,3.141592653589793] for _ in range(5)],'message':'完整热点'}
    for writer,name in [(case.write_json,'result.json'),(atomic_json,'viewer.json')]:
        path=tmp_path/name;writer(path,value)
        assert read_json(path)==value and '\n  ' not in path.read_text(encoding='utf8')
    assert MAX_FILE==128*1024*1024
