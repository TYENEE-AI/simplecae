import copy
import json
from pathlib import Path
import pytest
from simplecae.signals import design_signal,compare_results
from simplecae.benchmarks import bar_case
from simplecae.assessment import assess


def result():
    case=bar_case('bar',[0,0,-100],[5,4,3]);case['schema_version']='2.0'
    case['provenance']={'task_id':'fixture-task','revision':'base'}
    levels=[{'mesh':{'mesh_volume_mm3':10000.,'mass_kg':None},'results':{'max_von_mises_mpa':10.,'max_displacement_mm':.02,
        'minimum_bbox_extent_mm':10.,'max_strain_norm':.0001,'force_balance_relative_error':1e-8,'moment_balance_relative_error':1e-8,
        'peak_element_centroid_mm':[0,1,2]}} for _ in range(3)]
    a=assess(case,levels)
    return {'analysis':'linear_static','case':case,'levels':levels,'assessment':a,'status':a['status']}


@pytest.mark.parametrize('gate',['mesh_converged','force_and_moment_balance_passed','small_response_screen_passed'])
def test_no_favorable_margin_when_a_gate_disagrees_with_status(gate):
    r=result();r['assessment']['verification'][gate]=False
    s=design_signal(r)
    assert not s['valid_for_comparison'] and s['bottleneck_margin'] is None
    assert s['feasible_under_stated_model'] is None


def test_contact_feedback_names_unresolved_stage_gate_without_claiming_missing_steps():
    r = result()
    r["case"]["connections"] = [{"name": "pad", "type": "frictionless_contact"}]
    r["stage_assessments"] = {"service": {"verification": {
        "mesh_converged": False, "force_and_moment_balance_passed": True,
        "small_response_screen_passed": True}}}
    r["status"] = "indeterminate"
    signal = design_signal(r)
    gap = next(f for f in signal["feedback"] if f.get("scope") == "contact_history")
    assert gap["failed_stage_gates"] == ["service/mesh_converged"]
    assert "does not imply" in gap["message"]
    assert not signal["valid_for_comparison"]


def test_assumed_case_can_compare_but_cannot_be_called_physically_verified():
    r=result();r['case']['conditions']['material_verified']=False
    r['assessment']=assess(r['case'],r['levels']);s=design_signal(r)
    assert s['valid_for_comparison'] and not s['physical_conditions_verified']
    assert not s['conditional_limit']['available'] and not s['whole_installation_rating_available']


def test_contract_preserves_task_physics_but_allows_design_revision(tmp_path):
    a=result();b=copy.deepcopy(a);b['case']['model']['path']='revised.step';b['case']['provenance']['revision']='thicker'
    paths=[]
    for name,r in [('a',a),('b',b)]:
        p=tmp_path/(name+'.json');p.write_text(json.dumps(r));paths.append(p)
    assert compare_results(paths)['comparable']
    b['case']['loads'][0]['total_force_n'][2]=-50
    paths[1].write_text(json.dumps(b))
    assert not compare_results(paths)['comparable']


def test_missing_task_id_rejects_cross_task_ranking(tmp_path):
    r=result();r['case']['provenance'].pop('task_id')
    p=tmp_path/'r.json';p.write_text(json.dumps(r))
    assert not compare_results([p,p])['comparable']


def test_mathematical_calibration_cannot_claim_physical_verification():
    r=result();r['case']['material']['calibration']={'kind':'mathematical_reference','reference':'prescribed constants','applicability':'synthetic case'}
    s=design_signal(r)
    assert s['valid_for_comparison'] and not s['physical_conditions_verified']


def test_envelope_preserves_omissions_and_mathematical_calibration_scope():
    r=result();r['case']['material']['calibration']={'kind':'mathematical_reference'}
    envelope={'analysis':'load_case_envelope','status':r['status'],'case':r['case'],
        'cases':[{'name':'one','status':r['status'],'assessment':r['assessment']}],
        'common_payload_scale_limit':1.5,'not_assessed':['Fatigue, impact, vibration and dynamic amplification']}
    signal=design_signal(envelope)
    assert signal['valid_for_comparison'] and not signal['physical_conditions_verified']
    assert signal['not_assessed']==envelope['not_assessed']


@pytest.mark.parametrize('gate',['small_response','equilibrium','stiffness_mesh'])
def test_unqualified_displacement_never_prescribes_a_stiffness_multiplier(gate):
    r=result()
    r['case']['criteria']['max_displacement_mm']=.001
    for level in r['levels']:
        if gate=='small_response':level['results']['max_displacement_mm']=1.
        if gate=='equilibrium':level['results']['force_balance_relative_error']=.5
    if gate=='stiffness_mesh':r['levels'][1]['results']['max_displacement_mm']=.1
    r['assessment']=assess(r['case'],r['levels']);r['status']=r['assessment']['status']
    s=design_signal(r)
    assert not s['valid_for_comparison']
    hints=[f for f in s['feedback'] if f.get('scope')=='stiffness']
    assert hints and all(f['kind']!='design_guidance' for f in hints)
    assert all('required_stiffness_multiplier' not in f for f in s['feedback'])
    if gate=='small_response':
        g=next(f for f in s['feedback'] if f['kind']=='model_applicability')
        assert g['failed_gate']=='small_response_screen'
        assert g['evidence']['mesh_converged']


def test_confirmed_stiffness_failure_retains_guidance_when_strength_mesh_is_unresolved():
    r=result();r['case']['criteria']['max_displacement_mm']=.001
    r['levels'][1]['results']['max_von_mises_mpa']=100.
    r['assessment']=assess(r['case'],r['levels']);r['status']=r['assessment']['status']
    s=design_signal(r)
    assert not s['valid_for_comparison']
    assert s['criterion_assessments']['stiffness']['status']=='fail_under_stated_model'
    hint=next(f for f in s['feedback'] if f.get('scope')=='stiffness' and f['kind']=='design_guidance')
    assert hint['required_stiffness_multiplier']==pytest.approx(20.)


def test_confirmed_strength_failure_retains_guidance_when_displacement_is_unresolved():
    r=result();r['case']['material']['yield_strength_mpa']=1.
    r['levels'][1]['results']['max_displacement_mm']=.2
    r['assessment']=assess(r['case'],r['levels']);r['status']=r['assessment']['status']
    s=design_signal(r)
    assert not s['valid_for_comparison']
    hint=next(f for f in s['feedback'] if f.get('scope')=='body_strength')
    assert hint['kind']=='constraint_failure'
    assert 'same required loads' in hint['suggestion']


def test_chain_model_boundary_is_separate_from_component_mesh_convergence():
    from simplecae.signals import structural_validity_guidance
    r={'poses':[{'name':'arbitrary_pose','task_probe_assessment':{'elastic_transfer':{
        'rotation_and_warping_screens_passed':False,'frame_mesh_comparisons':[True,True],
        'joint_compliance':{'small_response_passed':True}}}}]}
    g=structural_validity_guidance(r)
    assert g['focus']=='model_validity'
    assert g['failed_gate']=='elastic_transfer_rotation_or_warping'
    assert g['evidence'][0]['frame_mesh_comparisons']==[True,True]
    assert structural_validity_guidance({'poses':[{'name':'rigid_only','task_probe_assessment':None}]}) is None
