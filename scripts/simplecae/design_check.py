"""Bounded design checks using the existing solvers and unchanged acceptance gates.

The caller supplies the mechanical model. Depth never rewrites its physics.
An owned worker process provides a total wall-clock budget, including meshing.
"""
from __future__ import annotations
from .defaults import DEFAULT_EXECUTION_BUDGET
from .defaults import MAX_WAIT_SECONDS

import copy
import html
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from .case import sha256, write_json
from .signals import compare_results, design_signal, digest
from .paths import worker_entry
from .execution import stop_worker, worker_group_options


def read_context(path):
    context = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    allowed = {'question', 'scope', 'assumptions', 'not_assessed', 'change_hypothesis'}
    if not isinstance(context, dict) or set(context) - allowed:
        raise ValueError('Design context must contain only question, scope, assumptions, not_assessed and optional change_hypothesis')
    for key in ('question', 'scope'):
        if not isinstance(context.get(key), str) or not context[key].strip():
            raise ValueError(f'Design context requires a nonempty {key}')
    for key in ('assumptions', 'not_assessed'):
        if not isinstance(context.get(key), list) or any(not isinstance(v, str) or not v.strip() for v in context[key]):
            raise ValueError(f'Design context requires an explicit list of nonempty strings (may be empty): {key}')
    if 'change_hypothesis' in context and not isinstance(context['change_hypothesis'], str):
        raise ValueError('change_hypothesis must be text, not executable instructions')
    return context


def detailed_features(case, path, seen=None):
    """Inspect only declared JSON; do not import native CAD libraries in supervisor."""
    seen = set() if seen is None else seen
    path = Path(path).resolve()
    if path in seen:
        raise ValueError('Cyclic component case references')
    seen = seen | {path}
    features = []
    if case.get('bolts'):
        features.append('bolt preload/locking')
    if any(c.get('type') in ('frictionless_contact', 'frictional_contact') for c in case.get('connections', [])):
        features.append('nonlinear contact')
    if case.get('buckling', {}).get('enabled'):
        features.append('elastic buckling')
    for component in case.get('components', []):
        child = Path(component['case_path'])
        if not child.is_absolute():
            child = path.parent / child
        features.extend(detailed_features(json.loads(child.read_text(encoding='utf-8-sig')), child, seen))
    return sorted(set(features))


def joint_displacement_guidance(result, governing, failed):
    """Explain a controlling measured joint term, without changing any verdict."""
    case=result.get('case',{})
    transfer=case.get('elastic_transfer',{})
    if result.get('status') not in ('invalid',None) and case.get('probes') and transfer and not transfer.get('joints_locked_verified') and not transfer.get('joint_compliance'):
        return {'focus':'joint_compliance','evidence_status':'needs_information',
                'message':'末端定位检查缺少输出侧关节刚度或关节锁定证据。先取得保持姿态、控制状态和刚度/回差数据；URDF effort 是力矩限值，不能换算成刚度。当前连杆位移不能解释完整的实测下垂。'}
    name = (governing or {}).get('name')
    for pose in result.get('poses', []):
        assessment = pose.get('task_probe_assessment') or {}
        contributions = (assessment.get('displacement_contributions') or {}).get('full', {})
        for spec in result.get('case', {}).get('probes', []):
            key = f"{pose['name']}/probe:{spec['name']}"
            if key != name or key not in failed or spec['name'] not in contributions:
                continue
            measured = contributions[spec['name']]
            limit = spec.get('max_displacement_mm')
            if not isinstance(limit, (int, float)) or not limit > 0:
                continue
            direction = spec.get('direction')
            def scalar(vector):
                if direction is None:
                    return math.sqrt(sum(v*v for v in vector))
                norm = math.sqrt(sum(v*v for v in direction))
                return abs(sum(a*b for a,b in zip(vector,direction))) / norm
            joint = scalar(measured['joint_vector_mm'])
            if joint > limit:
                return {'focus': 'joint_compliance', 'pose': pose['name'], 'probe': spec['name'],
                    'joint_contribution_mm': joint, 'link_contribution_mm': scalar(measured['link_vector_mm']),
                    'total_mm': scalar(measured['total_vector_mm']), 'allowable_mm': limit,
                    'message': '该任务方向的关节贡献本身已超过限值。先复核输出侧刚度和保持参考，再评估允许的系统修改；只加厚连杆不能保证解决。贡献按声明方向投影或向量模计算，不能把两个模长相加。'}
    return None


