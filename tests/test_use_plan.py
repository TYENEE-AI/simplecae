"""Use-driven scope selection and non-promotion of partial/irrelevant evidence."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from simplecae.case import write_json, sha256
from simplecae.design_check import design_check, feedback, compare_design_checks
from simplecae.signals import digest
from simplecae.use_plan import read_plan, prepare_plan, bind_plan, usage_feedback, validate_binding
from test_design_check import context
from test_signals import result

ROOT = Path(__file__).resolve().parents[1]


def plan_file(tmp_path):
    p = tmp_path / 'use.json'
    value=read_plan(ROOT / 'examples/use-plans/bench-fixture.json')
    value['task_id']='fixture-task'
    write_json(p,value)
    return p


def binding(tmp_path):
    return bind_plan(plan_file(tmp_path), 'task-deflection', tmp_path / 'case.json')


@pytest.mark.parametrize('name,fem', [('manual-mechanism', []), ('wall-fixture', ['body-static']),
                                    ('robot-positioning', []), ('bench-fixture', ['task-deflection'])])
def test_real_scenario_plans_route_only_explicit_selected_work_without_executing(tmp_path, monkeypatch, name, fem):
    def forbidden(*args, **kwargs):
        raise AssertionError('Planning must not start any process')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    review = prepare_plan(ROOT / f'examples/use-plans/{name}.json', tmp_path / 'plan')
    assert review['fem_checks'] == fem
    assert not review['worker_started'] and review['checks_executed'] == []
    assert review['unresolved_required_checks']
    assert review['whole_product_pass_available'] is False
    assert json.loads((tmp_path / 'plan/plan.json').read_text(encoding='utf8')) == review['plan']


def test_product_name_does_not_select_the_algorithm(tmp_path):
    p = plan_file(tmp_path)
    a = prepare_plan(p, tmp_path / 'a')
    value = read_plan(p)
    value['request'] = 'An unrelated product name with <script>alert(1)</script>'
    write_json(p, value)
    b = prepare_plan(p, tmp_path / 'b')
    assert a['next_checks'] == b['next_checks'] and a['fem_checks'] == b['fem_checks']
    assert '<script>alert(1)</script>' not in (tmp_path / 'b/plan-review.html').read_text(encoding='utf8')


@pytest.mark.parametrize('change', ['duplicate', 'unknown_scenario', 'load_basis', 'result_criteria', 'unknown_field', 'boolean'])
def test_invalid_or_unjustified_ready_plan_is_rejected(tmp_path, change):
    p = plan_file(tmp_path); value = read_plan(p)
    if change == 'duplicate': value['checks'].append(copy.deepcopy(value['checks'][0]))
    elif change == 'unknown_scenario': value['checks'][0]['scenario'] = 'absent'
    elif change in ('load_basis', 'result_criteria'): value['checks'][0].pop(change)
    elif change == 'unknown_field': value['execute'] = 'not code'
    else: value['checks'][0]['required_for_claim'] = 1
    write_json(p, value)
    with pytest.raises(ValueError): prepare_plan(p, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('check_id', ['motion-fit', 'print-fit', 'stall-strength', 'absent'])
def test_no_non_fem_or_deferred_check_can_launch_design_worker(tmp_path, monkeypatch, check_id):
    c=tmp_path/'case.json';p=tmp_path/'context.json'
    write_json(c, result()['case']); write_json(p, context())
    module=importlib.import_module('simplecae.design_check')
    monkeypatch.setattr(module.subprocess,'Popen',lambda *a,**k: pytest.fail('Unexpected worker'))
    with pytest.raises(ValueError, match='immediate FEM'):
        design_check(c, tmp_path/'out', context_path=p,
                     plan_path=ROOT/'examples/use-plans/manual-mechanism.json', check_id=check_id)
    assert not (tmp_path/'out').exists()


def test_optional_case_binding_and_complete_open_scope(tmp_path):
    p=plan_file(tmp_path);value=read_plan(p);value['checks'][0]['case_path']='expected.json';write_json(p,value)
    with pytest.raises(ValueError, match='different case_path'): bind_plan(p,'task-deflection',tmp_path/'other.json')
    bound=bind_plan(p,'task-deflection',tmp_path/'expected.json')
    assert bound['other_required_checks']==['real-mount']
    bad=copy.deepcopy(bound);bad['other_required_checks']=[]
    with pytest.raises(ValueError,match='remaining'):validate_binding(bad)


def test_body_pass_does_not_fill_missing_user_measurement(tmp_path):
    bound=binding(tmp_path);value=feedback(result(),context(),'completed')
    assert usage_feedback(bound,value)['status']=='pass_under_stated_model'
    bound['check']['result_criteria'].append('task_probe:tip')
    bound['contract']['checks'][0]['result_criteria'].append('task_probe:tip')
    bound['contract_sha256']=digest(bound['contract'])
    u=usage_feedback(bound,value)
    assert u['status']=='insufficient_evidence' and u['missing_result_criteria']==['task_probe:tip']
    assert u['action']=='resolve_analysis_or_inputs' and not u['whole_product_pass_available']
    assert u['remaining_required_checks']==['real-mount']


def test_unassessed_strength_is_not_strength_evidence(tmp_path):
    value=feedback(result(),context(),'completed')
    value['criterion_assessments']['strength']['status']='not_assessed'
    u=usage_feedback(binding(tmp_path),value)
    assert u['status']=='insufficient_evidence' and u['unresolved_result_criteria']==['strength']


def test_error_is_not_weak_geometry_and_valid_failure_supplies_targeted_context(tmp_path):
    bound=binding(tmp_path);r=result()
    r.update(status='invalid',error='native startup failed');r.pop('assessment')
    u=usage_feedback(bound,feedback(r,context(),'analysis_failed'))
    assert u['action']=='resolve_analysis_or_inputs' and u['status']=='insufficient_evidence'
    assert u['targets']==bound['check']['targets']
    # Restore a consistent mathematically failed fixture, not a forged status.
    from simplecae.assessment import assess
    r=result()
    r['case']['criteria']['max_displacement_mm']=.01
    r['assessment']=assess(r['case'],r['levels']);r['status']=r['assessment']['status']
    u=usage_feedback(bound,feedback(r,context(),'completed'))
    assert u['status']=='fail_under_stated_model' and u['action']=='revise_targeted_design'
    assert u['confirmed_failed_criteria'] and u['cad_iteration']['preserve']


def test_bound_plan_change_during_worker_withholds_acceptance(tmp_path,monkeypatch):
    module=importlib.import_module('simplecae.design_check');real_popen=subprocess.Popen
    c=tmp_path/'case.json';p=tmp_path/'context.json';plan=plan_file(tmp_path)
    write_json(c,result()['case']);write_json(p,context())
    def worker(command,**options):
        dest=Path(command[command.index('--out')+1])
        script='import pathlib,json;p=pathlib.Path('+repr(str(dest))+');p.mkdir(parents=True);(p/"result.json").write_text('+repr(json.dumps(result()))+')'
        changed=read_plan(plan);changed['scenarios'][0]['success']='Changed acceptance meaning';write_json(plan,changed)
        return real_popen([sys.executable,'-c',script],**options)
    monkeypatch.setattr(module.subprocess,'Popen',worker)
    review=design_check(c,tmp_path/'out',context_path=p,plan_path=plan,check_id='task-deflection')
    assert review['execution']['state']=='analysis_failed'
    assert review['usage_feedback']['status']=='insufficient_evidence'
    assert json.loads((tmp_path/'out/analysis/result.json').read_text())['status']=='pass_under_stated_model'


def test_cli_plan_in_unicode_path_does_not_need_cad_or_solver(tmp_path):
    p=tmp_path/'需求 🦾.json';write_json(p,read_plan(ROOT/'examples/use-plans/manual-mechanism.json'))
    r=subprocess.run([sys.executable,str(ROOT/'scripts/simplecae_cli.py'),'plan',str(p),'--out',str(tmp_path/'审阅')],capture_output=True)
    assert r.returncode==0,r.stderr.decode('utf8')
    output=json.loads(r.stdout.decode('utf8'))
    assert output['fem_checks']==[] and output['worker_started'] is False


def test_viewer_preserves_usage_context_and_rejects_contradictory_feedback(tmp_path):
    from test_workbench import evidence
    from simplecae.workbench import create_session, add_result, atomic_json, snapshot
    session=create_session(tmp_path/'viewer');p=evidence(tmp_path,'body');bound=binding(tmp_path)
    f=feedback(json.loads(p.read_text(encoding='utf8')),context(),'completed')
    review={'schema_version':'simplecae-design-review-1.0','depth':'design','context':context(),
            'context_contract_sha256':digest(context()),'execution':{'state':'completed'},'feedback':f,
            'usage_plan':bound,'usage_feedback':usage_feedback(bound,f),'result':{'path':str(p),'sha256':sha256(p)}}
    q=tmp_path/'review.json';write_json(q,review)
    rid=add_result(session,p);rp=session/'runs'/f'{rid}.json';record=json.loads(rp.read_text())
    record['design_review']={'path':str(q),'sha256':sha256(q)};atomic_json(rp,record)
    run=snapshot(session)['runs'][0]
    assert run['usage_feedback']['user_impact']==bound['check']['user_impact']
    assert run['usage_feedback']['remaining_required_checks']==['real-mount']
    review['usage_feedback']['remaining_required_checks']=[];write_json(q,review)
    record['design_review']['sha256']=sha256(q);atomic_json(rp,record)
    assert snapshot(session)['runs'][0]['state']=='unavailable'


def test_comparison_rejects_changed_use_goal_and_mixed_planned_unplanned_runs(tmp_path):
    bound=binding(tmp_path);paths=[]
    for i in range(2):
        r=result();r['case']['model']['path']=f'geometry-{i}.step'
        p=tmp_path/f'result-{i}.json';write_json(p,r);f=feedback(r,context(),'completed')
        review={'schema_version':'simplecae-design-review-1.0','depth':'design','context':context(),
                'context_contract_sha256':digest(context()),'execution':{'state':'completed'},'feedback':f,
                'usage_plan':copy.deepcopy(bound),'usage_feedback':usage_feedback(bound,f),'result':{'path':str(p),'sha256':sha256(p)}}
        q=tmp_path/f'review-{i}.json';write_json(q,review);paths.append(q)
    assert compare_design_checks(paths)['comparable']
    review.pop('usage_plan');review.pop('usage_feedback');write_json(q,review)
    assert not compare_design_checks(paths)['comparable']


def test_completed_usage_summary_cannot_invent_a_missing_result_measurement(tmp_path):
    from simplecae.use_plan import review_usage_feedback
    bound=binding(tmp_path)
    bound['check']['result_criteria'].append('missing-tip')
    bound['contract']['checks'][0]['result_criteria'].append('missing-tip')
    bound['contract_sha256']=digest(bound['contract'])
    p=tmp_path/'result.json';write_json(p,result())
    f=feedback(result(),context(),'completed')
    f['criterion_assessments']['missing-tip']={'status':'pass_under_stated_model','utilization':.1}
    review={'usage_plan':bound,'usage_feedback':usage_feedback(bound,f),'feedback':f,
            'execution':{'state':'completed'},'context':context(),'result':{'path':str(p),'sha256':sha256(p)}}
    assert review['usage_feedback']['status']=='pass_under_stated_model'
    with pytest.raises(ValueError,match='bound result'):review_usage_feedback(review)


def test_wrong_task_is_rejected_before_any_worker(tmp_path,monkeypatch):
    c=tmp_path/'case.json';p=tmp_path/'context.json';plan=plan_file(tmp_path)
    value=result()['case'];value['provenance']['task_id']='different-task'
    write_json(c,value);write_json(p,context())
    module=importlib.import_module('simplecae.design_check')
    monkeypatch.setattr(module.subprocess,'Popen',lambda *a,**k: pytest.fail('Wrong task launched a worker'))
    with pytest.raises(ValueError,match='task_id'):
        design_check(c,tmp_path/'out',context_path=p,plan_path=plan,check_id='task-deflection')
    assert not (tmp_path/'out').exists()
