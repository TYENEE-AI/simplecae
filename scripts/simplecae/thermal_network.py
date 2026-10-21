"""Linear thermal networks: explicit physical data, no CAD-derived heat facts.

SI heat units (W, J, s, m); temperatures in deg C, differences in K.
Backward Euler conserves the discrete energy balance. Three refined histories
are compared at *every* common time and every node, including phase boundaries.
This is a lumped calculation, not a solid temperature-field FEM.
"""
from __future__ import annotations

import copy
import html
import json
import math
from pathlib import Path

import numpy as np
from scipy.linalg import cho_factor, cho_solve

from .case import sha256, write_json
from .signals import digest

SCHEMA = 'thermal-network-1.0'
RESULT_SCHEMA = 'thermal-network-result-1.0'
TIME_TOLERANCE_C = 0.05
BALANCE_TOLERANCE_W = 1e-8
NOT_ASSESSED = [
    'Temperatures are lumped-region values, not spatial surface or internal hot spots.',
    'Thermal expansion, stress, softening, creep, ignition and physical product safety are not assessed.',
    'Convection/contact resistance and material applicability require separate evidence.',
    'Radiation, phase change and temperature-dependent properties are not modeled.',
]


def schema():
    from .schemas import obj, arr, enum
    text = {'type': 'string', 'minLength': 1}
    number = {'type': 'number'}
    positive = {'type': 'number', 'exclusiveMinimum': 0}
    temperature = {'type': 'number', 'minimum': -273.15}
    mapping = lambda item: {'type': 'object', 'additionalProperties': item}
    node = obj({'id': text, 'target': text, 'basis': text,
                'capacity_j_k': positive, 'initial_temperature_c': temperature,
                'biot_number': {'type': 'number', 'minimum': 0}}, ('id', 'target', 'basis'))
    common = {'id': text, 'a': text, 'b': text, 'target': text, 'basis': text}
    variants = []
    for kind, parameters in (
        ('resistance', {'resistance_k_w': positive}),
        ('conduction', {'conductivity_w_mk': positive, 'length_m': positive, 'area_m2': positive}),
        ('convection', {'coefficient_w_m2k': positive, 'area_m2': positive}),
    ):
        fields = common | {'type': {'const': kind}} | parameters
        variants.append(obj(fields, tuple(fields)))
    phase = obj({'duration_s': positive, 'fixed_temperature_c': mapping(temperature),
                 'heat_w': mapping(number)}, ('duration_s', 'fixed_temperature_c', 'heat_w'))
    criterion = obj({'id': text, 'node': text, 'min_temperature_c': temperature,
                     'max_temperature_c': temperature}, ('id', 'node'))
    criterion['anyOf'] = [{'required': ['min_temperature_c']}, {'required': ['max_temperature_c']}]
    return obj({
        'schema_version': {'const': SCHEMA}, 'mode': enum('steady', 'transient'),
        'nodes': dict(arr(node, 1), maxItems=128),
        'links': dict(arr({'oneOf': variants}), maxItems=4096),
        'fixed_temperature_c': mapping(temperature), 'heat_w': mapping(number),
        'phases': dict(arr(phase, 1), maxItems=64),
        'steps_per_phase': {'type': 'integer', 'minimum': 4, 'maximum': 2000},
        'criteria': dict(arr(criterion, 1), maxItems=256),
        'property_temperature_range_c': dict(arr(temperature, 2), maxItems=2),
        'assumptions': arr(text, 1), 'not_assessed': arr(text),
        'conditions': obj({k: {'type': 'boolean'} for k in
            ('properties_verified', 'boundaries_verified', 'lumping_verified')},
            ('properties_verified', 'boundaries_verified', 'lumping_verified')),
        'provenance': obj({'task_id': text, 'revision': text, 'generator': text}, ('task_id',)),
    }, ('schema_version', 'mode', 'nodes', 'links', 'criteria',
         'property_temperature_range_c', 'assumptions', 'not_assessed', 'conditions', 'provenance'))


