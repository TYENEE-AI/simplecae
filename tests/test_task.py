"""Behavioral invariants of revision-bound, mixed-method Agent tasks."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from simplecae.case import write_json
from simplecae.task import start_task, run_task_check, record_task_check, task_status
from simplecae.workbench import snapshot
from simplecae.use_plan import read_plan, bind_plan, usage_feedback
from simplecae.design_check import feedback
from test_design_check import context
from test_signals import result

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('sources',[[],None])
def test_planning_before_CAD_exists_uses_manifest_as_source(tmp_path,sources):
    p=read_plan(ROOT/'examples/use-plans/manual-mechanism.json')
    p['schema_version']='simplecae-task-1.0'
    if sources is not None:p['sources']=sources
    path=tmp_path/'planning.json';write_json(path,p)
    status=start_task(path,tmp_path/'session')
    assert not status['whole_product_pass_available']
    state=json.loads((tmp_path/'session/task-state.json').read_text(encoding='utf-8'))
    assert str(path.resolve()) in state['bindings']


def request(tmp_path, *, fem=False):
    source = tmp_path / 'cad.py'
    source.write_text('revision 1', encoding='utf8')
    p = read_plan(ROOT / 'examples/use-plans/manual-mechanism.json')
    if fem:
        p = read_plan(ROOT / 'examples/use-plans/bench-fixture.json')
        case = json.loads((ROOT / 'examples/preview/fail.case.json').read_text(encoding='utf8'))
        case['model']['path'] = str(ROOT / 'examples/preview/beam.step')
        case.pop('provenance')  # Task id is supplied once by the shared task file.
        p['cases'] = {'task-deflection': case}
    p['schema_version'] = 'simplecae-task-1.0'
    p['sources'] = ['cad.py']
    path = tmp_path / '任务.json'
    write_json(path, p)
    return path


def evidence(tmp_path, status, cid=None, *, outcome='pass'):
    row = next(c for c in status['checks'] if c['id'] == cid) if cid else status['checks'][0]
    artifact = tmp_path / ('measurement-' + outcome + '.json')
    write_json(artifact, {'measured_gap_mm': .4, 'coverage': 'declared position only'})
    e = {'schema_version': 'simplecae-check-evidence-1.0', 'task_id': status['task_id'],
         'check_id': row['id'], 'method': row['method'], 'revision_sha256': status['revision_sha256'],
         'outcome': outcome, 'summary': 'Bound check outcome from external tool',
         'observations': ['0.4 mm measured clearance'], 'limitations': ['No physical test'],
         'artifacts': [str(artifact)]}
    path = tmp_path / ('evidence-' + outcome + '.json')
    write_json(path, e)
    return path


def test_geometry_task_does_not_start_a_solver_and_viewer_has_completion_records(tmp_path, monkeypatch):
    # Windows Python may query its OS version with `ver` on first access.
    # Resolve that stdlib metadata before guarding analysis process launches.
    import platform
    platform.system()
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('No solver during preparation/recording'))
    s = start_task(request(tmp_path), tmp_path / 'task')
    assert not (tmp_path / 'task/runs').exists()
    assert all(c['outcome'] == 'pending' for c in s['checks'])
    p = evidence(tmp_path, s)
    s = record_task_check(tmp_path / 'task', s['checks'][0]['id'], p)
    assert s['checks'][0]['outcome'] == 'pass'
    assert s['checks'][0]['latest']['kind'] == 'externally_recorded'
    assert not s['whole_product_pass_available'] and s['remaining_required_checks']
    assert snapshot(tmp_path / 'task/viewer')['tasks'][0]['checks'][0]['outcome'] == 'pass'


def test_one_file_derives_context_and_preserves_physics(tmp_path):
    s = start_task(request(tmp_path, fem=True), tmp_path / 'task')
    original = json.loads((ROOT / 'examples/preview/fail.case.json').read_text(encoding='utf8'))
    generated = json.loads((tmp_path / 'task/inputs/check-001.case.json').read_text(encoding='utf8'))
    for key in ('material', 'supports', 'loads', 'mesh', 'criteria', 'conditions'):
        assert generated[key] == original[key]
    assert generated['provenance']['task_id'] == s['task_id']
    xp = json.loads((tmp_path / 'task/inputs/check-001.context.json').read_text(encoding='utf8'))
    assert xp['question'] == s['checks'][0]['question']
    assert s['checks'][0]['case_ready']


@pytest.mark.parametrize('mutate', ['task', 'check', 'method', 'revision', 'missing_artifact', 'empty_observations'])
def test_foreign_or_incomplete_evidence_cannot_complete_a_check(tmp_path, mutate):
    s = start_task(request(tmp_path), tmp_path / 'task')
    path = evidence(tmp_path, s)
    e = json.loads(path.read_text(encoding='utf8'))
    key = {'task': 'task_id', 'check': 'check_id', 'method': 'method', 'revision': 'revision_sha256'}.get(mutate)
    if key: e[key] = 'different'
    elif mutate == 'missing_artifact': e['artifacts'] = ['missing.json']
    else: e['observations'] = []
    write_json(path, e)
    with pytest.raises(ValueError): record_task_check(tmp_path / 'task', s['checks'][0]['id'], path)
    assert all(c['outcome'] == 'pending' for c in task_status(tmp_path / 'task')['checks'])


def test_model_revision_invalidates_old_checks_and_blocks_fem(tmp_path, monkeypatch):
    s = start_task(request(tmp_path), tmp_path / 'task')
    record_task_check(tmp_path / 'task', s['checks'][0]['id'], evidence(tmp_path, s))
    (tmp_path / 'cad.py').write_text('revision 2', encoding='utf8')
    s = task_status(tmp_path / 'task')
    assert s['changed_inputs'] and s['checks'][0]['outcome'] == 'insufficient_evidence'
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Stale task must not launch worker'))
    with pytest.raises(ValueError, match='fresh revision'):
        run_task_check(tmp_path / 'task', 'anything')


@pytest.mark.parametrize('delete', [False, True])
def test_latest_record_corruption_cannot_reveal_old_pass(tmp_path, delete):
    s = start_task(request(tmp_path), tmp_path / 'task')
    cid = s['checks'][0]['id']
    record_task_check(tmp_path / 'task', cid, evidence(tmp_path, s))
    s = record_task_check(tmp_path / 'task', cid, evidence(tmp_path, s, outcome='fail'))
    latest = Path(s['checks'][0]['latest']['record'])
    if delete: latest.unlink()
    else: latest.write_text('{"check_id":"different"}', encoding='utf8')
    s = task_status(tmp_path / 'task')
    assert s['checks'][0]['outcome'] == 'insufficient_evidence'
    assert len(s['checks'][0]['history']) == 2


def test_modified_external_artifact_withholds_previously_recorded_pass(tmp_path):
    s = start_task(request(tmp_path), tmp_path / 'task')
    s = record_task_check(tmp_path / 'task', s['checks'][0]['id'], evidence(tmp_path, s))
    write_json(tmp_path / 'measurement-pass.json', {'changed': True})
    s = task_status(tmp_path / 'task')
    assert s['checks'][0]['outcome'] == 'insufficient_evidence'


def test_fem_cannot_be_overridden_and_non_fem_cannot_launch_worker(tmp_path, monkeypatch):
    s = start_task(request(tmp_path, fem=True), tmp_path / 'task')
    with pytest.raises(ValueError, match='FEM needs computed'):
        record_task_check(tmp_path / 'task', 'task-deflection', evidence(tmp_path, s))
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('No worker'))
    with pytest.raises(ValueError, match='immediate FEM'):
        run_task_check(tmp_path / 'task', 'real-mount')


def test_deferred_physical_result_can_be_recorded_but_is_external_not_certified(tmp_path):
    s = start_task(request(tmp_path, fem=True), tmp_path / 'task')
    s = record_task_check(tmp_path / 'task', 'real-mount', evidence(tmp_path, s, 'real-mount'))
    assert s['checks'][1]['outcome'] == 'pass'
    assert s['checks'][1]['latest']['kind'] == 'externally_recorded'
    assert not s['whole_product_pass_available']


def test_all_external_checks_complete_does_not_grant_product_approval(tmp_path):
    p = request(tmp_path)
    m = json.loads(p.read_text(encoding='utf8'))
    m['checks'] = [m['checks'][0]]
    write_json(p, m)
    s = start_task(p, tmp_path / 'task')
    s = record_task_check(tmp_path / 'task', s['checks'][0]['id'], evidence(tmp_path, s))
    assert s['status'] == 'declared_checks_complete' and not s['remaining_required_checks']
    assert not s['whole_product_pass_available']


def test_busy_task_rejects_second_mutation(tmp_path):
    s = start_task(request(tmp_path), tmp_path / 'task')
    (tmp_path / 'task/task.lock').write_text('owner', encoding='utf8')
    with pytest.raises(ValueError, match='busy'):
        record_task_check(tmp_path / 'task', s['checks'][0]['id'], evidence(tmp_path, s))
    assert (tmp_path / 'task/task.lock').read_text() == 'owner'


def test_cli_single_file_unicode_task_and_status(tmp_path):
    p = request(tmp_path)
    cli = ROOT / 'scripts/simplecae_cli.py'
    for cmd in ([str(p), '--out', str(tmp_path / 'task')], [str(tmp_path / 'task')]):
        op = 'start' if '--out' in cmd else 'status'
        r = subprocess.run([sys.executable, str(cli), 'task', op, *cmd], capture_output=True, encoding='utf8')
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)['status'] == 'insufficient_evidence'


def test_reanalysis_is_not_requested_for_pass_or_incomplete_solve(tmp_path):
    plan = ROOT / 'examples/use-plans/bench-fixture.json'
    binding = bind_plan(plan, 'task-deflection', tmp_path / 'case.json')
    passed = usage_feedback(binding, feedback(result(), context(), 'completed'))
    assert passed['cad_iteration']['requires_reanalysis'] is False
    assert passed['cad_iteration']['reanalysis_trigger'] == 'none_for_this_check'
    r = result(); r.update(status='invalid'); r.pop('assessment')
    missing = usage_feedback(binding, feedback(r, context(), 'analysis_failed'))
    assert missing['cad_iteration']['requires_reanalysis'] is False
    assert missing['cad_iteration']['reanalysis_trigger'] == 'after_input_or_analysis_repair_if_needed'


def test_missing_criterion_guidance_preserves_old_review_and_uses_raw_evidence(tmp_path):
    from simplecae.case import sha256
    from simplecae.signals import digest
    from simplecae.task import _analysis_note
    from simplecae.use_plan import review_usage_feedback
    bound = bind_plan(ROOT / 'examples/use-plans/bench-fixture.json', 'task-deflection', tmp_path / 'case.json')
    bound['check']['result_criteria'] = ['unknown:requirement']
    bound['contract']['checks'][0]['result_criteria'] = ['unknown:requirement']
    bound['contract_sha256'] = digest(bound['contract'])
    raw = result()
    raw['case']['provenance']['task_id'] = bound['contract']['task_id']
    path = tmp_path / 'result.json'
    write_json(path, raw)
    f = feedback(raw, context(), 'completed')
    usage = usage_feedback(bound, f)
    review = {'usage_plan': bound, 'usage_feedback': usage, 'feedback': f, 'context': context(),
              'execution': {'state': 'completed'}, 'result': {'path': str(path), 'sha256': sha256(path)}}
    # Old persisted review contains no new diagnostics, and must remain valid.
    original = copy.deepcopy(review)
    assert review_usage_feedback(review)['status'] == 'insufficient_evidence'
    # Displayed cached feedback is not authoritative for discoverable keys.
    review['feedback'] = {'criterion_assessments': {'invented-key': {}}}
    validated = review_usage_feedback(review)
    note = _analysis_note(review, validated)
    assert {'strength', 'stiffness'} <= set(note['available_result_criteria'])
    assert 'invented-key' not in note['available_result_criteria']
    assert note['missing_result_criteria'] == ['unknown:requirement']
    assert validated == original['usage_feedback']
    assert review['usage_feedback'] == original['usage_feedback']
    assert not validated['whole_product_pass_available']
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='evidence changed'):
        review_usage_feedback(review)


def test_computed_result_completes_only_selected_fem_and_preserves_raw_receipt(tmp_path, monkeypatch):
    import importlib
    from simplecae.assessment import assess
    from simplecae.case import sha256
    module=importlib.import_module('simplecae.design_check')
    labels=[]
    def computed(case_path,out,**options):
        labels.append(options['label'])
        out.mkdir(parents=True);(out/'analysis').mkdir()
        r=result();r['case']=json.loads(Path(case_path).read_text(encoding='utf8'))
        r['assessment']=assess(r['case'],r['levels']);r['status']=r['assessment']['status']
        rp=out/'analysis/result.json';write_json(rp,r)
        ctx=json.loads(Path(options['context_path']).read_text(encoding='utf8'))
        bound=bind_plan(options['plan_path'],options['check_id'],case_path)
        f=feedback(r,ctx,'completed')
        write_json(out/'design-review.json',{'execution':{'state':'completed'},'context':ctx,
            'feedback':f,'usage_plan':bound,'usage_feedback':usage_feedback(bound,f),
            'result':{'path':str(rp),'sha256':sha256(rp)}})
    monkeypatch.setattr(module,'design_check',computed)
    s=start_task(request(tmp_path,fem=True),tmp_path/'task')
    s=run_task_check(tmp_path/'task','task-deflection')
    assert labels==['task · task-deflection']
    assert s['checks'][0]['outcome']=='pass' and s['checks'][0]['latest']['kind']=='computed'
    assert s['checks'][0]['latest']['review']
    assert s['checks'][1]['outcome']=='pending' and s['remaining_required_checks']==['real-mount']
    assert not (tmp_path/'task/task.lock').exists()
    original_count=len(s['checks'][0]['history'])
    with pytest.raises(ValueError,match='already has a result'):
        run_task_check(tmp_path/'task','task-deflection')
    assert len(task_status(tmp_path/'task')['checks'][0]['history'])==original_count
    s=run_task_check(tmp_path/'task','task-deflection',retry_reason='Independent executor repair validation',label='Explicit revision label')
    assert labels[-1]=='Explicit revision label'
    assert len(s['checks'][0]['history'])==original_count+1
    assert s['checks'][0]['latest']['retry_reason']=='Independent executor repair validation'
    rp=Path(s['checks'][0]['latest']['review'])
    raw=json.loads(rp.read_text(encoding='utf8'))
    Path(raw['result']['path']).write_text('{}',encoding='utf8')
    assert task_status(tmp_path/'task')['checks'][0]['outcome']=='insufficient_evidence'