def feedback(result, context, run_state):
    if result.get('analysis') in ('fatigue_data', 'creep_data'):
        from .durability import design_feedback
        return design_feedback(result, context, run_state)
    if result.get('analysis') == 'motion_loads':
        from .motion import design_feedback
        return design_feedback(result, context, run_state)
    if result.get('analysis') == 'modal':
        from .modal import design_feedback
        return design_feedback(result, context, run_state)
    if result.get('analysis') == 'thermal_solid':
        from .thermal_solid import design_feedback
        return design_feedback(result, context, run_state)
    """Keep usable criterion findings and raw observations distinct from acceptance."""
    if result.get('analysis') == 'thermal_network':
        from .thermal_network import design_feedback
        return design_feedback(result, context, run_state)
    signal_value = design_signal(result)
    findings = copy.deepcopy(signal_value['feedback'])
    findings.extend(result.get('cad_metadata',[]))
    assessment = result.get('assessment', {})
    observations = []
    stages = [('service', result.get('levels', []))]
    # Stage assessments carry convergence decisions; observations below retain
    # every accepted mesh endpoint, including non-governing/global peaks.
    for stage, levels in stages:
        for level in levels:
            r = level.get('results', {})
            observations.append({'stage': stage, 'mesh_size_mm': level.get('mesh_size_mm'),
                'directory': level.get('directory'), 'strength_peak': r.get('strength_peak'),
                'peak_stress_element_centroid_mm': r.get('peak_element_centroid_mm'),
                'max_von_mises_mpa': r.get('max_von_mises_mpa'),
                'max_displacement_mm': r.get('max_displacement_mm'),
                'numerical_acceptance_complete': signal_value['valid_for_comparison']})
            for load in level.get('mesh',{}).get('loads',[]):
                diagnostic=load.get('distribution_diagnostic',{})
                if diagnostic.get('warnings') or diagnostic.get('assumptions'):
                    findings.append({'kind':'load_distribution','stage':stage,'load':load.get('name'),
                                     'mesh_size_mm':level.get('mesh_size_mm'),**diagnostic})
    criteria = signal_value.get('criterion_assessments', {})
    utilizations = dict(signal_value.get('utilizations', {}))
    utilizations.update({name: e.get('utilization') for name, e in criteria.items()})
    measured = [(name, value) for name, value in utilizations.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)]
    governing = max(measured, key=lambda item: item[1]) if measured else None
    failed_criteria={name:e for name,e in criteria.items() if e.get('status')=='fail_under_stated_model'}
    if failed_criteria:
        failed_measured=[item for item in measured if item[0] in failed_criteria]
        governing=max(failed_measured,key=lambda item:item[1]) if failed_measured else (next(iter(failed_criteria)),None)
    stage_findings = {name: {'strength_utilization': a.get('strength_utilization'),
                            'strength_peak': a.get('strength_peak'),
                            'status': a.get('status')}
                      for name, a in result.get('stage_assessments', {}).items()}
    if result.get('levels'):
        peak = result['levels'][-1].get('results', {}).get('strength_peak')
        confirmed_failure = any(c.get('status') == 'fail_under_stated_model' for c in criteria.values()) or (
            signal_value['valid_for_comparison'] and signal_value['feasible_under_stated_model'] is False)
        findings.append({'kind': 'design_hypothesis' if confirmed_failure else 'design_observation', 'scope': 'local_load_path',
            'service_strength_peak': peak, 'stage_strength_findings': stage_findings,
            'requires_reanalysis': confirmed_failure,
            'message': 'Use the located strength peak and displacement direction to investigate the confirmed failure; a small displacement alone does not establish strength.' if confirmed_failure
                else 'Uncropped location evidence is retained. No confirmed failure here requires an automatic geometry change.',
            'suggestion': 'Compare section depth, real transition radius or load-spreading area at the controlling region. Change one relevant parameter first; retain loads, materials, mounting and acceptance gates.' if confirmed_failure
                else 'Keep a passing geometry unless the user has a further optimization objective. For incomplete evidence, resolve validity before interpreting a peak as weak geometry.'})
    actions = []
    singularity=result.get('singularity_diagnostic')
    if singularity and singularity.get('classification')=='likely_singular':
        findings.append({'kind':'singularity_hypothesis',**singularity})
        actions.append('Review the located CAD edge and physical load/support transition, then make the indicated CAD change and reanalyze. Further refinement alone is not the next action; raw peaks and criteria are retained.')
    if run_state == 'budget_exhausted':
        actions.append('Inspect the last real stage in worker.stderr.log. Continue detailed verification only if it can change the design decision; an unfinished model has no passing verdict or comparison margin.')
    elif result.get('error'):
        actions.append('Resolve the recorded numerical/model error before accepting this model; preserve raw diagnostics and failed attempts.')
    elif not signal_value['valid_for_comparison']:
        actions.append('Inspect the located peak against the actual support/load transition and model assumptions; resolve missing criteria or mesh/validity evidence. Do not omit the hotspot or declare a singularity without evidence. Raw observations are not a ranked improvement.')
    elif signal_value['feasible_under_stated_model'] is True:
        actions.append('Retain the passing scoped geometry and continue the remaining use requirements. A passing check does not require an automatic CAD change or establish a product rating.')
    else:
        actions.append('Generate a revision from the located finding, then repeat with the same task contract and design context; compare only completed valid results.')
    guidance = joint_displacement_guidance(result,
        {'name': governing[0]} if governing else None,
        {k: v for k, v in criteria.items() if v.get('status') == 'fail_under_stated_model'})
    if guidance and (guidance.get('evidence_status')=='needs_information' or
                     signal_value['valid_for_comparison'] and signal_value['feasible_under_stated_model'] is False):
        actions[0] = guidance['message']
        findings.append({'kind': 'design_guidance', 'scope': 'joint_compliance', **guidance})
    if governing and '/actuator/' in governing[0] and signal_value['valid_for_comparison'] and signal_value['feasible_under_stated_model'] is False:
        findings.append({'kind': 'design_hypothesis', 'scope': 'actuator_load_path',
            'governing': {'name': governing[0], 'utilization': governing[1]}, 'requires_reanalysis': True,
            'suggestion': 'Inspect the governing pose and actuator reaction path. Consider geometry, leverage or mass distribution within the allowed design changes; rerun all required poses. Do not increase an actuator rating or reduce the required load to make the same task pass.'})
    actions.append('Keep the required loads, poses, materials, fixtures and acceptance gates unchanged. Apply only CAD changes allowed by the task; existing suggestions are hypotheses, not authorization to relax requirements.')
    for finding in findings:
        if finding.get('kind')=='unresolved_local_stress':
            actions.insert(0,finding['message']+' '+finding['suggestion'])
    if context['assumptions']:
        actions.append('Verify the highest-impact physical assumption before a product claim: ' + context['assumptions'][0])
    return {'model_status': result.get('status', 'incomplete'),
            'valid_for_comparison': signal_value['valid_for_comparison'],
            'conditional_model_pass': signal_value['feasible_under_stated_model'],
            'whole_product_pass_available': False,
            'governing_criterion': {'name': governing[0], 'utilization': governing[1]} if governing else None,
            'criterion_assessments': criteria, 'utilizations': utilizations, 'findings': findings,
            'observations': observations, 'next_actions': actions,
            'not_assessed': list(dict.fromkeys(context['not_assessed'] + signal_value['not_assessed'])),
            'verification': assessment.get('verification', {}),
            'meaning': 'Conclusions apply only to the explicit mechanical model and stated assumptions. No installation/product rating. Unresolved observations have no favorable ranking or capacity.'}


