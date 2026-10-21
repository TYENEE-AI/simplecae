"""Analytical references and workflow failures, independent of product names."""
import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from simplecae.case import write_json
from simplecae.thermal_network import calculate, validate, signal, analyze, conductance
from simplecae.api import check_case
from simplecae.signals import compare_results
from simplecae.task import start_task, run_task_check, task_status, record_task_check
from simplecae.workbench import snapshot


def network(mode='steady'):
    c = {'schema_version': 'thermal-network-1.0', 'mode': mode,
         'nodes': [{'id': n, 'target': 'region ' + n, 'basis': 'Analytical test, not material certification'}
                   for n in ('hot', 'body', 'ambient')],
         'links': [{'id': key, 'type': 'resistance', 'a': a, 'b': b, 'resistance_k_w': r,
                    'target': key, 'basis': 'Exact network reference'}
                   for key, a, b, r in [('in', 'hot', 'body', 2.), ('out', 'body', 'ambient', 3.)]],
         'fixed_temperature_c': {'hot': 100., 'ambient': 20.}, 'heat_w': {},
         'criteria': [{'id': 'temperature', 'node': 'body', 'max_temperature_c': 70.}],
         'property_temperature_range_c': [-100., 200.],
         'assumptions': ['Constant thermal properties; explicit reservoirs; linear lumped network'],
         'not_assessed': ['Real material and boundary applicability'],
         'conditions': dict.fromkeys(['properties_verified', 'boundaries_verified', 'lumping_verified'], False),
         'provenance': {'task_id': 'thermal-reference'}}
    if mode == 'transient':
        c['nodes'][1].update(capacity_j_k=10., initial_temperature_c=20., biot_number=.02)
        c['phases'] = [{'duration_s': 60., 'fixed_temperature_c': c.pop('fixed_temperature_c'),
                        'heat_w': c.pop('heat_w')}]
        c['steps_per_phase'] = 500
    return c


def test_series_resistance_exact_energy_and_margin():
    r = calculate(network())
    assert r['status'] == 'pass_under_stated_model'
    t = r['criterion_assessments']['temperature']
    assert t['max_temperature_c'] == pytest.approx(68.)
    assert t['margin_c'] == pytest.approx(2.)
    e = r['histories'][0]['energy'][0]
    assert e['bath_exchange_w'] == pytest.approx({'hot': 16., 'ambient': -16.})
    assert abs(e['balance_error_w']) < 1e-12
    assert r['whole_product_pass_available'] is False


def test_corrupted_thermal_evidence_cannot_confirm_a_design_failure(tmp_path):
    c = network()
    c['criteria'][0]['max_temperature_c'] = 60.
    p = tmp_path/'case.json'
    write_json(p, c)
    r = analyze(p, tmp_path/'run')
    assert signal(r)['criterion_assessments']['temperature']['status'] == 'fail_under_stated_model'
    r['histories'][0]['temperature_c'][0][1] -= 10.
    s = signal(r)
    assert not s['valid_for_comparison']
    assert s['feasible_under_stated_model'] is None
    assert s['criterion_assessments']['temperature']['status'] == 'indeterminate'


def test_parallel_conduction_convection_heat_source():
    c = network()
    c['links'] = [
        {'id': 'a', 'type': 'conduction', 'a': 'hot', 'b': 'body', 'conductivity_w_mk': 2.,
         'area_m2': .001, 'length_m': .01, 'target': 'bar', 'basis': 'Fourier law'},
        {'id': 'b', 'type': 'convection', 'a': 'body', 'b': 'ambient', 'coefficient_w_m2k': 10.,
         'area_m2': .02, 'target': 'exposed face', 'basis': 'Declared constant film coefficient'},
        {'id': 'c', 'type': 'resistance', 'a': 'body', 'b': 'ambient', 'resistance_k_w': 5.,
         'target': 'parallel path', 'basis': 'Reference'}]
    c['heat_w'] = {'body': 6.}
    r = calculate(c)
    assert r['criterion_assessments']['temperature']['max_temperature_c'] == pytest.approx((20 + 4 + 4 + 6) / .6)
    assert r['histories'][0]['energy'][0]['balance_error_w'] == pytest.approx(0, abs=1e-12)


