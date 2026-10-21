"""Small reproducible thermal-network demonstrations; no native meshes/caches."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from simplecae.case import sha256, write_json
from simplecae.api import analyze_case
from simplecae.task import start_task, run_task_check
from simplecae.workbench import create_session, add_result, export_session


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    base_path = ROOT / 'examples/thermal-network/reservoir.case.json'
    base = json.loads(base_path.read_text(encoding='utf-8'))
    create_session(out / 'viewer', 'SimpleCAE · 热网络参考验证（非产品验收）')
    records = []
    for name in ('pass', 'fail', 'insufficient', 'transient'):
        case = copy.deepcopy(base)
        expected = 'pass_under_stated_model'
        if name == 'fail':
            case['heat_w'] = {'body': 10}
            expected = 'fail_under_stated_model'
        if name == 'insufficient':
            case['property_temperature_range_c'] = [0, 90]
            expected = 'indeterminate'
        if name == 'transient':
            case['mode'] = 'transient'
            case['nodes'][1].update(capacity_j_k=10, initial_temperature_c=20, biot_number=.02)
            case['phases'] = [{'duration_s': 60, 'fixed_temperature_c': case.pop('fixed_temperature_c'),
                               'heat_w': case.pop('heat_w')}]
            case['steps_per_phase'] = 500
        cp = out / f'{name}.case.json'
        write_json(cp, case)
        result = analyze_case(cp, out / name, predict_capacity=False)
        if result['status'] != expected:
            raise AssertionError((name, expected, result['status']))
        add_result(out / 'viewer', out / name / 'result.json', name,
                   'Independent declared reference case; changes of physics are not a CAD-only improvement')
        records.append({'case': name, 'expected': expected, 'actual': result['status'],
            'criteria': result['criterion_assessments'], 'verification': result['verification'],
            'result_sha256': sha256(out / name / 'result.json')})
    # One real bounded Agent task: computed thermal check + pending physical test.
    check = {'id': 'heat', 'scenario': 'use', 'question': 'Does the protected region stay below 70 C?',
        'user_impact': 'Avoid excessive temperature at the protected region',
        'method': 'calculation', 'decision': 'now', 'targets': ['Protected region'],
        'reason': 'Declared lumped heat path is the first reference check', 'required_for_claim': True,
        'acceptance': 'Peak region temperature <=70 C within qualified numerical/model scope',
        'assumptions': base['assumptions'], 'not_assessed': base['not_assessed'],
        'load_path': 'Hot reservoir -> protected region -> ambient',
        'load_basis': '100 C and 20 C reservoirs, no internal heat',
        'support_basis': 'Two fixed temperature reservoirs', 'result_criteria': ['region-temperature']}
    physical = {k: copy.deepcopy(v) for k, v in check.items() if k not in
                ('load_path', 'load_basis', 'support_basis', 'result_criteria')}
    physical.update(id='actual-temperature', method='physical_test', decision='later',
                    question='Do measured installation temperatures support the assumptions?',
                    reason='Physical applicability remains unverified')
    task = {'schema_version': 'simplecae-task-1.0', 'task_id': base['provenance']['task_id'],
        'request': 'Protect a region from an explicit hot reservoir; demonstrate the calculation workflow',
        'scenarios': [{'id': 'use', 'use': 'Declared thermal-resistance network',
                       'success': 'Temperature criterion met and physical applicability separately verified'}],
        'checks': [check, physical], 'unknowns': ['Actual material, contact and convection data'],
        'iteration_constraints': ['Preserve service temperatures, heat input and limits'],
        'sources': [str(base_path)], 'cases': {'heat': str(base_path)}}
    write_json(out / 'agent.task.json', task)
    start_task(out / 'agent.task.json', out / 'agent', viewer_session=out / 'viewer')
    status = run_task_check(out / 'agent', 'heat', budget_seconds=60)
    if status['checks'][0]['outcome'] != 'pass' or status['checks'][1]['outcome'] != 'pending' or status['whole_product_pass_available']:
        raise AssertionError('Agent task lost its computed/pending/product distinction')
    export_session(out / 'viewer')
    summary = {'scope': 'Thermal network demonstration only; other analysis methods are not assessed by this script',
        'cases': records, 'agent_status': str(out / 'agent/task-status.json'),
        'all_expected_outcomes': True, 'whole_product_pass_available': False,
        'source_sha256': sha256(Path(__file__))}
    write_json(out / 'verification.json', summary)
    print(json.dumps({'out': str(out), 'all_expected_outcomes': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
