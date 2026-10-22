"""Agent-authored use scenarios and scoped checks; never an automatic solver router.

Planning validates explicit reasoning/data. It cannot infer physical facts from a
product name, execute checks, or certify that the chosen scope is sufficient.
"""
from __future__ import annotations

import copy
import html
import json
from pathlib import Path

from .case import sha256, write_json
from .signals import digest

SCHEMA = 'simplecae-use-plan-1.0'
METHODS = {'geometry', 'calculation', 'fem', 'physical_test', 'information'}
DECISIONS = {'now', 'later', 'needs_information', 'unsupported'}


def computed_check(check):
    """Explicit internal computation, distinct from an external calculation receipt."""
    return check['decision'] == 'now' and (check['method'] == 'fem' or
        (check['method'] == 'calculation' and bool(check.get('result_criteria'))))


def validate_computation(check, case):
    if case.get('schema_version') in ('fatigue-data-1.0', 'creep-data-1.0'):
        if check['method'] != 'calculation':
            raise ValueError('Material-curve durability screens are calculation checks, not spatial fatigue/creep FEM')
        return
    if case.get('schema_version') == 'motion-loads-1.0':
        if check['method'] != 'calculation':
            raise ValueError('Rigid motion loads require method calculation; strength needs a separate FEM check')
        return
    if case.get('schema_version') == 'modal-solid-1.0':
        if check['method'] != 'fem':
            raise ValueError('Solid modal analysis requires method fem')
        return
    if case.get('schema_version') == 'thermal-solid-1.0':
        if check['method'] != 'fem':
            raise ValueError('Solid thermal fields require method fem')
        return
    if case.get('schema_version') == 'thermal-network-1.0':
        if check['method'] != 'calculation':
            raise ValueError('Thermal network is a calculation, not a solid temperature FEM')
        return
    if check['method'] == 'calculation' and (case.get('schema_version') != 'robot-1.0' or
            any(case.get(k) for k in ('components', 'required_components', 'elastic_transfer', 'probes'))):
        raise ValueError('Computed calculation requires a rigid robot-1.0 case without component FEM, elastic transfer or probes; use fem for structural fields')


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be nonempty text')


def _texts(value, name, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f'{name} must be a list' + (' with at least one entry' if nonempty else ''))
    for item in value:
        _text(item, name)


def validate_plan(plan):
    required = {'schema_version', 'task_id', 'request', 'scenarios', 'checks', 'unknowns', 'iteration_constraints'}
    if not isinstance(plan, dict) or set(plan) != required or plan.get('schema_version') != SCHEMA:
        raise ValueError('Expected a complete simplecae-use-plan-1.0 object; unknown fields are rejected')
    for key in ('task_id', 'request'):
        _text(plan[key], key)
    for key in ('unknowns', 'iteration_constraints'):
        _texts(plan[key], key)
    if not isinstance(plan['scenarios'], list) or not plan['scenarios']:
        raise ValueError('At least one use scenario is required')
    scenarios = set()
    for s in plan['scenarios']:
        if not isinstance(s, dict) or set(s) != {'id', 'use', 'success'}:
            raise ValueError('Each scenario requires exactly id, use and success')
        for key in s:
            _text(s[key], 'scenario.' + key)
        if s['id'] in scenarios:
            raise ValueError('Duplicate scenario id')
        scenarios.add(s['id'])
    if not isinstance(plan['checks'], list) or not plan['checks']:
        raise ValueError('At least one explicit check is required')
    ids = set()
    keys = {'id', 'scenario', 'question', 'user_impact', 'method', 'decision', 'targets',
            'reason', 'required_for_claim', 'acceptance', 'assumptions', 'not_assessed'}
    optional = {'load_path', 'load_basis', 'support_basis', 'result_criteria', 'case_path'}
    for index,c in enumerate(plan['checks']):
        if not isinstance(c, dict) or not keys <= set(c) or set(c) - keys - optional:
            missing=sorted(keys-set(c)) if isinstance(c,dict) else sorted(keys)
            extra=sorted(set(c)-keys-optional) if isinstance(c,dict) else []
            raise ValueError(f'checks[{index}]: missing fields {missing}; unknown fields {extra}. '
                'Use task scaffold for a complete check. Examples: method="fem", decision="needs_information", '
                'required_for_claim=true, assumptions=[], not_assessed=["Actual mounting remains unverified"].')
        for key in keys - {'targets', 'required_for_claim', 'assumptions', 'not_assessed'}:
            _text(c[key], 'check.' + key)
        if c['id'] in ids:
            raise ValueError('Duplicate check id')
        ids.add(c['id'])
        if c['scenario'] not in scenarios or c['method'] not in METHODS or c['decision'] not in DECISIONS:
            raise ValueError('Unknown scenario, check method or decision')
        if type(c['required_for_claim']) is not bool:
            raise ValueError('required_for_claim must be a boolean')
        for key in ('targets', 'assumptions', 'not_assessed'):
            _texts(c[key], 'check.' + key, nonempty=(key == 'targets'))
        for key in optional & set(c) - {'result_criteria'}:
            _text(c[key], 'check.' + key)
        if 'result_criteria' in c:
            _texts(c['result_criteria'], 'result_criteria', nonempty=True)
            if len(set(c['result_criteria'])) != len(c['result_criteria']):
                raise ValueError('Duplicate result criterion')
        if computed_check(c):
            for key in ('load_path', 'load_basis', 'support_basis'):
                _text(c.get(key), 'Ready FEM check.' + key)
            _texts(c.get('result_criteria'), 'Ready FEM/calculation check.result_criteria', nonempty=True)
        elif 'result_criteria' in c:
            raise ValueError('result_criteria binds an immediate FEM or computed calculation check only; deferred checks are not assessed')
        if 'case_path' in c and not computed_check(c):
            raise ValueError('case_path requires an immediate computed check')
    return plan