def validate(case):
    import jsonschema
    try:
        jsonschema.Draft202012Validator(schema()).validate(case)
    except jsonschema.ValidationError as exc:
        raise ValueError('Thermal input: ' + exc.message) from None
    # JSON Schema accepts NaN/Infinity under Python; no numerical field may.
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Thermal inputs must be finite')
        if isinstance(value, dict):
            for v in value.values():
                finite(v)
        if isinstance(value, list):
            for v in value:
                finite(v)
        if isinstance(value, str) and not value.strip():
            raise ValueError('Thermal text fields must be nonempty')
    finite(case)
    ids = [n['id'] for n in case['nodes']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate thermal node id')
    for key in ('links', 'criteria'):
        if len({x['id'] for x in case[key]}) != len(case[key]):
            raise ValueError('Duplicate thermal ' + key + ' id')
    ids = set(ids)
    for link in case['links']:
        if link['a'] not in ids or link['b'] not in ids or link['a'] == link['b']:
            raise ValueError('A heat link needs two different known nodes')
    for c in case['criteria']:
        if c['node'] not in ids:
            raise ValueError('Temperature criterion references an unknown node')
        if c.get('min_temperature_c', -273.15) > c.get('max_temperature_c', math.inf):
            raise ValueError('Temperature criterion has contradictory bounds')
    if case['property_temperature_range_c'][0] >= case['property_temperature_range_c'][1]:
        raise ValueError('Property temperature range must be increasing')
    if case['mode'] == 'steady':
        if 'phases' in case or 'steps_per_phase' in case:
            raise ValueError('A steady case cannot contain transient phases/steps')
        if not {'fixed_temperature_c', 'heat_w'} <= set(case):
            raise ValueError('Steady case requires fixed_temperature_c and heat_w')
        phases = [case]
    else:
        if 'fixed_temperature_c' in case or 'heat_w' in case:
            raise ValueError('Transient boundary conditions belong in phases')
        if 'phases' not in case:
            raise ValueError('Transient case requires phases')
        phases = case['phases']
        if len(phases) * case.get('steps_per_phase', 100) * 4 > 32000:
            raise ValueError('Transient history exceeds 32000 fine steps; split the task explicitly')
    fixed = set(phases[0]['fixed_temperature_c'])
    for phase in phases:
        if set(phase['fixed_temperature_c']) != fixed:
            raise ValueError('Changing fixed-node membership is unsupported; change values only')
        if (set(phase['heat_w']) | fixed) - ids:
            raise ValueError('Boundary/heat references an unknown node')
        if set(phase['heat_w']) & fixed:
            raise ValueError('Heat input on a prescribed-temperature reservoir is ambiguous')
    if not ids - fixed:
        raise ValueError('At least one non-prescribed thermal node is needed')
    if any(n['id'] in fixed and ('capacity_j_k' in n or 'initial_temperature_c' in n)
           for n in case['nodes']):
        raise ValueError('A prescribed reservoir cannot also have ignored capacity/initial temperature')
    if case['mode'] == 'transient':
        for node in case['nodes']:
            if node['id'] not in fixed and not {'capacity_j_k', 'initial_temperature_c'} <= set(node):
                raise ValueError('Each transient free node requires capacity and initial temperature')
    # A steady floating component cannot have a uniquely determined temperature.
    # Transient insulated bodies with finite capacity, however, are supported.
    if case['mode'] == 'steady':
        reached = set(fixed)
        while True:
            old = set(reached)
            for link in case['links']:
                if {link['a'], link['b']} & reached:
                    reached.update((link['a'], link['b']))
            if old == reached:
                break
        if reached != ids:
            raise ValueError('No temperature reference/heat-rejection path for a steady component')
    return case


def read_case(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def conductance(link):
    if link['type'] == 'resistance':
        value = 1 / link['resistance_k_w']
    elif link['type'] == 'conduction':
        value = link['conductivity_w_mk'] * link['area_m2'] / link['length_m']
    else:
        value = link['coefficient_w_m2k'] * link['area_m2']
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Conductance must be finite and positive in SI units')
    return value


def _system(case):
    ids = [n['id'] for n in case['nodes']]
    lookup = {key: i for i, key in enumerate(ids)}
    phases = [case] if case['mode'] == 'steady' else case['phases']
    fixed = [lookup[key] for key in phases[0]['fixed_temperature_c']]
    free = [i for i in range(len(ids)) if i not in fixed]
    k = np.zeros((len(ids), len(ids)))
    for link in case['links']:
        a, b, g = lookup[link['a']], lookup[link['b']], conductance(link)
        k[a, a] += g
        k[b, b] += g
        k[a, b] -= g
        k[b, a] -= g
    if not np.isfinite(k).all():
        raise ValueError('Thermal matrix overflow')
    return ids, lookup, fixed, free, k, phases


def _history(case, refinement=1):
    ids, lookup, fixed, free, k, phases = _system(case)
    t = np.array([n.get('initial_temperature_c', 0.) for n in case['nodes']], dtype=float)
    capacity = np.array([case['nodes'][i].get('capacity_j_k', 0.) for i in free])
    kff = k[np.ix_(free, free)]
    times, temperatures, records, phases_at = [], [], [], []
    elapsed = 0.
    max_residual = 0.
    for phase_index, phase in enumerate(phases):
        for name, value in phase['fixed_temperature_c'].items():
            t[lookup[name]] = value
        q = np.array([phase['heat_w'].get(ids[i], 0.) for i in free])
        rhs = q - k[np.ix_(free, fixed)] @ t[fixed]
        if case['mode'] == 'steady':
            factor = cho_factor(kff)
            t[free] = cho_solve(factor, rhs)
            derivative = np.zeros(len(free))
            count, dt = 1, 0.
        else:
            count = case.get('steps_per_phase', 100) * refinement
            dt = phase['duration_s'] / count
            factor = cho_factor(kff + np.diag(capacity / dt))
            times.append(elapsed)
            temperatures.append(t.copy())
            phases_at.append(phase_index)
        for step in range(count):
            if dt:
                old = t[free].copy()
                t[free] = cho_solve(factor, rhs + capacity / dt * old)
                derivative = capacity * (t[free] - old) / dt
            residual = kff @ t[free] - rhs + derivative
            max_residual = max(max_residual, float(np.max(np.abs(residual))))
            # Positive exchange means energy enters the free network from bath.
            bath_w = {ids[j]: float(sum(k[i, j] * (t[i] - t[j]) for i in free)) for j in fixed}
            records.append({'phase': phase_index, 'time_s': elapsed + (step + 1) * dt,
                'input_w': float(q.sum()), 'bath_exchange_w': bath_w,
                'storage_rate_w': float(derivative.sum()),
                'balance_error_w': float(q.sum() + sum(bath_w.values()) - derivative.sum())})
            times.append(elapsed + (step + 1) * dt)
            temperatures.append(t.copy())
            phases_at.append(phase_index)
        if dt:
            elapsed += phase['duration_s']
    field = np.asarray(temperatures)
    if not np.isfinite(field).all() or not math.isfinite(max_residual):
        raise ValueError('Non-finite thermal solution')
    return {'time_s': times, 'phase': phases_at, 'temperature_c': field.tolist(),
            'energy': records, 'max_nodal_balance_error_w': max_residual}


def _compare_histories(coarse, fine):
    # Each phase contains n+1 samples; phase transitions retain BOTH reservoir
    # states at the same time. Never interpolate across an imposed jump.
    max_error = 0.
    for phase in set(coarse['phase']):
        a = np.array([row for row, p in zip(coarse['temperature_c'], coarse['phase']) if p == phase])
        b = np.array([row for row, p in zip(fine['temperature_c'], fine['phase']) if p == phase])
        if len(b) != 2 * (len(a) - 1) + 1:
            raise ValueError('Transient comparison has missing phase/time samples')
        error = max(float(np.max(np.abs(a - b[::2]))),
                    float(np.max(np.abs(a.max(axis=0) - b.max(axis=0)))),
                    float(np.max(np.abs(a.min(axis=0) - b.min(axis=0)))))
        max_error = max(max_error, error)
    return max_error


def calculate(case):
    validate(case)
    histories = [_history(case, r) for r in ((1, 2, 4) if case['mode'] == 'transient' else (1,))]
    return _assess(case, histories)


def _assess(case, histories):
    differences = [_compare_histories(a, b) for a, b in zip(histories, histories[1:])]
    last = histories[-1]
    values = np.asarray(last['temperature_c'])
    lo, hi = case['property_temperature_range_c']
    balance = max(h['max_nodal_balance_error_w'] for h in histories)
    verification = {
        'energy_balance_passed': balance <= BALANCE_TOLERANCE_W,
        'max_nodal_balance_error_w': balance, 'balance_tolerance_w': BALANCE_TOLERANCE_W,
        'time_refinement_passed': all(x <= TIME_TOLERANCE_C for x in differences),
        'time_refinement_max_differences_c': differences,
        'time_refinement_tolerance_c': TIME_TOLERANCE_C,
        'property_range_passed': bool(np.min(values) >= lo and np.max(values) <= hi),
        'lumping_screen_passed': all(n.get('biot_number', 0.) <= .1 for n in case['nodes']),
    }
    valid = all(verification[k] for k in
        ('energy_balance_passed', 'time_refinement_passed', 'property_range_passed', 'lumping_screen_passed'))
    criteria = {}
    nodes = {n['id']: (i, n) for i, n in enumerate(case['nodes'])}
    for c in case['criteria']:
        i, node = nodes[c['node']]
        high_index, low_index = int(np.argmax(values[:, i])), int(np.argmin(values[:, i]))
        high, low = float(values[high_index, i]), float(values[low_index, i])
        margins = ([c['max_temperature_c'] - high] if 'max_temperature_c' in c else [])
        margins += ([low - c['min_temperature_c']] if 'min_temperature_c' in c else [])
        # Do not divide Celsius temperatures to invent an utilization ratio.
        # A resolved time history still has finite temporal accuracy. Do not
        # turn an arbitrarily small positive sampled margin into acceptance.
        guard = TIME_TOLERANCE_C if case['mode'] == 'transient' else 1e-9
        criterion_status = ('pass_under_stated_model' if min(margins) > guard else
                            'fail_under_stated_model' if min(margins) < -guard else 'indeterminate')
        criteria[c['id']] = {'status': criterion_status if valid else 'indeterminate',
            'node': c['node'], 'target': node['target'], 'max_temperature_c': high,
            'min_temperature_c': low, 'peak_time_s': last['time_s'][high_index],
            'minimum_time_s': last['time_s'][low_index], 'margin_c': min(margins),
            'numerical_guard_c': guard,
            'limits': {k: v for k, v in c.items() if k.endswith('_temperature_c')}}
    passed = all(c['status'] == 'pass_under_stated_model' for c in criteria.values())
    resolved = all(c['status'] != 'indeterminate' for c in criteria.values())
    status = ('pass_under_stated_model' if passed else 'fail_under_stated_model') if valid and resolved else 'indeterminate'
    gaps = [k for k in ('properties_verified', 'boundaries_verified', 'lumping_verified')
            if not case['conditions'][k]]
    if any('biot_number' not in n for n in case['nodes']):
        gaps.append('Some lumped regions have no quantified Biot screen; supplied lumping basis is an assertion.')
    diagnostics = []
    if not verification['property_range_passed']:
        diagnostics.append({'code': 'property_temperature_range', 'observed_range_c': [float(values.min()), float(values.max())],
            'declared_range_c': [lo, hi], 'message':
            'Calculated temperatures leave the declared material-property range. Obtain applicable property data or change the physical design; do not simply widen the range without evidence.'})
    if not verification['time_refinement_passed']:
        diagnostics.append({'code': 'time_refinement', 'differences_c': differences,
            'tolerance_c': TIME_TOLERANCE_C, 'message':
            'Time histories are not resolved. Increase steps_per_phase and rerun before interpreting a temperature as a design failure.'})
    if not verification['lumping_screen_passed']:
        diagnostics.append({'code': 'lumping_screen',
            'nodes': [n['id'] for n in case['nodes'] if n.get('biot_number', 0) > .1],
            'message': 'The declared Biot screen exceeds 0.1. Use a justified spatial model/subdivision; changing the temperature limit does not repair this model.'})
    if not verification['energy_balance_passed']:
        diagnostics.append({'code': 'energy_balance', 'residual_w': balance,
            'tolerance_w': BALANCE_TOLERANCE_W, 'message':
            'Nodal heat balance fails. Inspect units, conductance scaling and numerical conditioning before CAD changes.'})
    if valid and not resolved:
        diagnostics.append({'code': 'criterion_near_numerical_guard',
            'criteria': [name for name, c in criteria.items() if c['status'] == 'indeterminate'],
            'message': 'A temperature margin lies inside the numerical guard. No favorable verdict is available at this accuracy.'})
    return {'schema_version': RESULT_SCHEMA, 'analysis': 'thermal_network', 'status': status,
        'case': copy.deepcopy(case), 'node_ids': [n['id'] for n in case['nodes']],
        'histories': histories, 'criterion_assessments': criteria,
        'verification': verification, 'evidence_gaps': gaps, 'diagnostics': diagnostics,
        'whole_product_pass_available': False,
        'not_assessed': list(dict.fromkeys(NOT_ASSESSED + case['not_assessed']))}


def analyze(path, out):
    path, out = Path(path).resolve(), Path(out).resolve()
    case = read_case(path)
    source_hash = sha256(path)
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'input.json', case)
    try:
        result = calculate(case)
        if sha256(path) != source_hash:
            raise ValueError('Thermal input changed during solve')
    except (ValueError, ArithmeticError, np.linalg.LinAlgError) as exc:
        result = {'schema_version': RESULT_SCHEMA, 'analysis': 'thermal_network',
            'case': case, 'status': 'invalid', 'error': str(exc), 'whole_product_pass_available': False,
            'not_assessed': NOT_ASSESSED}
    result['source'] = {'path': str(path), 'sha256': source_hash}
    result['method'] = {'name': 'linear thermal network / backward Euler', 'time_tolerance_c': TIME_TOLERANCE_C,
        'balance_tolerance_w': BALANCE_TOLERANCE_W, 'implementation_sha256': sha256(Path(__file__))}
    result['task_contract'] = contract(case)
    result['evaluation_signal'] = signal(result)
    write_json(out / 'result.json', result)
    write_json(out / 'signal.json', result['evaluation_signal'])
    text = html.escape(json.dumps(result['evaluation_signal'], ensure_ascii=False, indent=2))
    (out / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>SimpleCAE thermal</title>'
        '<style>body{font:15px/1.6 system-ui;max-width:1000px;margin:32px auto}pre{white-space:pre-wrap}</style>'
        '<h1>热网络检查</h1><p>节点温度不是空间热点；条件模型通过不代表产品通过。</p>'
        '<a href="result.json">完整温度历程与能量平衡</a><pre>' + text + '</pre>', encoding='utf-8')
    return result


def contract(case):
    # Until geometry-to-network bindings are qualified, changes of resistance,
    # mass or boundary assumptions are separate model contracts, not ranked CAD.
    value = copy.deepcopy(case)
    value.pop('steps_per_phase', None)
    value['provenance'] = {'task_id': case.get('provenance', {}).get('task_id')}
    return value


def signal(result):
    case = result.get('case', {})
    criteria = result.get('criterion_assessments', {})
    verification = result.get('verification', {})
    valid = result.get('status') in ('pass_under_stated_model', 'fail_under_stated_model')
    valid = valid and result.get('task_contract') == contract(case)
    valid = valid and bool(criteria) and all(verification.get(k) is True for k in (
        'energy_balance_passed', 'time_refinement_passed', 'property_range_passed', 'lumping_screen_passed'))
    valid = valid and set(criteria) == {c['id'] for c in case.get('criteria', [])}
    valid = valid and all(c.get('status') in ('pass_under_stated_model', 'fail_under_stated_model')
                          for c in criteria.values())
    failed = [c for c in criteria.values() if c['status'] == 'fail_under_stated_model']
    valid = valid and (result.get('status') == ('fail_under_stated_model' if failed else 'pass_under_stated_model'))
    evidence_error = None
    if valid:
        try:
            _verify_evidence(result)
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as exc:
            valid = False
            evidence_error = str(exc)
    if not valid:
        # A broken history/assessment seal invalidates categorical failures too.
        # Keep the raw temperatures for diagnosis, but do not tell an Agent that
        # an unverified "fail" is established evidence for a CAD change.
        criteria = {name: dict(c, status='indeterminate') for name, c in criteria.items()}
    findings = [{'kind': 'thermal_observation', 'scope': c['target'], **c,
                 'message': f"区域温度 {c['min_temperature_c']:.5g}–{c['max_temperature_c']:.5g} °C；"
                            f"最小判据裕量 {c['margin_c']:.5g} °C。区域集中温度不代表内部或表面热点。"}
                for c in criteria.values()]
    if valid and failed:
        findings.append({'kind': 'design_hypothesis', 'requires_reanalysis': True,
            'message': 'Trace heat entering the failing region versus heat leaving it. For excess temperature, consider reducing the incoming heat conductance or increasing heat rejection; insulating a heat-generating region can worsen it. Preserve service temperatures, power, duration and acceptance limits.',
            'scope': [c['target'] for c in failed]})
    if not valid:
        for diagnostic in result.get('diagnostics', []):
            findings.append({'kind': 'evidence_gap', **diagnostic})
        if evidence_error or not result.get('diagnostics'):
            findings.append({'kind': 'evidence_gap', 'message':
                evidence_error or result.get('error') or 'Resolve missing thermal histories or criteria before CAD acceptance.'})
    return {'schema_version': 'simplecae-signal-1.0', 'analysis_status': result.get('status', 'invalid'),
        'valid_for_comparison': bool(valid),
        'feasible_under_stated_model': (not failed) if valid else None,
        'physical_conditions_verified': False, 'whole_installation_rating_available': False,
        'task_contract_sha256': digest(contract(case)),
        'task_id': case.get('provenance', {}).get('task_id'), 'candidate': case.get('provenance', {}),
        'utilizations': {}, 'bottleneck_margin': None, 'conditional_limit': None,
        'metrics': {'node_temperatures': criteria}, 'coverage': {'method': 'lumped_network'},
        'criterion_assessments': criteria, 'feedback': findings,
        'not_assessed': result.get('not_assessed', NOT_ASSESSED) + result.get('evidence_gaps', []),
        'score_meaning': 'Temperature margins in deg C; no stress, lifetime, spatial-hotspot or product rating.'}


def _verify_evidence(result):
    """Recheck stored histories against equations, never trust only green flags."""
    case = validate(result['case'])
    ids, lookup, fixed, free, k, phases = _system(case)
    histories = result['histories']
    refinements = (1, 2, 4) if case['mode'] == 'transient' else (1,)
    if len(histories) != len(refinements) or result['node_ids'] != ids:
        raise ValueError('Thermal evidence has incomplete refinement or node coverage')
    for h, refinement in zip(histories, refinements):
        expected_times, expected_phases = [], []
        starts = []
        elapsed = 0.
        for p, phase in enumerate(phases):
            starts.append(len(expected_times))
            n = case.get('steps_per_phase', 100) * refinement if case['mode'] == 'transient' else 0
            dt = phase['duration_s'] / n if n else 0.
            expected_times.extend(elapsed + j * dt for j in range(n + 1))
            expected_phases.extend([p] * (n + 1))
            elapsed += n * dt
        values = np.asarray(h['temperature_c'], dtype=float)
        if (values.shape != (len(expected_times), len(ids)) or not np.isfinite(values).all()
                or h['phase'] != expected_phases or len(h['time_s']) != len(expected_times)
                or not np.allclose(h['time_s'], expected_times, atol=1e-9, rtol=1e-12)):
            raise ValueError('Thermal evidence has missing/non-finite field or time samples')
        maximum_residual = 0.
        energy_index = 0
        for p, phase in enumerate(phases):
            start, end = starts[p], starts[p + 1] if p + 1 < len(starts) else len(values)
            segment = values[start:end]
            for name, temperature in phase['fixed_temperature_c'].items():
                if not np.allclose(segment[:, lookup[name]], temperature, rtol=0, atol=1e-10):
                    raise ValueError('Recorded temperature contradicts prescribed reservoir')
            q = np.array([phase['heat_w'].get(ids[i], 0.) for i in free])
            if case['mode'] == 'transient':
                previous = ([case['nodes'][i]['initial_temperature_c'] for i in free]
                            if p == 0 else values[start - 1, free])
                if not np.allclose(segment[0, free], previous, rtol=0, atol=1e-10):
                    raise ValueError('Thermal initial state or phase continuity is contradictory')
                dt = phase['duration_s'] / (len(segment) - 1)
                capacity = np.array([case['nodes'][i]['capacity_j_k'] for i in free])
                storage = np.diff(segment[:, free], axis=0) * (capacity / dt)
                steps = segment[1:]
                step_times = expected_times[start + 1:end]
            else:
                steps, storage = segment, np.zeros((1, len(free)))
                step_times = expected_times[start:end]
            residuals = steps @ k[free, :].T - q + storage
            maximum_residual = max(maximum_residual, float(np.max(np.abs(residuals))))
            for row, rate, time in zip(steps, storage, step_times):
                recorded = h['energy'][energy_index]
                bath = {ids[j]: float(sum(k[i, j] * (row[i] - row[j]) for i in free)) for j in fixed}
                expected = {'input_w': float(q.sum()), 'storage_rate_w': float(rate.sum()),
                    'balance_error_w': float(q.sum() + sum(bath.values()) - rate.sum())}
                if (recorded['phase'] != p or not math.isclose(recorded['time_s'], time, abs_tol=1e-9)
                        or set(recorded['bath_exchange_w']) != set(bath)):
                    raise ValueError('Thermal energy evidence has inconsistent phase/coverage')
                for name, value in expected.items():
                    if not math.isclose(recorded[name], value, rel_tol=1e-10, abs_tol=1e-8):
                        raise ValueError('Thermal energy ledger contradicts temperature history')
                if any(not math.isclose(recorded['bath_exchange_w'][name], value, rel_tol=1e-10, abs_tol=1e-8)
                       for name, value in bath.items()):
                    raise ValueError('Thermal reservoir flux contradicts temperature history')
                energy_index += 1
        if energy_index != len(h['energy']) or maximum_residual > BALANCE_TOLERANCE_W:
            raise ValueError('Thermal history fails independently reconstructed nodal energy balance')
        if abs(maximum_residual - h['max_nodal_balance_error_w']) > BALANCE_TOLERANCE_W:
            raise ValueError('Thermal recorded residual contradicts the history')
    recomputed = _assess(case, histories)
    for name in ('criterion_assessments', 'verification', 'status', 'diagnostics'):
        if result[name] != recomputed[name]:
            raise ValueError('Thermal assessment contradicts complete histories: ' + name)


def design_feedback(result, context, run_state):
    s = signal(result)
    if run_state != 'completed':
        s.update(valid_for_comparison=False, feasible_under_stated_model=None)
    criteria = s['criterion_assessments']
    governing = min(criteria, key=lambda key: criteria[key]['margin_c']) if criteria else None
    action = ('Resolve the recorded thermal input/numerical/applicability gap before accepting or changing CAD.'
              if not s['valid_for_comparison'] else
              'Keep this scoped design and finish the remaining use checks.'
              if s['feasible_under_stated_model'] else
              'Trace the heat path at the named region; propose a permitted geometric change and recheck unchanged service conditions.')
    return {'model_status': result.get('status', 'invalid'),
        'valid_for_comparison': s['valid_for_comparison'],
        'conditional_model_pass': s['feasible_under_stated_model'],
        'whole_product_pass_available': False,
        'governing_criterion': {'name': governing, 'margin_c': criteria[governing]['margin_c']} if governing else None,
        'criterion_assessments': criteria, 'utilizations': {}, 'findings': s['feedback'],
        'observations': list(criteria.values()),
        'next_actions': [d['message'] for d in result.get('diagnostics', [])] or [action],
        'not_assessed': list(dict.fromkeys(context['not_assessed'] + s['not_assessed'])),
        'verification': result.get('verification', {}),
        'meaning': 'Declared lumped heat model only; temperature is not strength, lifetime or product approval.'}


def display_history(result):
    """Small plot payload; preserve extrema and phase boundaries, never verdicts."""
    if not result.get('histories'):
        return None
    h = result['histories'][-1]
    targets = list(dict.fromkeys(c['node'] for c in result['case']['criteria']))
    ids = result['node_ids']
    series = []
    for name in targets[:8]:
        col = ids.index(name)
        values = np.array([row[col] for row in h['temperature_c']])
        stride = max(1, math.ceil(len(values) / 1000))
        selected = set(range(0, len(values), stride)) | {len(values) - 1, int(values.argmax()), int(values.argmin())}
        for i in range(1, len(values)):
            if h['phase'][i] != h['phase'][i - 1]:
                selected.update((i - 1, i))
        node = next(n for n in result['case']['nodes'] if n['id'] == name)
        series.append({'node': name, 'target': node['target'],
            'points': [[h['time_s'][i], float(values[i])] for i in sorted(selected)],
            'limits_c': sorted({c[k] for c in result['case']['criteria'] if c['node'] == name
                               for k in ('min_temperature_c', 'max_temperature_c') if k in c})})
    return {'series': series, 'mode': result['case']['mode'], 'omitted_nodes': max(0, len(targets) - 8),
            'meaning': 'Display sampling retains region extrema and phase boundaries; complete histories and every criterion remain in result.json.'}