def test_transient_matches_analytic_first_order_system():
    r = calculate(network('transient'))
    assert r['status'] == 'pass_under_stated_model'
    h = r['histories'][-1]
    expected = 68. - 48. * np.exp(-np.array(h['time_s']) / 12.)
    assert np.max(np.abs(np.array(h['temperature_c'])[:, 1] - expected)) < .03
    assert len(r['histories']) == 3
    assert max(r['verification']['time_refinement_max_differences_c']) < .05
    assert r['verification']['max_nodal_balance_error_w'] < 1e-9


def test_insulated_heating_energy_conservation():
    c = network('transient')
    c['nodes'] = [c['nodes'][1]]
    c['links'] = []
    c['phases'] = [{'duration_s': 10., 'fixed_temperature_c': {}, 'heat_w': {'body': 2.}}]
    r = calculate(c)
    assert r['criterion_assessments']['temperature']['max_temperature_c'] == pytest.approx(22.)
    assert r['histories'][-1]['energy'][-1]['storage_rate_w'] == pytest.approx(2.)


def test_phase_change_keeps_hot_then_cold_peak_and_both_jump_sides():
    c = network('transient')
    c['phases'].append({'duration_s': 60., 'fixed_temperature_c': {'hot': 20., 'ambient': 20.}, 'heat_w': {}})
    r = calculate(c)
    h = r['histories'][-1]
    t = r['criterion_assessments']['temperature']
    assert t['peak_time_s'] == 60.
    assert h['temperature_c'][-1][1] < 21.
    both = [row[0] for time, row in zip(h['time_s'], h['temperature_c']) if time == 60.]
    assert both == [100., 20.]


def test_two_node_transient_against_independent_matrix_exponential():
    from scipy.linalg import expm
    c = network('transient')
    c['nodes'].append({'id': 'extra', 'target': 'second mass', 'basis': 'Reference',
                       'capacity_j_k': 20., 'initial_temperature_c': 20.})
    c['links'].append({'id': 'extra', 'type': 'resistance', 'a': 'body', 'b': 'extra',
                       'resistance_k_w': 4., 'target': 'joining layer', 'basis': 'Reference'})
    c['phases'][0]['duration_s'] = 20.
    r = calculate(c)
    k = np.array([[.5 + 1/3 + .25, -.25], [-.25, .25]])
    cap_inv = np.diag([.1, .05])
    equilibrium = np.linalg.solve(k, [50 + 20/3, 0])
    for time, row in zip(r['histories'][-1]['time_s'][::100], r['histories'][-1]['temperature_c'][::100]):
        expected = equilibrium + expm(-cap_inv @ k * time) @ (np.array([20, 20]) - equilibrium)
        assert np.max(np.abs(expected - np.array(row)[[1, 3]])) < .03
    assert r['verification']['time_refinement_passed']


@pytest.mark.parametrize('limit,expected', [(60, 'fail_under_stated_model'), (80, 'pass_under_stated_model')])
def test_declared_temperature_limit_controls_result(limit, expected):
    c = network()
    c['criteria'][0]['max_temperature_c'] = limit
    assert calculate(c)['status'] == expected


def test_negative_Celsius_not_used_as_utilization(tmp_path):
    c = network()
    c['fixed_temperature_c'] = {'hot': -10., 'ambient': -30.}
    c['criteria'][0] = {'id': 'temperature', 'node': 'body', 'min_temperature_c': -15.}
    p = tmp_path / 'case.json'
    write_json(p, c)
    r = analyze(p, tmp_path / 'result')
    assert r['status'] == 'fail_under_stated_model'
    assert r['evaluation_signal']['utilizations'] == {}
    assert r['criterion_assessments']['temperature']['margin_c'] == pytest.approx(-3.)


@pytest.mark.parametrize('gap', ['biot', 'range', 'time'])
def test_applicability_and_time_failures_withhold_acceptance(gap):
    c = network('transient' if gap == 'time' else 'steady')
    if gap == 'biot':
        c['nodes'][1]['biot_number'] = .11
    elif gap == 'range':
        c['property_temperature_range_c'] = [0., 90.]
    else:
        c['steps_per_phase'] = 4
    r = calculate(c)
    assert r['status'] == 'indeterminate'
    assert all(x['status'] == 'indeterminate' for x in r['criterion_assessments'].values())
    expected = {'biot': 'lumping_screen', 'range': 'property_temperature_range', 'time': 'time_refinement'}[gap]
    assert expected in [d['code'] for d in r['diagnostics']]