def write_review(out, review):
    write_json(out / 'design-review.json', review)
    # Plain, portable review alongside the unchanged solver report and Viewer.
    escape = lambda value: html.escape(json.dumps(value, ensure_ascii=False, indent=2))
    from .use_plan import render_usage_summary
    (out / 'design-review.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>SimpleCAE design check</title>'
        '<style>body{font:15px/1.6 system-ui;max-width:1000px;margin:32px auto;padding:0 20px;color:#20252a}pre{white-space:pre-wrap;background:#f3f4f5;padding:16px}a{color:#185e9b}</style>'
        '<h1>SimpleCAE · 设计检查</h1><p>条件模型结论与产品通过分别记录；未完成的分析不能用于排名。</p>'
        '<p>' + ('<a href="analysis/report.html">原始分析报告</a> · ' if (out / 'analysis/report.html').is_file() else '')
        + '<a href="design-review.json">Agent JSON</a>'
        + (' · <a href="worker.stderr.log">执行日志</a> · <a href="worker.stdout.log">原始输出</a>' if (out / 'worker.stderr.log').is_file() else '') + '</p>'
        + (render_usage_summary(review) if review.get('usage_feedback') else '')
        + '<h2>问题与范围</h2><pre>' + escape(review['context']) + '</pre>'
        '<h2>执行与预算</h2><pre>' + escape(review['execution']) + '</pre>'
        '<h2>设计反馈</h2><pre>' + escape(review['feedback']) + '</pre>', encoding='utf-8')