def read_plan(path):
    return validate_plan(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def plan_contract(plan):
    value = copy.deepcopy(plan)
    for c in value['checks']:
        c.pop('case_path', None)  # A geometry revision can use a fresh case path.
    return value


def render_check_scope(check):
    """Show the existing declared scope; never infer verification from its prose."""
    e = lambda value: html.escape(str(value))
    lines = ['<div class="check-scope"><p><strong>判据：</strong>' + e(check['acceptance']) + '</p>']
    for key, label in (('assumptions', '条件假设（非已验证事实）'), ('not_assessed', '未评估范围')):
        values = check.get(key, [])
        if values:
            lines.append('<p><strong>' + label + '：</strong></p><ul>' + ''.join('<li>' + e(v) + '</li>' for v in values) + '</ul>')
    latest = check.get('latest') or {}
    if latest:
        lines.append('<p>证据类型：' + e(latest.get('kind', 'unavailable')) + '</p>')
        if latest.get('summary'): lines.append('<p>' + e(latest['summary']) + '</p>')
        if latest.get('limitations'):
            lines.append('<p><strong>本次证据限制：</strong></p><ul>' + ''.join('<li>' + e(v) + '</li>' for v in latest['limitations']) + '</ul>')
    return ''.join(lines) + '</div>'


def prepare_plan(path, out):
    path, out = Path(path).resolve(), Path(out).resolve()
    plan = read_plan(path)
    now = [c for c in plan['checks'] if c['decision'] == 'now']
    fem = [c['id'] for c in now if c['method'] == 'fem']
    calculations = [c['id'] for c in now if c['method'] == 'calculation' and computed_check(c)]
    report = {'schema_version': 'simplecae-plan-review-1.0', 'plan': plan,
        'source': {'path': str(path), 'sha256': sha256(path)},
        'recommendation': 'targeted_fem' if fem else 'targeted_calculation' if calculations else 'needs_information' if any(
            c['required_for_claim'] and c['decision'] in ('needs_information', 'unsupported') for c in plan['checks']) else 'no_fem_now',
        'next_checks': [c['id'] for c in now], 'fem_checks': fem, 'calculation_checks': calculations,
        'unresolved_required_checks': [c['id'] for c in plan['checks'] if c['required_for_claim']],
        'worker_started': False, 'checks_executed': [], 'whole_product_pass_available': False,
        'meaning': 'A recorded Agent plan, not completed engineering evidence. No keyword-based product routing; no automatic model modification or solve.'}
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'plan-review.json', report)
    write_json(out / 'plan.json', plan)
    e = lambda x: html.escape(str(x))
    rows = ''.join('<tr><td>' + '</td><td>'.join(e(c[k]) for k in ('question', 'user_impact', 'method', 'decision'))
                   + '<td>' + e(', '.join(c['targets'])) + '</td><td>' + e(c['reason']) + render_check_scope(c) + '</td></tr>' for c in plan['checks'])
    (out / 'plan-review.html').write_text('<!doctype html><meta charset="utf-8"><title>SimpleCAE · 使用检查计划</title>'
        '<style>body{font:15px/1.6 system-ui;max-width:1150px;margin:32px auto;padding:0 20px;color:#20252a}td,th{padding:10px;text-align:left;border-bottom:1px solid #ddd}table{border-collapse:collapse}pre{white-space:pre-wrap}</style>'
        '<h1>本次先检查什么</h1><p>' + e(plan['request']) + '</p>'
        + ''.join('<p><strong>' + e(s['use']) + '</strong><br>使用目标：' + e(s['success']) + '</p>' for s in plan['scenarios'])
        + '<p>这是计划，尚未执行检查；暂缓有限元不代表强度通过。</p><table><tr><th>问题</th><th>对使用的影响</th><th>方法</th><th>时机</th><th>对象</th><th>理由</th></tr>'
        + rows + '</table><h2>缺失信息与迭代边界</h2><pre>'
        + e(json.dumps({k: plan[k] for k in ('unknowns', 'iteration_constraints')}, ensure_ascii=False, indent=2))
        + '</pre><p><a href="plan-review.json">Agent JSON</a></p>', encoding='utf-8')
    return report


