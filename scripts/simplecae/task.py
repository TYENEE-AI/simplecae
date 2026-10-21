"""Small revision-bound task workspace; external evidence is recorded, not certified.

One input bundles a use plan and cases. Explicit FEM and rigid robot calculation
checks can start a worker. Other tools own external checks and physical tests.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import html
import json
from pathlib import Path
import secrets
import tempfile

from .case import sha256, write_json
from .signals import digest
from .use_plan import SCHEMA, validate_plan, prepare_plan, review_usage_feedback, computed_check, validate_computation
from .workbench import atomic_json, create_session, export_session, now

TASK_SCHEMA = 'simplecae-task-1.0'
EVIDENCE_SCHEMA = 'simplecae-check-evidence-1.0'


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be nonempty text')


def _paths(values, base):
    if not isinstance(values, list) or not values:
        raise ValueError('sources/artifacts must contain existing files')
    paths = []
    for value in values:
        _text(value, 'file path')
        p = Path(value)
        p = (base / p).resolve() if not p.is_absolute() else p.resolve()
        if not p.is_file():
            raise ValueError(f'Evidence/source file does not exist: {p}')
        paths.append(p)
    return paths


def _preflight(path, check_id):
    from .api import check_case
    try:
        return check_case(path)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f'Check {check_id}: invalid numerical input before solve: {exc}') from exc


def _case_paths(value, base, sources, inspected=None):
    """Resolve documented file references without changing physical inputs."""
    inspected = set() if inspected is None else inspected
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'package_roots' and isinstance(item, dict):
                for name, folder in item.items():
                    _text(folder, 'package root')
                    root = (base / folder).resolve()
                    if not root.is_dir():
                        raise ValueError(f'URDF package root does not exist: {root}')
                    item[name] = str(root)
            elif key in ('path', 'case_path', 'interface_manifest') and isinstance(item, str):
                path = Path(item)
                path = (base / path).resolve() if not path.is_absolute() else path.resolve()
                if not path.is_file():
                    raise ValueError(f'Case input does not exist: {path}')
                value[key] = str(path)
                sources.add(path)
                # Nested component case paths retain their own base directory.
                if key == 'case_path' and path not in inspected:
                    inspected.add(path)
                    nested = _read(path)
                    _case_paths(nested, path.parent, sources, inspected)
            else:
                _case_paths(item, base, sources, inspected)
    elif isinstance(value, list):
        for item in value:
            _case_paths(item, base, sources, inspected)


@contextmanager
def _lock(session):
    lock = Path(session) / 'task.lock'
    try:
        with lock.open('x', encoding='utf-8') as stream:
            stream.write('One task mutation at a time; remove only after confirming its worker has stopped.')
    except FileExistsError:
        raise ValueError('Task is busy or has an interrupted operation; inspect task.lock and running workers') from None
    try:
        yield
    finally:
        lock.unlink()


def _load(session, current=True):
    session = Path(session).resolve()
    state = _read(session / 'task-state.json')
    if state.get('schema_version') != TASK_SCHEMA:
        raise ValueError('Not a SimpleCAE task workspace')
    if digest(state['bindings']) != state['revision_sha256']:
        raise ValueError('Task revision binding is contradictory')
    if _read(session / 'inputs' / 'plan.json') != state['plan']:
        raise ValueError('Task plan and snapshot differ; start a fresh revision workspace')
    changed = [name for name, expected in state['bindings'].items()
               if not Path(name).is_file() or sha256(Path(name)) != expected]
    # Older workspaces may not have closed URDF asset references. Do not silently
    # trust them on upgrade: retain their files/history but require a fresh revision
    # when an actual dependency was never bound. No recursive directory scan.
    for entry in state['cases'].values():
        try:
            if _read(entry['case']).get('schema_version') in ('robot-1.0', 'motion-loads-1.0'):
                from .api import check_case
                from .sources import source_paths
                missing=source_paths(check_case(Path(entry['case']))) - {Path(p) for p in state['bindings']}
                changed.extend('Unbound numerical dependency: ' + str(p) for p in sorted(missing))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            changed.append('Numerical dependency unavailable: ' + str(exc))
    if changed and current:
        raise ValueError('Task inputs changed; start a fresh revision workspace: ' + ', '.join(changed))
    return session, state, changed


def start_task(path, out, *, viewer_session=None):
    """Prepare plan, cases, contexts and Viewer from one data-only file; no solve."""
    path, out = Path(path).resolve(), Path(out).resolve()
    manifest = _read(path)
    extras = {'sources', 'cases', 'change_hypothesis'}
    if not isinstance(manifest, dict) or manifest.get('schema_version') != TASK_SCHEMA:
        raise ValueError('Expected simplecae-task-1.0')
    plan = {k: copy.deepcopy(v) for k, v in manifest.items() if k not in extras}
    plan['schema_version'] = SCHEMA
    validate_plan(plan)
    sources = set(_paths(manifest.get('sources'), path.parent)) | {path}
    cases = manifest.get('cases', {})
    if not isinstance(cases, dict):
        raise ValueError('cases must map check ids to inline cases or case file paths')
    fem = {c['id']: c for c in plan['checks'] if computed_check(c)}
    if set(cases) - set(fem):
        raise ValueError('Cases can bind only immediate computed FEM/calculation checks')
    hypothesis = manifest.get('change_hypothesis', '')
    if not isinstance(hypothesis, str):
        raise ValueError('change_hypothesis must be text')
    generated = {}
    for index, (cid, check) in enumerate(fem.items()):
        entry = cases.get(cid, check.get('case_path'))
        if entry is None:
            continue  # Planning can precede numerical model preparation.
        base = path.parent
        if isinstance(entry, str):
            case_path = _paths([entry], base)[0]
            sources.add(case_path)
            case, base = _read(case_path), case_path.parent
        elif isinstance(entry, dict):
            case = copy.deepcopy(entry)
        else:
            raise ValueError('A case must be a JSON object or file path')
        if not isinstance(case, dict):
            raise ValueError('A case file must contain a JSON object')
        if check.get('case_path') and cid in cases:
            raise ValueError('Use cases or check.case_path, not both for the same check')
        provenance = case.setdefault('provenance', {})
        if provenance.get('task_id', plan['task_id']) != plan['task_id']:
            raise ValueError('Case task_id differs from the task')
        provenance['task_id'] = plan['task_id']
        _case_paths(case, base, sources)
        # Reuse the existing static contract/semantic validators before creating
        # a workspace or worker. The normalized return locates source dependencies
        # only; generated physical inputs never receive temporary draft paths.
        with tempfile.TemporaryDirectory(prefix='simplecae-preflight-') as temporary:
            draft = Path(temporary) / 'case.json'
            write_json(draft, case)
            validated = _preflight(draft, cid)
            validate_computation(check, validated)
            from .sources import source_paths
            sources.update(source_paths(validated))
        stem = f'check-{index + 1:03d}'  # Never put caller-supplied ids in paths.
        check['case_path'] = str(out / 'inputs' / f'{stem}.case.json')
        context = {'question': check['question'], 'scope': '; '.join(check['targets']),
                   'assumptions': check['assumptions'] or ['No additional modeling assumptions declared.'],
                   'not_assessed': check['not_assessed'] or ['Physical applicability remains separately unverified.']}
        if hypothesis:
            context['change_hypothesis'] = hypothesis
        generated[cid] = (stem, case, context)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'inputs').mkdir()
    (out / 'records').mkdir()
    write_json(out / 'task-snapshot.json', manifest)
    write_json(out / 'inputs' / 'plan.json', plan)
    entries = {}
    for cid, (stem, case, context) in generated.items():
        cp, xp = out / 'inputs' / f'{stem}.case.json', out / 'inputs' / f'{stem}.context.json'
        write_json(cp, case)
        write_json(xp, context)
        entries[cid] = {'case': str(cp), 'context': str(xp)}
    prepare_plan(out / 'inputs' / 'plan.json', out / 'plan')
    local_viewer = Path(viewer_session).resolve() if viewer_session else out / 'viewer'
    if not viewer_session:
        create_session(local_viewer, plan['request'])
    else:
        from .workbench import session_config
        session_config(local_viewer)
    bindings = {str(p): sha256(p) for p in sorted(sources | set((out / 'inputs').glob('*.json')) | {out / 'task-snapshot.json'})}
    state = {'schema_version': TASK_SCHEMA, 'task_id': plan['task_id'], 'plan': plan,
             'revision_sha256': digest(bindings), 'bindings': bindings, 'cases': entries,
             'viewer_session': str(local_viewer), 'records': [], 'created_at_utc': now()}
    atomic_json(out / 'task-state.json', state)
    return task_status(out)


def _check(state, cid):
    selected = next((c for c in state['plan']['checks'] if c['id'] == cid), None)
    if selected is None:
        raise ValueError('Unknown check id')
    return selected


def _save_record(session, state, record):
    path = session / 'records' / (secrets.token_hex(12) + '.json')
    atomic_json(path, record)
    state['records'].append({'path': str(path), 'sha256': sha256(path), 'check_id': record['check_id']})
    atomic_json(session / 'task-state.json', state)


def run_task_check(session, check_id, *, budget_seconds=600, timeout='auto', ccx=None,
                   depth='design', label=None, storage='compact', retry_reason=None):
    """Run one explicit computed check; reuse all existing numerical validity gates."""
    session = Path(session).resolve()
    with _lock(session):
        _, state, _ = _load(session)
        check = _check(state, check_id)
        if not computed_check(check):
            raise ValueError('Only an immediate FEM or computed calculation check can start a worker')
        if check_id not in state['cases']:
            raise ValueError('No case supplied; prepare the model and start a fresh task workspace')
        if retry_reason is not None:
            _text(retry_reason,'retry_reason')
        # An unchanged task is immutable. Repeated worker launches require a
        # concrete reason, except the explicitly requested design->detailed step.
        previous=next((b for b in reversed(state['records']) if b['check_id']==check_id),None)
        if previous:
            record_path=Path(previous['path'])
            if sha256(record_path)!=previous['sha256']:
                raise ValueError('Prior check record changed; inspect task status before retrying')
            prior=_read(record_path)
            review_path=Path(prior['review']['path'])
            if sha256(review_path)!=prior['review']['sha256']:
                raise ValueError('Prior computed review changed; inspect task status before retrying')
            previous_execution=_read(review_path).get('execution',{})
            selecting_depth=previous_execution.get('state')=='needs_explicit_model' and depth=='detailed'
            if not selecting_depth and retry_reason is None:
                raise ValueError('This unchanged check already has a result. Inspect task status; changed inputs need a fresh workspace. '
                                 'For an identified execution/environment repair, provide retry_reason / --retry-reason. No automatic identical rerun.')
        from .design_check import design_check
        entry = state['cases'][check_id]
        _preflight(Path(entry['case']), check_id)
        run = session / 'runs' / secrets.token_hex(8)
        design_check(entry['case'], run, context_path=entry['context'],
            plan_path=session / 'inputs' / 'plan.json', check_id=check_id, depth=depth,
            budget_seconds=budget_seconds, timeout=timeout, ccx=ccx, storage=storage,
            # The question is unchanged across CAD revisions. The workspace
            # identifies the revision so the Viewer does not show duplicate,
            # indistinguishable labels; full question remains in the review.
            viewer_session=state['viewer_session'], label=label or f'{session.name} · {check_id}',
            change_note=_read(session / 'task-snapshot.json').get('change_hypothesis', ''))
        review_path = run / 'design-review.json'
        record = {'check_id': check_id, 'method': check['method'], 'kind': 'computed',
                  'revision_sha256': state['revision_sha256'], 'recorded_at_utc': now(),
                  'review': {'path': str(review_path), 'sha256': sha256(review_path)}}
        if retry_reason is not None:record['retry_reason']=retry_reason
        _save_record(session, state, record)
        # Bind the displayed run to the task even if a completion receipt is later lost.
        for file in (Path(state['viewer_session']) / 'runs').glob('*.json'):
            displayed = _read(file)
            if displayed.get('design_review', {}).get('path') == str(review_path):
                displayed['task_workspace'] = str(session)
                atomic_json(file, displayed)
    return task_status(session)


def record_task_check(session, check_id, evidence_path=None, *, artifacts=None,
                      outcome=None, observations=None, limitations=None, summary=None,
                      revision_sha256=None):
    """Record external results with their artifacts; never override a FEM verdict."""
    session = Path(session).resolve()
    evidence_path = Path(evidence_path).resolve() if evidence_path is not None else None
    with _lock(session):
        _, state, _ = _load(session)
        check = _check(state, check_id)
        if check['method'] == 'fem' or computed_check(check) or check['decision'] == 'unsupported':
            raise ValueError('FEM needs computed evidence; unsupported checks require a new justified plan')
        if evidence_path is not None:
            if any(v is not None for v in (artifacts, outcome, observations, limitations, summary, revision_sha256)):
                raise ValueError('Use an evidence file or explicit artifact/outcome fields, not both')
            e, base, originals = _read(evidence_path), evidence_path.parent, {evidence_path}
        else:
            if revision_sha256 != state['revision_sha256']:
                raise ValueError('Direct recording requires the unchanged revision_sha256 from task start/status')
            if not isinstance(artifacts, list) or not artifacts:
                raise ValueError('Direct recording requires existing artifacts and explicit observations/outcome')
            e = {'schema_version': EVIDENCE_SCHEMA, 'task_id': state['task_id'],
                 'check_id': check_id, 'method': check['method'], 'revision_sha256': state['revision_sha256'],
                 'outcome': outcome, 'summary': summary or (observations[0] if isinstance(observations, list) and observations else None),
                 'observations': observations, 'limitations': [] if limitations is None else limitations,
                 'artifacts': [str(p) for p in artifacts]}
            base, originals = Path.cwd(), set()
        fields = {'schema_version', 'task_id', 'check_id', 'method', 'revision_sha256',
                  'outcome', 'summary', 'observations', 'limitations', 'artifacts'}
        if not isinstance(e, dict) or set(e) != fields or e['schema_version'] != EVIDENCE_SCHEMA:
            raise ValueError('Expected complete simplecae-check-evidence-1.0; unknown fields rejected')
        if (e['task_id'], e['check_id'], e['method'], e['revision_sha256']) != (
                state['task_id'], check_id, check['method'], state['revision_sha256']):
            raise ValueError('External evidence belongs to a different task/check/method/revision')
        if e['outcome'] not in ('pass', 'fail', 'insufficient_evidence'):
            raise ValueError('outcome must be pass, fail or insufficient_evidence')
        _text(e['summary'], 'summary')
        for key in ('observations', 'limitations'):
            if not isinstance(e[key], list) or (key == 'observations' and not e[key]):
                raise ValueError('observations must be nonempty; limitations must be a list')
            for item in e[key]:
                _text(item, key)
        artifacts = _paths(e['artifacts'], base)
        # Snapshot tiny metadata; retain artifacts in place instead of duplicating them.
        record = {'check_id': check_id, 'method': check['method'], 'kind': 'externally_recorded',
                  'revision_sha256': state['revision_sha256'], 'recorded_at_utc': now(),
                  'evidence': e, 'bindings': {str(p): sha256(p) for p in set(artifacts) | originals}}
        _save_record(session, state, record)
    return task_status(session)


def _analysis_note(review, usage):
    """Expose a bounded action and existing contribution evidence, not a new solver."""
    execution = review['execution']
    note = {'execution_state': execution['state'], 'worker_started': execution.get('worker_started', False),
            'governing': usage.get('governing'), 'reanalysis_trigger': usage['cad_iteration']['reanalysis_trigger'],
            'confirmed_failed_criteria': usage.get('confirmed_failed_criteria', {}),
            'missing_result_criteria': usage.get('missing_result_criteria', []),
            'unresolved_result_criteria': usage.get('unresolved_result_criteria', [])}
    if review.get('result'):
        raw = _read(review['result']['path'])
        note['result_path'] = review['result']['path']
        if raw.get('error'):note['error'] = raw['error']
        diagnostics=[]
        for pose in raw.get('poses', []):
            for component in pose.get('components', []):
                if component.get('status') == 'pass_under_stated_model':continue
                item={'pose':pose['name'],'link':component.get('robot_load_transfer',{}).get('link'),
                      'status':component.get('status')}
                if component.get('error'):item['error']=component['error']
                verification=component.get('assessment',{}).get('verification',{})
                item['verification']={k:verification[k] for k in ('mesh_converged','force_and_moment_balance_passed','small_response_screen_passed') if k in verification}
                if component.get('levels'):
                    last=component['levels'][-1];field=last.get('results',{})
                    item['last_field']={k:field[k] for k in ('strength_peak','max_von_mises_mpa','max_displacement_mm','peak_element_centroid_mm') if k in field}
                    item['field_coordinate_system']='component CAD coordinates, mm'
                    item['directory']=last.get('directory')
                diagnostics.append(item)
        if diagnostics:
            note['component_diagnostics']=diagnostics[:6]
            note['component_diagnostics_count']=len(diagnostics)
            note['component_diagnostics_truncated']=len(diagnostics)>6
    else:
        raw = None
    if execution['state'] == 'needs_explicit_model':
        note.update(focus='analysis_depth', message='声明的接触、预紧或屈曲需要明确选择详细分析；没有删去这些物理。',
                    detailed_features=review.get('detailed_features', []))
        return note
    if raw is not None:
        from .signals import structural_validity_guidance
        if guidance:=structural_validity_guidance(raw):
            note.update(guidance)
            return note
    if usage['status'] != 'fail_under_stated_model' or raw is None:
        return note
    # Small located evidence already computed from the uncropped final field.
    # It is an observation for CAD hypotheses, never a physical root-cause claim.
    observations=review.get('feedback', {}).get('observations', [])
    if observations:
        last=observations[-1]
        note['last_service_observation']={k:last[k] for k in ('stage','mesh_size_mm','strength_peak',
            'peak_stress_element_centroid_mm','max_von_mises_mpa','max_displacement_mm','numerical_acceptance_complete') if k in last}
    from .design_check import joint_displacement_guidance
    guidance = joint_displacement_guidance(raw, usage.get('governing'), usage['confirmed_failed_criteria'])
    if guidance:
        note.update(guidance)
    return note


def task_status(session, *, export=True):
    session, state, changed = _load(session, current=False)
    histories = {c['id']: [] for c in state['plan']['checks']}
    for binding in state['records']:
        path = Path(binding['path'])
        try:
            if not path.resolve().is_relative_to(session / 'records') or sha256(path) != binding['sha256']:
                raise ValueError('Check record changed or escaped its workspace')
            record = _read(path)
            if record['revision_sha256'] != state['revision_sha256']:
                raise ValueError('Check record belongs to another revision')
            cid = record['check_id']
            if cid != binding['check_id'] or record['method'] != _check(state, cid)['method']:
                raise ValueError('Check record contradicts its task binding')
            if record['kind'] == 'computed':
                rp = Path(record['review']['path'])
                if sha256(rp) != record['review']['sha256']:
                    raise ValueError('Computed review changed')
                review = _read(rp)
                feedback = review_usage_feedback(review)
                outcome = {'pass_under_stated_model': 'pass', 'fail_under_stated_model': 'fail',
                           'insufficient_evidence': 'insufficient_evidence'}[feedback['status']]
                summary = feedback['action']
                limitations = feedback['not_assessed']
                analysis = _analysis_note(review, feedback)
            else:
                if any(not Path(p).is_file() or sha256(Path(p)) != h for p, h in record['bindings'].items()):
                    raise ValueError('External evidence or artifact changed')
                outcome, summary = record['evidence']['outcome'], record['evidence']['summary']
                limitations = record['evidence']['limitations']
            histories[cid].append({'outcome': outcome, 'summary': summary, 'kind': record['kind'],
                                    'record': str(path), 'recorded_at_utc': record['recorded_at_utc'],
                                    'limitations': limitations,
                                    **({'review': record['review']['path'], 'analysis': analysis} if record['kind'] == 'computed' else {})})
            if record.get('retry_reason'):histories[cid][-1]['retry_reason']=record['retry_reason']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # A corrupted latest record cannot reveal an older favorable result.
            cid = binding['check_id']
            if cid in histories:
                histories[cid].append({'outcome': 'insufficient_evidence', 'summary': str(exc),
                                       'kind': 'unavailable', 'record': str(path)})
            else:
                changed.append('Unattributable or missing completion record: ' + str(path))
    rows = []
    for check in state['plan']['checks']:
        history = histories[check['id']]
        latest = history[-1] if history else None
        outcome = 'insufficient_evidence' if changed else latest['outcome'] if latest else 'pending'
        action = ('start_fresh_revision' if changed else 'continue' if outcome == 'pass'
                  else 'choose_analysis_depth' if latest and latest.get('analysis', {}).get('focus') == 'analysis_depth'
                  else 'review_joint_compliance' if latest and latest.get('analysis', {}).get('focus') == 'joint_compliance'
                  else 'review_model_validity' if latest and latest.get('analysis', {}).get('focus') == 'model_validity'
                  else 'review_failed_check' if outcome == 'fail'
                  else 'resolve_evidence_or_analysis' if outcome == 'insufficient_evidence'
                  else 'unsupported' if check['decision'] == 'unsupported'
                  else 'obtain_information' if check['decision'] == 'needs_information'
                  else 'deferred' if check['decision'] == 'later'
                  else (('run_fem' if check['method'] == 'fem' else 'run_calculation') if check['id'] in state['cases'] else 'prepare_case') if computed_check(check)
                  else 'execute_external_check')
        rows.append({'id': check['id'], 'question': check['question'], 'method': check['method'],
                     'required_for_claim': check['required_for_claim'], 'outcome': outcome,
                     'next_action': action, 'latest': latest, 'history': history,
                     'case_ready': check['id'] in state['cases']})
    required = [r for r in rows if r['required_for_claim']]
    remaining = [r['id'] for r in required if r['outcome'] != 'pass']
    status = ('failed' if any(r['outcome'] == 'fail' for r in required) else
              'insufficient_evidence' if remaining or changed else 'declared_checks_complete')
    report = {'schema_version': 'simplecae-task-status-1.0', 'task_id': state['task_id'],
              'request': state['plan']['request'], 'session': str(session),
              'created_at_utc': state['created_at_utc'],
              'revision_sha256': state['revision_sha256'], 'status': status,
              'checks': rows, 'remaining_required_checks': remaining, 'changed_inputs': changed,
              'unknowns': state['plan']['unknowns'], 'whole_product_pass_available': False,
              'viewer_session': state['viewer_session'],
              'meaning': 'Completion of declared checks only. External outcomes are recorded assertions, not independently certified facts or product approval.'}
    if export:
        atomic_json(session / 'task-status.json', report)
        escape = html.escape
        table = ''.join('<tr><td>' + '</td><td>'.join(escape(str(r[k])) for k in
                        ('question', 'method', 'outcome', 'next_action')) + '</td></tr>' for r in rows)
        (session / 'task-status.html').write_text('<!doctype html><meta charset="utf-8"><title>SimpleCAE · 检查进度</title>'
            '<style>body{font:15px/1.6 system-ui;max-width:1100px;margin:32px auto}td,th{padding:10px;text-align:left;border-bottom:1px solid #ddd}</style>'
            '<h1>使用检查进度</h1><p>' + escape(report['request']) + '</p><p>' + escape(status)
            + ' · 声明检查的完成情况，不代表产品通过。外部证据为记录结果。</p>'
            '<table><tr><th>问题</th><th>方法</th><th>结果</th><th>下一步</th></tr>' + table
            + '</table><p><a href="task-status.json">Agent JSON</a></p>', encoding='utf-8')
        # Multiple CAD revisions can share the existing Viewer without copying fields.
        vp = Path(state['viewer_session']) / 'tasks'
        vp.mkdir(exist_ok=True)
        atomic_json(vp / (digest(str(session))[:16] + '.json'), {'session': str(session)})
        export_session(state['viewer_session'])
    return report


def brief_task_status(report):
    """Small opt-in orchestration view; complete history/fields remain on disk."""
    checks = []
    for row in report['checks']:
        item = {k: row[k] for k in ('id', 'question', 'method', 'outcome', 'next_action')}
        latest = row.get('latest') or {}
        item['evidence_kind'] = latest.get('kind')
        if latest.get('review'):item['review_path']=latest['review']
        if latest.get('record'):item['evidence_record_path']=latest['record']
        if latest.get('summary'):
            summary=latest['summary']
            item.update(summary=summary[:500],summary_truncated=len(summary)>500)
        if latest.get('analysis'):
            item['analysis'] = latest['analysis']
        if row['next_action'] == 'choose_analysis_depth':
            item['suggested_command_args'] = ['task', 'run', report['session'], '--check', row['id'], '--depth', 'detailed']
        checks.append(item)
    counts = {state: sum(c['outcome'] == state for c in checks)
              for state in ('pass', 'fail', 'pending', 'insufficient_evidence')}
    message = ('存在已确认不满足的检查；保留失败证据。' if counts['fail'] else
               '部分证据不足或已失效；不能授予通过。' if counts['insufficient_evidence'] else
               '已完成的检查通过；仍有未完成必检项。' if counts['pass'] and report['remaining_required_checks'] else
               '尚有必检项未完成。' if report['remaining_required_checks'] else
               '声明的必检项已完成；不代表产品验收。')
    return {k: report[k] for k in ('schema_version', 'task_id', 'session', 'status', 'revision_sha256',
            'remaining_required_checks', 'changed_inputs', 'unknowns', 'whole_product_pass_available')} | {
        'checks': checks, 'completion_counts': counts, 'progress_message': message,
        'full_report': str(Path(report['session']) / 'task-status.json'),
        'meaning': '仅为声明检查的简报；未决项仍未通过，完整历史与场文件没有删减。'}