def design_check(case_path, out, *, context_path, depth='design', budget_seconds=DEFAULT_EXECUTION_BUDGET,
                 ccx=None, timeout='auto', preview=True, viewer_session=None,
                 label=None, change_note='', predict_capacity=False, storage='compact',
                 plan_path=None, check_id=None, reuse_levels=None):
    from .retention import validate_storage, retain_output
    validate_storage(storage)
    if depth not in ('design', 'detailed'):
        raise ValueError('depth must be design or detailed')
    from .solver import execution_threads
    execution_threads()  # Validate explicit requests; auto selects per native deck.
    if not isinstance(predict_capacity, bool):
        raise ValueError('predict_capacity must be a boolean')
    automatic_timeout=isinstance(timeout,str) and timeout=='auto'
    for name, value in [('budget_seconds', budget_seconds)]+([] if automatic_timeout else [('timeout', timeout)]):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= MAX_WAIT_SECONDS:
            raise ValueError(f'{name} must be finite, positive and within the platform wait range')
    case_path, out = Path(case_path).resolve(), Path(out).resolve()
    context_path = Path(context_path).resolve()
    context = read_context(context_path)
    if bool(plan_path) != bool(check_id):
        raise ValueError('Supply both plan_path and check_id')
    usage = None
    if plan_path:
        from .use_plan import bind_plan
        usage = bind_plan(plan_path, check_id, case_path)
    case = json.loads(case_path.read_text(encoding='utf-8-sig'))
    if reuse_levels is not None:
        from .api import check_case
        from .level_cache import validate_request
        validate_request(check_case(case_path), reuse_levels, out)
    if usage and case.get('schema_version') in ('thermal-network-1.0', 'thermal-solid-1.0', 'modal-solid-1.0', 'motion-loads-1.0', 'fatigue-data-1.0', 'creep-data-1.0'):
        from .use_plan import validate_computation
        validate_computation(usage['check'], case)
    if case.get('schema_version') in ('thermal-network-1.0', 'thermal-solid-1.0', 'modal-solid-1.0', 'motion-loads-1.0', 'fatigue-data-1.0', 'creep-data-1.0') and predict_capacity:
        raise ValueError('Thermal/modal/motion/durability analysis does not provide automatic capacity/lifetime extrapolation')
    if usage and case.get('provenance', {}).get('task_id') != usage['contract']['task_id']:
        raise ValueError('Case task_id must match the selected use plan')
    features = detailed_features(case, case_path)
    out.mkdir(parents=True, exist_ok=False)
    review = {'schema_version': 'simplecae-design-review-1.0', 'context': context,
        'context_contract_sha256': digest({k:v for k,v in context.items() if k != 'change_hypothesis'}),
        'inputs': {str(case_path): sha256(case_path), str(context_path): sha256(context_path)},
        'depth': depth, 'detailed_features': features,
        'analysis_options': {'predict_capacity': predict_capacity}}
    from .execution import hardware_snapshot
    review['resource_plan']={'hardware':hardware_snapshot(),
        'requested_threads':None if os.environ.get('SIMPLECAE_SOLVER_THREADS','auto')=='auto' else execution_threads(),
        'thread_policy':os.environ.get('SIMPLECAE_SOLVER_THREADS','auto'),
        'timeout_policy':'shared_total_budget' if automatic_timeout else 'explicit_per_solve_cap',
        'per_solve_timeout_seconds':None if automatic_timeout else timeout,
        'total_budget_seconds':budget_seconds,
        'meaning':'Total worker deadline remains enforced. Automatic threads use an applicable measured same-deck profile, otherwise serial. Per-deck decisions are recorded by the solver. CPU count does not establish correctness. Physics and acceptance gates are unchanged.'}
    if usage:
        review['usage_plan'] = usage
    if depth == 'design' and features:
        review['execution'] = {'state': 'needs_explicit_model', 'budget_seconds': budget_seconds,
            'elapsed_seconds': 0, 'worker_started': False}
        review['feedback'] = {'model_status': 'not_run', 'valid_for_comparison': False,
            'conditional_model_pass': None, 'whole_product_pass_available': False,
            'next_actions': ['Use --depth detailed for these declared features, or supply a separate explicitly justified linear design model. No contacts, bolts or requested buckling were removed.'],
            'not_assessed': context['not_assessed']}
        if usage:
            from .use_plan import usage_feedback
            review['usage_feedback'] = usage_feedback(usage, review['feedback'])
        write_review(out, review)
        return review
    command = [sys.executable, worker_entry(),
               'analyze', str(case_path), '--out', str(out / 'analysis'),
               '--timeout', str(budget_seconds if automatic_timeout else min(timeout, budget_seconds)), '--storage', 'full']
    if reuse_levels is not None:
        command += ['--reuse-levels', str(Path(reuse_levels).resolve())]
    if not predict_capacity:
        command += ['--no-capacity']
    if ccx:
        from .solver import find_ccx
        command += ['--ccx', str(find_ccx(ccx))]
    if not preview:
        command += ['--no-preview']
    if viewer_session:
        command += ['--viewer-session', str(Path(viewer_session).resolve()), '--change-note', change_note]
        if label:
            command += ['--label', label]
    started = time.monotonic()
    process = None
    state = 'completed'
    from .process_lock import identity
    ownership=out/'worker-ownership.json'
    write_json(ownership,{'owner':identity(),'worker':None,'deadline_monotonic':started+budget_seconds})
    worker_env=dict(os.environ,SIMPLECAE_WORKER_OWNERSHIP=str(ownership.resolve()))
    with (out / 'worker.stdout.log').open('wb') as stdout, (out / 'worker.stderr.log').open('wb') as stderr:
        try:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                env=worker_env,**worker_group_options())
            try:
                process.wait(timeout=max(0, budget_seconds - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                state = 'budget_exhausted'
                stop_worker(process)
        except BaseException:
            if process is not None:
                stop_worker(process)
            raise
    elapsed = time.monotonic() - started
    # All native descendants have stopped. Compact outside the solve budget,
    # without changing result bytes, Viewer field bindings or numerical gates.
    if (out / 'analysis').is_dir():
        review['storage'] = {k:v for k,v in retain_output(out / 'analysis', storage).items()
                             if k in ('mode','saved_bytes','errors')}
    result_path = out / 'analysis' / 'result.json'
    result = {'case': case}
    result_read_error = None
    if result_path.exists():
        try:
            loaded = json.loads(result_path.read_text(encoding='utf-8-sig'))
            if not isinstance(loaded, dict):
                raise ValueError('result must be a JSON object')
            result = loaded
        except (OSError, ValueError) as exc:
            result_read_error = f'{type(exc).__name__}: {exc}'
    # The worker may have written a status just before its final report; budget
    # expiry still withholds acceptance. Preserve its raw record unchanged.
    if state == 'budget_exhausted':
        result = copy.deepcopy(result)
        result.update(status='invalid', error='Total design-check budget exhausted; analysis is incomplete')
        result.pop('assessment', None)
    elif process.returncode != 0 or result_read_error or not result_path.exists() or not result.get('status'):
        state = 'analysis_failed'
        result = copy.deepcopy(result)
        result.update(status='invalid', error=result.get('error', 'Worker did not produce a completed result; inspect worker logs'))
        result.pop('assessment', None)
    if usage and (not Path(usage['source']['path']).is_file() or sha256(Path(usage['source']['path'])) != usage['source']['sha256']):
        state = 'analysis_failed'
        result = copy.deepcopy(result)
        result.update(status='invalid', error='Use plan changed during analysis; original numerical bytes retained, acceptance withheld')
        result.pop('assessment', None)
    review['execution'] = {'state': state, 'budget_seconds': budget_seconds,
        'elapsed_seconds': elapsed, 'worker_started': True, 'worker_pid': process.pid,
        'worker_returncode': process.returncode, 'command': command}
    if state in ('budget_exhausted','analysis_failed'):
        review['execution']['recovery']={'code':state,'retryable_unchanged':False,
            'next_action':'review_budget_and_completed_stages' if state=='budget_exhausted' else 'inspect_retained_diagnostics',
            'fields':['budget_seconds'] if state=='budget_exhausted' else [],
            'details':{'worker_log':str(out/'worker.stderr.log')}}
    if result_read_error:
        review['execution']['result_read_error'] = result_read_error
    events = []
    for line in (out / 'worker.stderr.log').read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line).get('simplecae_progress')
            if event:
                events.append(event)
        except (ValueError, AttributeError):
            pass
    review['execution']['last_recorded_stage'] = events[-1] if events else None
    review['execution']['completed_mesh_endpoints'] = len(result.get('levels', []))
    if viewer_session and state == 'budget_exhausted':
        # A killed worker cannot close its own stage record. Close only records
        # bound to our fresh, owned output; never leave a false live run behind.
        from .workbench import atomic_json, export_session, now
        try:
            for path in (Path(viewer_session) / 'runs').glob('*.json'):
                record = json.loads(path.read_text(encoding='utf-8-sig'))
                if record.get('out') == str(out / 'analysis') and record.get('state') == 'pending':
                    record.update(state='interrupted', error='Total design-check budget exhausted; no completed result accepted', finished_at_utc=now())
                    atomic_json(path, record)
            export_session(viewer_session)
        except Exception as exc:
            review['viewer_error'] = str(exc)
    review['feedback'] = feedback(result, context, state)
    if usage:
        from .use_plan import usage_feedback
        review['usage_feedback'] = usage_feedback(usage, review['feedback'])
    if result_path.exists():
        review['result'] = {'path': str(result_path)}
        try:
            review['result']['sha256'] = sha256(result_path)
        except OSError as exc:
            review['execution']['result_read_error'] = f'{type(exc).__name__}: {exc}'
    write_review(out, review)
    if viewer_session:
        try:
            from .workbench import atomic_json, export_session
            for path in (Path(viewer_session) / 'runs').glob('*.json'):
                record = json.loads(path.read_text(encoding='utf-8-sig'))
                if record.get('out') == str(out / 'analysis'):
                    record['design_review'] = {'path': str(out / 'design-review.json'), 'sha256': sha256(out / 'design-review.json')}
                    atomic_json(path, record)
            export_session(viewer_session)
        except Exception as exc:
            review['viewer_error'] = str(exc)
            # Do not rewrite a review already bound by the Viewer record.
    return review


def compare_design_checks(paths):
    if len(paths) < 2:
        raise ValueError('Compare at least two design reviews')
    reviews = [json.loads(Path(p).read_text(encoding='utf-8-sig')) for p in paths]
    reasons = []
    for review in reviews:
        if review.get('schema_version') != 'simplecae-design-review-1.0':
            raise ValueError('Expected a design review')
        if review.get('execution', {}).get('state') != 'completed' or not review.get('feedback', {}).get('valid_for_comparison'):
            reasons.append('At least one design check is unfinished, invalid or unresolved')
        result = review.get('result', {})
        if not result or not Path(result['path']).is_file() or sha256(Path(result['path'])) != result['sha256']:
            reasons.append('Missing or changed result evidence')
        if digest({k:v for k,v in review['context'].items() if k != 'change_hypothesis'}) != review.get('context_contract_sha256'):
            reasons.append('Contradictory design context binding')
        if review.get('usage_plan'):
            from .use_plan import review_usage_feedback
            try:
                if review_usage_feedback(review)['status'] == 'insufficient_evidence':
                    reasons.append('Selected usage criteria are unresolved')
            except (ValueError, KeyError, TypeError, OSError):
                reasons.append('Contradictory use-plan binding')
    if len({(r.get('usage_plan', {}).get('contract_sha256'), r.get('usage_plan', {}).get('selected_check_id')) for r in reviews}) != 1:
        reasons.append('Use scenario, selected check or plan scope differs')
    if len({r.get('context_contract_sha256') for r in reviews}) != 1 or len({r.get('depth') for r in reviews}) != 1:
        reasons.append('Decision question, model scope, assumptions, unassessed items or depth differ')
    comparison = compare_results([r['result']['path'] for r in reviews]) if not reasons else None
    if comparison:
        reasons.extend(comparison['withheld_reasons'])
    return {'schema_version': 'simplecae-design-comparison-1.0', 'comparable': not reasons,
            'withheld_reasons': reasons, 'comparison': comparison,
            'whole_product_pass_available': False}
