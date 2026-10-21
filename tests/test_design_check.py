"""Scope, budget and comparison failures must never become design approval."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from simplecae.case import write_json
from simplecae.design_check import design_check, feedback, read_context, compare_design_checks, detailed_features, stop_worker
from simplecae.signals import digest
from test_signals import result


def context():
    return {'question': 'Can this revision carry the declared load?',
            'scope': 'Linear part with declared equivalent support',
            'assumptions': ['Support stiffness is unmeasured'],
            'not_assessed': ['Anchor failure and long-term creep']}


def files(tmp_path, case=None):
    c=tmp_path/'case.json';p=tmp_path/'context.json'
    write_json(c,case or result()['case']);write_json(p,context())
    return c,p


def test_default_never_silently_removes_contact_or_preload(tmp_path):
    c,p=files(tmp_path, {'bolts':[{'name':'bolt'}], 'connections':[{'type':'frictional_contact'}]})
    original=c.read_bytes()
    review=design_check(c,tmp_path/'out',context_path=p)
    assert review['execution']['state']=='needs_explicit_model'
    assert review['execution']['worker_started'] is False
    assert review['feedback']['conditional_model_pass'] is None
    assert c.read_bytes()==original and not (tmp_path/'out/analysis').exists()


def test_invalid_thread_request_is_rejected_before_output(tmp_path,monkeypatch):
    c,p=files(tmp_path)
    monkeypatch.setenv('SIMPLECAE_SOLVER_THREADS','not-a-count')
    with pytest.raises(ValueError,match='available logical CPU'):
        design_check(c,tmp_path/'out',context_path=p)
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('partial,delay,budget,state',[('{',20,.5,'budget_exhausted'),('[]',0,5,'analysis_failed')])
def test_real_worker_partial_result_remains_reviewable(tmp_path,monkeypatch,partial,delay,budget,state):
    # __init__ exports design_check; explicitly import its defining module.
    import importlib
    module=importlib.import_module('simplecae.design_check')
    real_popen=subprocess.Popen
    def worker(command,**options):
        if '--out' not in command:return real_popen(command,**options)
        destination=Path(command[command.index('--out')+1])
        script='import pathlib,time;p=pathlib.Path('+repr(str(destination))+');p.mkdir(parents=True);(p/"result.json").write_text('+repr(partial)+');time.sleep('+str(delay)+')'
        return real_popen([sys.executable,'-c',script],**options)
    monkeypatch.setattr(module.subprocess,'Popen',worker)
    c,p=files(tmp_path);review=design_check(c,tmp_path/'out',context_path=p,budget_seconds=budget)
    assert review['execution']['state']==state
    assert review['execution']['result_read_error']
    assert (tmp_path/'out/analysis/result.json').read_text()==partial
    assert review['result']['sha256']
    assert not review['feedback']['valid_for_comparison']
    assert review['feedback']['conditional_model_pass'] is None
    assert 'analysis/report.html' not in (tmp_path/'out/design-review.html').read_text(encoding='utf-8')
    assert 'worker.stderr.log' in (tmp_path/'out/design-review.html').read_text(encoding='utf-8')


def test_actuator_governs_feedback_even_when_component_criteria_pass(monkeypatch):
    import importlib
    module=importlib.import_module('simplecae.design_check')
    original=module.design_signal
    def robot_signal(r):
        s=original(r);s['utilizations']['extended/actuator/shoulder']=30.
        s['feasible_under_stated_model']=False
        s['criterion_assessments']={'extended/arm/stiffness':{'utilization':.13,'status':'pass_under_stated_model'}}
        return s
    monkeypatch.setattr(module,'design_signal',robot_signal)
    review=feedback(result(),context(),'completed')
    assert review['governing_criterion']=={'name':'extended/actuator/shoulder','utilization':30.}
    assert any(f.get('scope')=='actuator_load_path' and f['requires_reanalysis'] for f in review['findings'])


def test_robot_nested_detailed_physics_is_not_missed(tmp_path):
    write_json(tmp_path/'part.json',{'buckling':{'enabled':True}})
    assert detailed_features({'components':[{'case_path':'part.json'}]},tmp_path/'robot.json')==['elastic buckling']
    write_json(tmp_path/'part.json',{'components':[{'case_path':'robot.json'}]})
    write_json(tmp_path/'robot.json',{'components':[{'case_path':'part.json'}]})
    with pytest.raises(ValueError,match='Cyclic'):detailed_features(json.loads((tmp_path/'robot.json').read_text()),tmp_path/'robot.json')


@pytest.mark.parametrize('budget',[0,-1,float('nan'),float('inf'),True,86401])
def test_invalid_budget_rejected_before_worker(tmp_path,budget):
    c,p=files(tmp_path)
    with pytest.raises(ValueError,match='budget_seconds'):design_check(c,tmp_path/'out',context_path=p,budget_seconds=budget)
    assert not (tmp_path/'out').exists()


def test_real_worker_startup_timeout_preserves_logs_without_acceptance(tmp_path):
    c,p=files(tmp_path)
    review=design_check(c,tmp_path/'out',context_path=p,budget_seconds=.001)
    assert review['execution']['state']=='budget_exhausted'
    assert review['execution']['elapsed_seconds']<15
    assert not review['feedback']['valid_for_comparison']
    assert review['feedback']['conditional_model_pass'] is None
    assert not review['feedback']['whole_product_pass_available']
    assert (tmp_path/'out/worker.stderr.log').exists()
    assert json.loads((tmp_path/'out/design-review.json').read_text())==review


def test_complete_assumed_model_is_useful_but_not_product_approval():
    r=result();r['case']['conditions']['material_verified']=False
    review=feedback(r,context(),'completed')
    assert review['conditional_model_pass'] is True and review['valid_for_comparison']
    assert not review['whole_product_pass_available']
    assert review['observations'] and review['next_actions']
    assert any(f['kind']=='design_observation' and not f['requires_reanalysis'] for f in review['findings'])
    assert not any(f['kind']=='design_hypothesis' for f in review['findings'])


def test_invalid_hotspot_is_preserved_as_unranked_observation():
    r=result();r.update(status='invalid',error='native contact pressure check rejected')
    r.pop('assessment')
    review=feedback(r,context(),'analysis_failed')
    assert review['conditional_model_pass'] is None and not review['valid_for_comparison']
    assert len(review['observations'])==3
    assert review['observations'][-1]['peak_stress_element_centroid_mm']==[0,1,2]
    assert all(not o['numerical_acceptance_complete'] for o in review['observations'])


def test_preload_control_is_kept_separate_from_service_peak():
    r=result();r['stage_assessments']={'preload':{'status':'indeterminate','strength_utilization':1.4,'strength_peak':{'component':'pad','element_centroid_mm':[1,2,3]}}}
    review=feedback(r,context(),'completed')
    hypothesis=next(f for f in review['findings'] if f.get('scope')=='local_load_path')
    assert hypothesis['stage_strength_findings']['preload']['strength_peak']['component']=='pad'


def test_context_is_data_and_rejects_missing_or_unknown_fields(tmp_path):
    p=tmp_path/'context.json';write_json(p,dict(context(),execute='do something'))
    with pytest.raises(ValueError):read_context(p)
    write_json(p,dict(context(),assumptions=[""]))
    with pytest.raises(ValueError):read_context(p)
    value=context();value.pop('not_assessed')
    write_json(p,value)
    with pytest.raises(ValueError):read_context(p)


def test_explicit_empty_assumptions_do_not_invent_physical_evidence(tmp_path):
    p=tmp_path/'context.json'
    write_json(p,dict(context(),assumptions=[],not_assessed=[]))
    value=read_context(p)
    review=feedback(result(),value,'completed')
    assert review['whole_product_pass_available'] is False
    assert not any('highest-impact physical assumption' in a for a in review['next_actions'])


def test_design_comparison_preserves_context_and_original_contract(tmp_path):
    from simplecae.case import sha256
    paths=[]
    for i in range(2):
        r=result();r['case']['model']['path']=f'candidate-{i}.step'
        p=tmp_path/f'result-{i}.json';write_json(p,r)
        review={'schema_version':'simplecae-design-review-1.0','depth':'design','context':context(),
                'context_contract_sha256':digest(context()),'execution':{'state':'completed'},
                'feedback':{'valid_for_comparison':True},'result':{'path':str(p),'sha256':sha256(p)}}
        q=tmp_path/f'review-{i}.json';write_json(q,review);paths.append(q)
    assert compare_design_checks(paths)['comparable']
    review['context']['assumptions']=['Different fixture hypothesis']
    review['context_contract_sha256']=digest(review['context']);write_json(paths[-1],review)
    assert not compare_design_checks(paths)['comparable']
    review['context']=context();review['context_contract_sha256']=digest(context())
    review['execution']['state']='budget_exhausted';write_json(paths[-1],review)
    assert not compare_design_checks(paths)['comparable']
    review['execution']['state']='completed';write_json(paths[-1],review)
    r['case']['loads'][0]['total_force_n'][2]=-50;write_json(p,r)
    review['result']['sha256']=sha256(p);write_json(paths[-1],review)
    assert not compare_design_checks(paths)['comparable']


def test_budget_cleanup_stops_owned_descendants(tmp_path):
    ready=tmp_path/'ready';late=tmp_path/'should-not-exist'
    child='import time,pathlib;time.sleep(2);pathlib.Path('+repr(str(late))+').write_text("orphan")'
    parent='import subprocess,sys,time,pathlib;subprocess.Popen([sys.executable,"-c",'+repr(child)+']);pathlib.Path('+repr(str(ready))+').write_text("ready");time.sleep(20)'
    process=subprocess.Popen([sys.executable,'-c',parent],
        **({'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}))
    try:
        deadline=time.monotonic()+5
        while not ready.exists() and time.monotonic()<deadline:time.sleep(.02)
        assert ready.exists()
        stop_worker(process)
        assert process.poll() is not None
        time.sleep(2.1)
        assert not late.exists(), 'A descendant survived the total-budget cleanup'
    finally:
        stop_worker(process)


def test_viewer_design_scope_and_review_hash_are_enforced(tmp_path):
    from test_workbench import evidence
    from simplecae.workbench import create_session, add_result, atomic_json, snapshot, compare_runs
    from simplecae.case import sha256
    session=create_session(tmp_path/'viewer');ids=[]
    for i in range(2):
        p=evidence(tmp_path,f'body-{i}')
        review={'schema_version':'simplecae-design-review-1.0','depth':'design','context':context(),
                'context_contract_sha256':digest(context()),'execution':{'state':'completed'},
                'feedback':{'valid_for_comparison':True},'result':{'path':str(p),'sha256':sha256(p)}}
        q=tmp_path/f'review-{i}.json';write_json(q,review)
        rid=add_result(session,p);ids.append(rid)
        rp=session/'runs'/f'{rid}.json';record=json.loads(rp.read_text())
        record['design_review']={'path':str(q),'sha256':sha256(q)};atomic_json(rp,record)
    assert compare_runs(session,*ids)['comparable']
    assert snapshot(session)['runs'][0]['design_context']['scope']==context()['scope']
    review['context']['scope']='A different physical boundary model'
    review['context_contract_sha256']=digest(review['context']);write_json(q,review)
    assert snapshot(session)['runs'][1]['state']=='unavailable'
    record['design_review']['sha256']=sha256(q);atomic_json(rp,record)
    assert not compare_runs(session,*ids)['comparable']
