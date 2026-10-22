"""A task branch's explicit wall-time allowance; not numerical acceptance."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import secrets
import time

from .workbench import atomic_json, now
from .case import sha256
from .diagnostics import WorkflowError


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be finite and positive')
    return float(value)


def path_for(session, state):
    return Path(state.get('execution_budget', Path(session) / 'execution-budget.json'))


def read_budget(session, state):
    path = path_for(session, state)
    if not path.exists():
        return {'path': str(path), 'configured': False, 'remaining_seconds': None,
                'meaning': 'First attempt sets the branch allowance; use total_budget_seconds to plan multiple checks.'}
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema_version') != 'simplecae-execution-budget-1' or value.get('task_id') != state['task_id']:
        raise ValueError('Execution budget belongs to a different task')
    spent = sum(positive(a['charged_seconds'], 'charged_seconds') if a['charged_seconds'] else 0.
                for a in value['attempts'])
    limit = positive(value['limit_seconds'], 'limit_seconds')
    return dict(value, path=str(path), configured=True, spent_seconds=spent,
                remaining_seconds=max(0., limit-spent),
                meaning='Shared across checks and continued CAD revisions. Started/interrupted attempts reserve their full allowance until settled. No engineering verdict.')


@contextmanager
def attempt(session, state, check_id, requested, total=None, reason=None):
    from .process_lock import mutation_lock
    with mutation_lock(path_for(session,state).with_suffix('.lock'),session):
        with _attempt(session,state,check_id,requested,total,reason) as allowance:
            yield allowance


@contextmanager
def _attempt(session, state, check_id, requested, total=None, reason=None):
    requested = positive(requested, 'budget_seconds')
    if total is not None: positive(total, 'total_budget_seconds')
    path = path_for(session, state)
    try:
        value = read_budget(session, state)
        if not value['configured']:
            # Old workspaces must not silently forget previous attempts.
            owner = path.parent.resolve()
            owner_state = owner / 'task-state.json'
            prior = json.loads(owner_state.read_text(encoding='utf-8')) if owner_state.exists() else state
            if prior['task_id'] != state['task_id']:
                raise ValueError('Execution budget owner belongs to a different task')
            history = []
            for binding in prior['records']:
                record_path = Path(binding['path'])
                if not record_path.resolve().is_relative_to(owner / 'records') or sha256(record_path) != binding['sha256']:
                    raise ValueError('Legacy execution record changed or escaped its workspace')
                record = json.loads(record_path.read_text(encoding='utf-8'))
                if record['revision_sha256'] != prior['revision_sha256'] or record['check_id'] != binding['check_id']:
                    raise ValueError('Legacy execution record contradicts its task binding')
                if record.get('kind') != 'computed': continue
                if prior.get('execution_budget'):
                    raise ValueError('Execution budget missing from a previously executed workspace; restore the original ledger before retrying')
                if sha256(Path(record['review']['path'])) != record['review']['sha256']:
                    raise ValueError('Legacy execution review changed')
                review = json.loads(Path(record['review']['path']).read_text(encoding='utf-8'))
                execution = review.get('execution', {})
                charge = execution.get('elapsed_seconds', execution.get('budget_seconds', requested))
                history.append({'id': 'legacy-' + Path(binding['path']).stem, 'state': 'legacy_accounted',
                                'charged_seconds': positive(charge, 'legacy elapsed') if charge else 0.})
            value = {'schema_version': 'simplecae-execution-budget-1', 'task_id': state['task_id'],
                     'limit_seconds': total if total is not None else requested, 'attempts': history, 'changes': []}
        elif total is not None and total != value['limit_seconds']:
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError('Changing a branch allowance requires budget_reason / --budget-reason; retry_reason does not extend it')
            value['changes'].append({'at_utc': now(), 'old_seconds': value['limit_seconds'],
                                     'new_seconds': total, 'reason': reason})
            value['limit_seconds'] = total
        # read_budget adds presentation-only fields; persist just the ledger.
        value = {k: value[k] for k in ('schema_version', 'task_id', 'limit_seconds', 'attempts', 'changes')}
        for interrupted in value['attempts']:
            if interrupted.get('state')=='started':
                interrupted.update(state='interrupted_reserved',recovered_at_utc=now())
                # A hard-killed supervisor cannot settle elapsed time reliably.
                # Retain the complete pre-reserved charge; never reset budget.
        spent = sum(a['charged_seconds'] for a in value['attempts'])
        remaining = value['limit_seconds'] - spent
        if remaining <= 0:
            atomic_json(path, value)
            raise WorkflowError('Task branch budget exhausted. Inspect task status; explicitly revise total_budget_seconds with budget_reason only after a justified execution repair.',
                'branch_budget_exhausted',fields=['total_budget_seconds','budget_reason'],next_action='review_execution_budget',
                details={'spent_seconds':spent,'limit_seconds':value['limit_seconds']})
        allowance = min(requested, remaining)
        record = {'id': secrets.token_hex(8), 'workspace': str(Path(session).resolve()), 'check_id': check_id,
                  'started_at_utc': now(), 'state': 'started', 'allocated_seconds': allowance,
                  'charged_seconds': allowance}
        value['attempts'].append(record)
        atomic_json(path, value)  # Reserve before a worker can be launched.
        started = time.monotonic()
        try:
            yield allowance
        except BaseException:
            record['state'] = 'interrupted'
            raise
        else:
            record['state'] = 'finished'
        finally:
            # Include parsing, report/export and lossless retention overhead.
            record.update(charged_seconds=time.monotonic()-started, finished_at_utc=now())
            atomic_json(path, value)
    finally:
        pass
