"""Engineering counterexamples from the five-persona CAD/CAE campaign."""
import copy
import json
from pathlib import Path

import pytest

from simplecae.benchmarks import bar_case
from simplecae.case import validate_case, write_json, load_case
from simplecae.thermal_solid import _assess, accuracy_policy, contract, read_case


@pytest.mark.parametrize('token,expected', [('8.738447E+01',5e-6),
    ('0.000000E+00',5e-7), ('1.234D-02',5e-6), ('1.234567-120',5e-127)])
def test_native_print_resolution_comes_from_token(token, expected):
    from simplecae.thermal_solid_solver import printed_half_unit
    assert printed_half_unit(token) == pytest.approx(expected, rel=1e-14, abs=0.)


def test_conductive_audit_accounts_for_print_rounding_but_detects_corruption(monkeypatch):
    import numpy as np
    from scipy.sparse import csr_matrix
    from simplecae import thermal_solid_solver as solver
    k = csr_matrix([[1000.,-1000.],[-1000.,1000.]])
    monkeypatch.setattr(solver, 'integration_data', lambda _: (
        np.array([1,2]), {1:0,2:1}, np.ones(2), np.ones(2), csr_matrix(np.eye(2)), k))
    case = {'mode':'steady', 'material':{'conductivity_w_mk':1.}}
    fields = {'temperature_c':{1:80.,2:80.},'rfl_w':{1:.004,2:-.004},
              'temperature_c_half_unit':{1:5e-6,2:5e-6},'rfl_w_half_unit':{1:5e-10,2:5e-10}}
    ledger = solver.energy_history(case, {}, {1:80.,2:80.}, [(0.,fields)], '.')
    assert ledger[0]['max_conductive_field_residual_w'] == .004
    assert ledger[0]['max_conductive_field_excess_w'] == 0.
    fields['rfl_w'] = {1:.1,2:-.1}
    bad = solver.energy_history(case, {}, {1:80.,2:80.}, [(0.,fields)], '.')
    assert bad[0]['max_conductive_field_excess_w'] > .089


def test_programmatic_refinement_accepts_only_representation_roundoff():
    case = bar_case('beam', [0, 0, -1], [3., 3.*.8, 3.*.64])
    validate_case(case)
    case['mesh']['sizes_mm'][1] = 2.400001
    with pytest.raises(ValueError, match='20%'):
        validate_case(case)


def temperature_evidence(temperatures=(60., 60.2, 60.3), limit=70.):
    case = {'mode':'steady','material':{'temperature_range_c':[0,120]},
            'criteria':[{'id':'body','target':'body','region':{'type':'body'},'max_temperature_c':limit}]}
    levels = []
    for i,t in enumerate(temperatures):
        h = {'time_s':0.,'min_temperature_c':25.,'max_temperature_c':t,
             'min_location_mm':[0,0,0],'max_location_mm':[1,1,1],'min_element':1,'max_element':2}
        levels.append({'directory':f'mesh-{i}', 'energy_passed':True,
                       'boundary_temperature_passed':True,'quadrature_passed':True,
                       'histories':{'__body__':[h],'body':[h]}})
    return case, levels


def test_task_accuracy_requires_clear_decision_reserve_and_preserves_energy_gate():
    case, levels = temperature_evidence()
    assert _assess(case, levels, [])[0] == 'indeterminate'
    case['accuracy'] = {'temperature_tolerance_c':.5,'basis':'Coarse thermal design; 5 C reserve'}
    assert _assess(case, levels, [])[0] == 'pass_under_stated_model'
    case['criteria'][0]['max_temperature_c'] = 60.8
    assert _assess(case, levels, [])[0] == 'indeterminate'
    case['criteria'][0]['max_temperature_c'] = 58.
    assert _assess(case, levels, [])[0] == 'fail_under_stated_model'
    case['criteria'][0]['max_temperature_c'] = 70.
    levels[-1]['energy_passed'] = False
    assert _assess(case, levels, [])[0] == 'indeterminate'


def test_accuracy_is_bound_to_task_contract_and_default_is_unchanged():
    case, _ = temperature_evidence()
    case['provenance'] = {'task_id':'thermal'}
    assert accuracy_policy(case) == {'spatial_tolerance_c':.05, 'time_tolerance_c':.05,
                                    'criterion_guard_c':.10001}
    previous = contract(case, {})
    case['accuracy'] = {'temperature_tolerance_c':.5, 'basis':'Explicit task accuracy'}
    assert previous != contract(case, {})
    assert accuracy_policy(case)['criterion_guard_c'] > 1.


@pytest.mark.parametrize('tol', [True, 0., -1., float('inf'), float('nan')])
def test_nonphysical_accuracy_is_rejected(tol):
    with pytest.raises(ValueError):
        accuracy_policy({'accuracy':{'temperature_tolerance_c':tol, 'basis':'invalid'}})


def test_damaged_accuracy_does_not_crash_or_grant_favorable_signal():
    from simplecae.thermal_solid import signal
    result = signal({'status':'invalid','case':{'accuracy':{'basis':'missing tolerance'}}})
    assert not result['valid_for_comparison']
    assert result['feasible_under_stated_model'] is None
    assert result['whole_product_pass_available'] is False