@pytest.mark.parametrize('fault', ['floating', 'node', 'duplicate', 'negative', 'infinite',
                                  'unknown', 'fixed_heat', 'capacity', 'fixed_switch', 'units'])
def test_reject_invalid_or_ambiguous_inputs(fault):
    c = network('transient' if fault in ('capacity', 'fixed_switch') else 'steady')
    if fault == 'floating':
        c['links'] = []
    elif fault == 'node':
        c['links'][0]['b'] = 'missing'
    elif fault == 'duplicate':
        c['nodes'].append(copy.deepcopy(c['nodes'][0]))
    elif fault == 'negative':
        c['links'][0]['resistance_k_w'] = -2.
    elif fault == 'infinite':
        c['fixed_temperature_c']['hot'] = float('inf')
    elif fault == 'unknown':
        c['radiation'] = True
    elif fault == 'fixed_heat':
        c['heat_w'] = {'hot': 3.}
    elif fault == 'capacity':
        del c['nodes'][1]['capacity_j_k']
    elif fault == 'fixed_switch':
        c['phases'].append({'duration_s': 1., 'fixed_temperature_c': {'ambient': 20.}, 'heat_w': {}})
    elif fault == 'units':
        c['links'][0]['resistance_k_w'] = '2 K/W'
    with pytest.raises((ValueError, __import__('jsonschema').ValidationError)):
        validate(c)


def test_changed_boundary_or_resistance_is_not_ranked_as_same_contract(tmp_path):
    paths = []
    for i in range(2):
        c = network()
        c['links'][0]['resistance_k_w'] += i
        path = tmp_path / f'case{i}.json'
        write_json(path, c)
        analyze(path, tmp_path / str(i))
        paths.append(tmp_path / str(i) / 'result.json')
    assert not compare_results(paths)['comparable']
    assert compare_results([paths[0], paths[0]])['comparable']


def manifest(tmp_path, limit=70):
    root = Path(__file__).resolve().parents[1]
    p = json.loads((root / 'examples/tasks/bench-fixture.task.json').read_text(encoding='utf-8'))
    check = next(c for c in p['checks'] if c['method'] == 'fem')
    check.update(id='heat', method='calculation', question='Does the body remain below the declared temperature?',
                 result_criteria=['temperature'], targets=['body'],
                 load_path='hot reservoir -> body -> ambient', load_basis='100 C / 20 C',
                 support_basis='Two prescribed-temperature reservoirs')
    physical = copy.deepcopy(check)
    physical.update(id='physical', method='physical_test', decision='later',
                    question='Are actual material and installation temperatures verified?')
    for key in ('result_criteria', 'load_path', 'load_basis', 'support_basis', 'case_path'):
        physical.pop(key, None)
    p['checks'] = [check, physical]
    p['task_id'] = 'thermal-reference'
    c = network()
    c['criteria'][0]['max_temperature_c'] = limit
    cp = tmp_path / 'case.json'
    write_json(cp, c)
    p['cases'] = {'heat': str(cp)}
    p['sources'] = [str(cp)]
    path = tmp_path / 'task.json'
    write_json(path, p)
    return path


@pytest.mark.parametrize('limit,outcome,trigger', [
    (70, 'pass', 'none_for_this_check'),
    (60, 'fail', 'after_design_change')])
def test_real_agent_task_worker_and_viewer(tmp_path, limit, outcome, trigger):
    task = tmp_path / 'task'
    start_task(manifest(tmp_path, limit), task)
    status = run_task_check(task, 'heat', budget_seconds=40)
    row = status['checks'][0]
    assert row['outcome'] == outcome
    assert row['latest']['kind'] == 'computed'
    assert row['latest']['analysis']['reanalysis_trigger'] == trigger
    assert status['checks'][1]['outcome'] == 'pending'
    assert not status['whole_product_pass_available']
    view = snapshot(task / 'viewer')
    assert view['runs'][-1]['analysis'] == 'thermal_network'
    assert view['runs'][-1]['signal']['valid_for_comparison']
    assert view['runs'][-1]['datasets'] == []  # no fabricated spatial FEM
    with pytest.raises(ValueError, match='computed'):
        record_task_check(task, 'heat', artifacts=[str(task / 'task-status.json')],
            revision_sha256=status['revision_sha256'], outcome='pass', observations=['Unallowed override'])
    result = Path(row['latest']['analysis']['result_path'])
    data = json.loads(result.read_text(encoding='utf-8'))
    data['criterion_assessments']['temperature']['max_temperature_c'] = 0.
    write_json(result, data)
    assert task_status(task)['checks'][0]['outcome'] == 'insufficient_evidence'