def bind_plan(path, check_id, case_path):
    path, case_path = Path(path).resolve(), Path(case_path).resolve()
    plan = read_plan(path)
    selected = next((c for c in plan['checks'] if c['id'] == check_id), None)
    if selected is None or not computed_check(selected):
        raise ValueError('Select an immediate FEM or computed calculation check; deferred, geometry and missing-information checks cannot start a solver')
    if selected['method'] == 'calculation':
        from .api import check_case
        validate_computation(selected, check_case(case_path))
    if selected.get('case_path'):
        expected = Path(selected['case_path'])
        if not expected.is_absolute():
            expected = path.parent / expected
        if expected.resolve() != case_path:
            raise ValueError('Selected plan check binds a different case_path')
    scenario = next(s for s in plan['scenarios'] if s['id'] == selected['scenario'])
    return {'source': {'path': str(path), 'sha256': sha256(path)}, 'contract': plan_contract(plan),
        'contract_sha256': digest(plan_contract(plan)), 'selected_check_id': check_id,
        'scenario': copy.deepcopy(scenario), 'check': copy.deepcopy(selected),
        'other_required_checks': [c['id'] for c in plan['checks'] if c['required_for_claim'] and c['id'] != check_id]}


def validate_binding(binding):
    validate_plan(binding['contract'])
    if digest(binding['contract']) != binding['contract_sha256']:
        raise ValueError('Contradictory use-plan contract binding')
    cid = binding['selected_check_id']
    selected = next((c for c in binding['contract']['checks'] if c['id'] == cid), None)
    check = {k: v for k, v in binding['check'].items() if k != 'case_path'}
    if selected != check or not computed_check(selected):
        raise ValueError('Contradictory selected check')
    if binding['scenario'] != next(s for s in binding['contract']['scenarios'] if s['id'] == selected['scenario']):
        raise ValueError('Contradictory use scenario')
    remaining = [c['id'] for c in binding['contract']['checks'] if c['required_for_claim'] and c['id'] != cid]
    if binding['other_required_checks'] != remaining:
        raise ValueError('Contradictory remaining usage checks')


def usage_feedback(binding, feedback):
    validate_binding(binding)
    check = binding['check']
    evidence = feedback.get('criterion_assessments', {})
    utilizations = feedback.get('utilizations', {})
    missing = [name for name in check['result_criteria'] if name not in evidence and name not in utilizations]
    unresolved = [name for name in check['result_criteria'] if name in evidence and
                  evidence[name].get('status') not in ('pass_under_stated_model', 'fail_under_stated_model')]
    failed = {name: evidence[name] for name in check['result_criteria'] if name in evidence and
              evidence[name].get('status') == 'fail_under_stated_model'}
    valid = feedback.get('valid_for_comparison', False)
    passed = feedback.get('conditional_model_pass')
    state = 'insufficient_evidence' if missing or unresolved or not valid or passed is None else 'pass_under_stated_model' if passed else 'fail_under_stated_model'
    action = 'resolve_analysis_or_inputs' if state == 'insufficient_evidence' else 'revise_targeted_design' if state == 'fail_under_stated_model' else 'keep_and_check_remaining_requirements'
    blocked = state == 'fail_under_stated_model' and feedback.get('cad_iteration_blocked') is True
    if blocked:
        action = 'resolve_analysis_or_inputs'
    # A located numerical observation is not a proven physical root cause.
    return {'scenario': binding['scenario'], 'check_id': check['id'], 'question': check['question'],
        'user_impact': check['user_impact'], 'targets': check['targets'], 'acceptance': check['acceptance'],
        'status': state, 'missing_result_criteria': missing, 'unresolved_result_criteria': unresolved, 'action': action,
        'confirmed_failed_criteria': failed,
        'governing': feedback.get('governing_criterion'),
        'located_observations': feedback.get('observations', []),
        'cad_iteration': {'requires_reanalysis': state == 'fail_under_stated_model' and not blocked,
            'reanalysis_trigger': 'after_input_or_analysis_repair_if_needed' if blocked
                else 'after_design_change' if state == 'fail_under_stated_model'
                else 'after_input_or_analysis_repair_if_needed' if state == 'insufficient_evidence'
                else 'none_for_this_check',
            'instruction': 'Link the valid failed criterion and located region to one actual CAD parameter; explain the mechanical hypothesis, preserve the task, and recheck fit/motion/interfaces after the edit.' if action == 'revise_targeted_design'
                else 'Resolve the documented boundary/requirement conflict before CAD iteration; retain the failed result and do not silently change conditions or acceptance limits.' if blocked
                else 'Resolve missing criteria, model validity or execution first; do not diagnose weak geometry from an incomplete solve.' if action == 'resolve_analysis_or_inputs'
                else 'No automatic CAD change is required by a passing scoped check. Continue the remaining usage checks.',
            'preserve': binding['contract']['iteration_constraints']},
        'remaining_required_checks': binding['other_required_checks'],
        'not_assessed': list(dict.fromkeys(check['not_assessed'] + feedback.get('not_assessed', []))),
        'whole_product_pass_available': False}


