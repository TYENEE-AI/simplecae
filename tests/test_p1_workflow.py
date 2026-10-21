"""Branch limits and lazy evidence must not promote partial work to acceptance."""
import copy
import http.client
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from simplecae.case import write_json, sha256
from simplecae import task_budget
from simplecae.task import start_task, task_status, brief_task_status
from simplecae.workbench import create_session, add_result, snapshot, make_server, compare_runs, save_note
from test_task import request
from test_workbench import evidence


def test_cumulative_allowance_does_not_reset_on_retry_and_extension_is_explicit(tmp_path, monkeypatch):
    state = {'task_id': 'branch', 'records': []}
    clock = [0.]
    monkeypatch.setattr(task_budget, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    with task_budget.attempt(tmp_path, state, 'one', 6, total=10) as allowed:
        assert allowed == 6
        clock[0] += 7  # Includes postprocess overhead beyond worker budget.
    with task_budget.attempt(tmp_path, state, 'two', 6) as allowed:
        assert allowed == 3
        clock[0] += 3
    with pytest.raises(ValueError, match='exhausted'):
        with task_budget.attempt(tmp_path, state, 'two', 600): pytest.fail('No reset')
    with pytest.raises(ValueError, match='budget_reason'):
        with task_budget.attempt(tmp_path, state, 'two', 6, total=20): pytest.fail('No implicit extension')
    with task_budget.attempt(tmp_path, state, 'two', 6, total=20, reason='Measured execution repair'):
        clock[0] += 1
    report = task_budget.read_budget(tmp_path, state)
    assert report['spent_seconds'] == 11 and report['remaining_seconds'] == 9
    assert len(report['changes']) == 1


def test_unsettled_attempt_reserves_budget_and_interrupt_is_recorded(tmp_path, monkeypatch):
    state = {'task_id': 'branch', 'records': []}
    with pytest.raises(RuntimeError):
        with task_budget.attempt(tmp_path, state, 'check', 10):
            pending = task_budget.read_budget(tmp_path, state)
            assert pending['remaining_seconds'] == 0 and pending['attempts'][0]['state'] == 'started'
            with pytest.raises(ValueError, match='busy/interrupted'):
                with task_budget.attempt(tmp_path, state, 'check', 10): pass
            raise RuntimeError('worker failed')
    assert task_budget.read_budget(tmp_path, state)['attempts'][0]['state'] == 'interrupted'


def test_cad_revision_shares_allowance_but_not_completion(tmp_path):
    path = request(tmp_path, fem=True)
    first = tmp_path/'r1'; second = tmp_path/'r2'
    start_task(path, first)
    state = json.loads((first/'task-state.json').read_text(encoding='utf-8'))
    with task_budget.attempt(first, state, 'task-deflection', 10): pass
    (tmp_path/'cad.py').write_text('revision 2')
    status = start_task(path, second, continue_from=first)
    assert status['execution_budget']['path'] == str(first/'execution-budget.json')
    assert len(status['execution_budget']['attempts']) == 1
    assert all(row['outcome'] == 'pending' for row in status['checks'])
    assert not status['whole_product_pass_available']


def test_metadata_does_not_construct_fields_and_selected_requests_ignore_other_runs(tmp_path, monkeypatch):
    import simplecae.workbench as wb
    session = create_session(tmp_path/'viewer')
    a = add_result(session, evidence(tmp_path, 'a'))
    b = add_result(session, evidence(tmp_path, 'b'))
    c = add_result(session, evidence(tmp_path, 'c'))
    original = wb.dataset
    called = []
    def dataset(path, label, body):
        called.append(Path(path).parent.name)
        return original(path, label, body)
    monkeypatch.setattr(wb, 'dataset', dataset)
    data = snapshot(session, include_fields=False)
    assert len(data['runs']) == 3 and not called
    assert all(r['fields_loaded'] is False and r['datasets'] == [] for r in data['runs'])
    assert all(r['status'] == 'fields_not_loaded' and not r['signal']['valid_for_comparison']
               and r['signal']['feasible_under_stated_model'] is None for r in data['runs'])
    full = snapshot(session, run_ids={a})['runs'][0]
    assert called == ['a'] and full['datasets'][0]['stress'] == [10]*4
    called.clear()
    assert compare_runs(session, a, b)['comparable']
    assert sorted(called) == ['a', 'b']
    called.clear()
    save_note(session, {'run_id': a, 'result_sha256': full['result_sha256'], 'text': 'Review'})
    assert called == ['a']


def test_lazy_http_preserves_hidden_bad_field_and_origin_guards(tmp_path):
    session = create_session(tmp_path/'viewer')
    source = evidence(tmp_path)
    fp = source.parent/'level-03/fields.npz'
    with np.load(fp) as loaded: arrays = dict(loaded)
    arrays['displacements'][9, 0] = np.nan  # Interior node omitted from display.
    np.savez(fp, **arrays)
    rid = add_result(session, source)
    server = make_server(session)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    def get(path, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        connection.request('GET', path, headers=headers or {})
        response = connection.getresponse(); body = response.read(); status = response.status; connection.close()
        return status, json.loads(body)
    try:
        code, meta = get('/state')
        assert code == 200 and meta['runs'][0]['fields_loaded'] is False
        code, full = get('/run?id='+rid)
        assert code == 200 and full['state'] == 'unavailable' and 'signal' not in full
        assert get('/run?id=../../other')[0] == 400
        assert get('/run?id='+rid, {'Origin':'https://foreign.invalid'})[0] == 403
        assert get('/run?id='+rid+'&id=second')[0] == 400
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_requested_load_level_key_does_not_inherit_capacity_or_fixed_response(tmp_path):
    from simplecae.level_cache import level_key
    from simplecae.benchmarks import bar_case
    step=tmp_path/'part.step'; step.write_text('A'); exe=tmp_path/'ccx'; exe.write_text('B')
    case=bar_case('part',[1000.,0,0],[5.,4.,3.]); case['model']['path']=str(step)
    keys={level_key(case,3.,exe,predict_capacity=p,require_fixed_response=f) for p,f in [(True,False),(False,False),(False,True)]}
    assert len(keys)==3


def test_legacy_revision_migration_accounts_owner_and_rejects_changed_evidence(tmp_path, monkeypatch):
    owner=tmp_path/'old'; owner.mkdir(); (owner/'records').mkdir()
    review=owner/'review.json'; write_json(review, {'execution': {'elapsed_seconds': 7}})
    record=owner/'records/check.json'
    payload={'kind':'computed', 'revision_sha256':'old', 'check_id':'one',
             'review':{'path':str(review), 'sha256':sha256(review)}}
    write_json(record,payload)
    prior={'task_id':'branch','revision_sha256':'old',
           'records':[{'path':str(record),'sha256':sha256(record),'check_id':'one'}]}
    write_json(owner/'task-state.json',prior)
    revision=tmp_path/'new'; revision.mkdir()
    state={'task_id':'branch','records':[], 'execution_budget':str(owner/'execution-budget.json')}
    monkeypatch.setattr(task_budget, 'time', SimpleNamespace(monotonic=lambda: 0.))
    with task_budget.attempt(revision,state,'one',10) as allowed:
        assert allowed==3
    assert task_budget.read_budget(revision,state)['spent_seconds']==7
    stored=json.loads((owner/'execution-budget.json').read_text(encoding='utf-8'))
    assert 'remaining_seconds' not in stored
    (owner/'execution-budget.json').unlink()  # Simulate damaged/missing migration evidence.
    write_json(review, {'execution': {'elapsed_seconds': 0}})
    with pytest.raises(ValueError,match='review changed'):
        with task_budget.attempt(revision,state,'one',10): pytest.fail('Tampered migration')
    prior['execution_budget']=state['execution_budget']; write_json(owner/'task-state.json',prior)
    with pytest.raises(ValueError,match='budget missing'):
        with task_budget.attempt(revision,state,'one',10): pytest.fail('Missing ledger must not reset')


def test_saved_legacy_status_keeps_unknown_allowance(tmp_path):
    path=request(tmp_path,fem=True)
    report=start_task(path,tmp_path/'task')
    del report['execution_budget']; del report['execution_next_action']
    brief=brief_task_status(report)
    assert brief['execution_budget']['remaining_seconds'] is None
    assert brief['execution_next_action']=='refresh_task_status'
    assert not brief['whole_product_pass_available']