def test_result_and_signal_schema(tmp_path):
    from simplecae.schemas import check_contract
    c = network()
    p = tmp_path / 'case.json'
    write_json(p, c)
    assert check_case(p) == c
    r = analyze(p, tmp_path / 'run')
    check_contract(r, 'result')
    check_contract(r['evaluation_signal'], 'signal')
    r['criterion_assessments']['temperature']['status'] = 'indeterminate'
    assert not signal(r)['valid_for_comparison']


@pytest.mark.parametrize('fault', ['field', 'peak', 'criterion', 'refinement', 'reservoir', 'energy', 'node_coverage'])
def test_summary_cannot_override_bound_thermal_history(tmp_path, fault):
    cp = tmp_path / 'case.json'
    write_json(cp, network('transient'))
    r = analyze(cp, tmp_path / 'out')
    assert signal(r)['valid_for_comparison']
    if fault == 'field':
        r['histories'][-1]['temperature_c'][-1][1] += 5
    elif fault == 'peak':
        r['criterion_assessments']['temperature']['max_temperature_c'] -= 5
    elif fault == 'criterion':
        r['criterion_assessments']['temperature']['margin_c'] += 5
    elif fault == 'refinement':
        r['histories'].pop(0)
    elif fault == 'reservoir':
        r['histories'][-1]['temperature_c'][-1][0] += 5
    elif fault == 'energy':
        r['histories'][-1]['energy'][-1]['bath_exchange_w']['hot'] += 5
    elif fault == 'node_coverage':
        r['node_ids'].reverse()
    assert not signal(r)['valid_for_comparison']
    assert signal(r)['feasible_under_stated_model'] is None


def test_temperature_margin_inside_numerical_guard_is_unresolved():
    c = network('transient')
    actual = calculate(c)['criterion_assessments']['temperature']['max_temperature_c']
    c['criteria'][0]['max_temperature_c'] = actual + .01
    assert calculate(c)['status'] == 'indeterminate'


def test_display_retains_peak_and_phase_change_samples():
    from simplecae.thermal_network import display_history
    c = network('transient')
    c['phases'].append({'duration_s': 60., 'fixed_temperature_c': {'hot': 20., 'ambient': 20.}, 'heat_w': {}})
    r = calculate(c)
    points = display_history(r)['series'][0]['points']
    assert max(v for _, v in points) == r['criterion_assessments']['temperature']['max_temperature_c']
    assert len([p for p in points if p[0] == 60.]) == 2
    assert len(points) < len(r['histories'][-1]['temperature_c'])


def test_direct_plan_cannot_label_a_network_as_spatial_FEM(tmp_path):
    from simplecae.design_check import design_check
    from test_design_check import context
    path = manifest(tmp_path)
    plan = json.loads(path.read_text(encoding='utf-8'))
    plan['schema_version'] = 'simplecae-use-plan-1.0'
    plan['checks'][0]['method'] = 'fem'
    plan.pop('sources')
    plan.pop('cases')
    pp = tmp_path / 'plan.json'
    write_json(pp, plan)
    xp = tmp_path / 'context.json'
    write_json(xp, context())
    with pytest.raises(ValueError, match='not a solid'):
        design_check(tmp_path / 'case.json', tmp_path / 'run', context_path=xp,
                     plan_path=pp, check_id='heat')
    assert not (tmp_path / 'run').exists()


def test_no_thermal_capacity_claim(tmp_path):
    from simplecae.design_check import design_check
    from test_design_check import context
    cp, xp = tmp_path / 'case.json', tmp_path / 'context.json'
    write_json(cp, network())
    write_json(xp, context())
    with pytest.raises(ValueError, match='capacity'):
        design_check(cp, tmp_path / 'run', context_path=xp, predict_capacity=True)
    assert not (tmp_path / 'run').exists()