def test_close_temperature_decision_has_actionable_feedback():
    from simplecae.thermal_solid import signal
    case, levels = temperature_evidence(limit=60.8)
    case['accuracy'] = {'temperature_tolerance_c':.5,'basis':'Coarse screen'}
    status, verification, criteria = _assess(case, levels, [])
    result = signal(dict(case=case,status=status,verification=verification,
                         criterion_assessments=criteria))
    guidance = [f for f in result['feedback'] if f['kind']=='numerical_resolution']
    assert guidance and 'tighter accuracy' in guidance[0]['message']
    assert not result['valid_for_comparison']


def test_thermal_local_mesh_and_resource_budgets_use_existing_contract(tmp_path):
    # Complete input based on an existing source, no solve needed to check syntax.
    root = Path(__file__).resolve().parents[1]
    model = root/'examples/integration/simplecad-beam.step'
    c = {'schema_version':'thermal-solid-1.0','mode':'steady',
         'model':{'path':str(model),'units':'mm','expected_bbox_mm':[[0,0,0],[100,10,10]]},
         'material':{'name':'assumed','basis':'test','conductivity_w_mk':167.,'temperature_range_c':[0,120]},
         'boundaries':[{'name':'reference','type':'temperature','target':'root','basis':'Synthetic thermal reference',
                        'selector':{'type':'plane','axis':'x','position_mm':0},'temperature_c':20.}],
         'mesh':{'sizes_mm':[4.,3.2,2.56],'max_elements':40000,'max_field_values':8000000,
           'local_refinements':[{'name':'root','selector':{'type':'plane','axis':'x','position_mm':0},'size_factor':.25,'distance_mm':4}]},
         'criteria':[{'id':'body','target':'body','region':{'type':'body'},'max_temperature_c':70}],
         'accuracy':{'temperature_tolerance_c':.5,'basis':'Task requires 0.5 C, with adequate decision reserve'},
         'assumptions':['synthetic'],'not_assessed':[],
         'conditions':{'properties_verified':False,'boundaries_verified':False},'provenance':{'task_id':'test'}}
    path = tmp_path/'case.json'; write_json(path,c)
    result = read_case(path)
    assert result['mesh']['max_elements'] == 40000
    from simplecae.schemas import check_contract
    check_contract(c)
    c['mesh']['local_refinements'] *= 2
    write_json(path,c)
    with pytest.raises(ValueError, match='unique'):
        read_case(path)
    c['mesh']['local_refinements'] = []
    c['accuracy']['basis'] = '   '
    write_json(path,c)
    with pytest.raises(ValueError, match='basis'):
        read_case(path)


def test_element_budget_stops_before_order_elevation_and_keeps_diagnostic(tmp_path, monkeypatch):
    import gmsh
    from simplecae.geometry import make_mesh
    root = Path(__file__).resolve().parents[1]
    case = load_case(root/'examples/integration/simplecad-beam-step.case.json')
    case['mesh']['max_elements'] = 1
    def forbidden(*args, **kwargs):
        raise AssertionError('Order elevation must not start after the budget is exceeded')
    monkeypatch.setattr(gmsh.model.mesh, 'setOrder', forbidden)
    with pytest.raises(ValueError, match='exceeds max_elements'):
        make_mesh(case, 5., tmp_path)
    diagnostic = json.loads((tmp_path/'mesh-diagnostic.json').read_text())
    assert diagnostic['element_count'] > diagnostic['max_elements'] == 1
    assert diagnostic['stage'] == 'element_budget'
    assert not (tmp_path/'job.inp').exists()


def test_thermal_preview_reports_power_units_and_never_invents_supports(tmp_path):
    from simplecae.preflight import preview_thermal
    root=Path(__file__).resolve().parents[1]
    case={'schema_version':'thermal-solid-1.0','mode':'steady',
          'model':{'path':str(root/'examples/integration/simplecad-beam.step')},
          'boundaries':[{'name':'heat','type':'heat_flux','target':'face','basis':'test',
                         'selector':{'type':'plane','axis':'x','position_mm':100},'flux_w_m2':1000},
                        {'name':'cold','type':'temperature','target':'face','basis':'test',
                         'selector':{'type':'plane','axis':'x','position_mm':0},'temperature_c':25}]}
    path=tmp_path/'input.json';write_json(path,case)
    preview_thermal(path,case,tmp_path/'preview')
    result=json.loads((tmp_path/'preview/preview.json').read_text())
    assert result['display']['supports'] == []
    heat=result['regions'][0]
    assert heat['prescribed_power_w'] == pytest.approx(heat['area_mm2']*.001)
    assert result['thermal_diagnostics']['temperature_reference_declared']
    assert result['thermal_diagnostics']['unassigned_insulated_face_ids']
    assert 'no temperature' in result['scope']
    case['boundaries'].append(copy.deepcopy(case['boundaries'][0]))
    with pytest.raises(ValueError, match='overlap'):
        preview_thermal(path,case,tmp_path/'overlap')