def review_usage_feedback(review):
    """Recompute completed usage evidence from the bound raw result, not a summary."""
    bound = review['usage_plan']
    validate_binding(bound)
    source_feedback = review['feedback']
    if review.get('execution', {}).get('state') == 'completed':
        p = Path(review['result']['path'])
        if sha256(p) != review['result']['sha256']:
            raise ValueError('Usage result evidence changed')
        raw = json.loads(p.read_text(encoding='utf-8-sig'))
        if raw.get('case', {}).get('provenance', {}).get('task_id') != bound['contract']['task_id']:
            raise ValueError('Use-plan task differs from bound numerical result')
        from .design_check import feedback
        source_feedback = feedback(raw, review['context'], 'completed')
    expected = usage_feedback(bound, source_feedback)
    if expected != review.get('usage_feedback'):
        raise ValueError('Usage feedback contradicts its bound result/check')
    return expected


def render_usage_summary(review):
    """A short human summary; raw observations remain available in the JSON."""
    u = review['usage_feedback']
    e = lambda x: html.escape(str(x))
    states = {'pass_under_stated_model': '本项声明模型通过，实物适用性仍需核验',
              'fail_under_stated_model': '本项声明模型不满足要求', 'insufficient_evidence': '本项证据不足，不能授予通过'}
    actions = {'resolve_analysis_or_inputs': '先补输入或解决分析问题；不把计算失败诊断成结构过弱。',
               'revise_targeted_design': '根据已确认的失败和定位证据，提出一个实际CAD参数的修改假设并复验。',
               'keep_and_check_remaining_requirements': '保留本轮设计，继续其余使用要求。'}
    remaining = [c['question'] for c in review['usage_plan']['contract']['checks'] if c['id'] in u['remaining_required_checks']]
    lines = ['<h2>本次使用目标与设计反馈</h2><p><strong>' + e(states[u['status']]) + '</strong></p>',
        '<p>使用方式：' + e(u['scenario']['use']) + '<br>希望达到：' + e(u['scenario']['success']) + '</p>',
        '<p>本轮问题：' + e(u['question']) + '<br>关注对象：' + e('、'.join(u['targets']))
        + '<br>影响使用：' + e(u['user_impact']) + '</p>', '<p>下一步：' + e(actions[u['action']]) + '</p>']
    if u['missing_result_criteria'] or u['unresolved_result_criteria']:
        lines.append('<p>缺失或未解决的结果判据：' + e('、'.join(u['missing_result_criteria'] + u['unresolved_result_criteria'])) + '</p>')
    if u['confirmed_failed_criteria']:
        lines.append('<p>已确认不满足：' + e('、'.join(u['confirmed_failed_criteria'])) + '</p>')
    if remaining:
        lines.append('<p>本项分析不覆盖的其他必检项（已完成情况见任务检查进度）：</p><ul>' + ''.join('<li>' + e(q) + '</li>' for q in remaining) + '</ul>')
    lines.append('<p>本项结果不代表整机／安装／产品通过。数值、热点和完整证据见原始分析与Agent JSON。</p>')
    return ''.join(lines)
