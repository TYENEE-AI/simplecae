"""Local, source-bound review sessions. No solver or CAD commands from the browser."""
from __future__ import annotations

from .paths import resource_root
import hashlib
import json
import secrets
import shutil
import threading
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np

from .case import sha256, write_json
from .signals import compare_results, design_signal
from .viewer import viewer_data

SCHEMA = 'simplecae-viewer-1.0'
ASSETS = resource_root() / 'assets'
MAX_FILE = 128 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_FILE:
        raise ValueError('Viewer input exceeds 128 MiB')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    write_json(temp, value)
    temp.replace(path)


def session_config(session):
    cfg = read_json(Path(session) / 'viewer.json')
    if cfg.get('schema_version') != SCHEMA:
        raise ValueError('Not a SimpleCAE Viewer session')
    return cfg


def create_session(session, title='SimpleCAE · 分析审阅'):
    session = Path(session).resolve()
    session.mkdir(parents=True, exist_ok=False)
    (session / 'runs').mkdir()
    (session / 'feedback').mkdir()
    atomic_json(session / 'viewer.json', {'schema_version': SCHEMA, 'title': title,
                'created_at_utc': now(), 'feedback_token': secrets.token_urlsafe(32)})
    for name in ('workbench.js', 'workbench.css'):
        shutil.copyfile(ASSETS / name, session / name)
    return session


def contained(root, path):
    path = Path(path).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Field evidence must stay within the registered result directory')
    return path


def leaves(result, prefix=''):
    if result.get('analysis') in ('thermal_solid', 'modal'):
        return
    if result.get('levels'):
        yield prefix or '主体', result
    for level in result.get('diagnostic_levels',[]):
        yield (prefix+' / 未通过诊断场（不可用于判定通过） / '+level.get('stage','service')).strip(' /'),{
            'levels':[level],'case':result.get('case',{}),'assessment':{},
            'diagnostic_only':True,'unaccepted_reason':level.get('unaccepted_reason')}
    for pose in result.get('poses', []):
        for component in pose.get('components', []):
            name = component.get('robot_load_transfer', {}).get('link', 'component')
            yield from leaves(component, f"{pose['name']} / {name}")
    for case in result.get('cases', []):
        yield from leaves(case, f"{prefix} / {case.get('name', 'load case')}".strip(' /'))


def evidence_files(path, result):
    files = [Path(path).resolve()]
    if result.get('analysis') in ('thermal_solid', 'modal'):
        files.extend(contained(Path(path).parent, p) for p in result.get('evidence_files', {}))
    for _, body in leaves(result):
        directory = contained(Path(path).parent, body['levels'][-1]['directory'])
        files.extend(directory / name for name in ('mesh.npz', 'fields.npz'))
    for file in files:
        if file.stat().st_size > MAX_FILE:
            raise ValueError('Viewer evidence exceeds 128 MiB per file')
    return {str(p): sha256(p) for p in files}


def finish_record(record, result_path):
    path = Path(result_path).resolve()
    result = read_json(path)
    record.update(state='completed', result=str(path), finished_at_utc=now(),
                  bindings=evidence_files(path, result))
    return record


def add_result(session, result_path, label=None, change_note=''):
    session = Path(session).resolve()
    session_config(session)
    record = {'id': secrets.token_hex(8), 'label': label or Path(result_path).parent.name,
              'change_note': change_note, 'started_at_utc': now(), 'events': []}
    finish_record(record, result_path)
    atomic_json(session / 'runs' / (record['id'] + '.json'), record)
    return record['id']


class RunRecorder:
    """One atomic record per attempt; abrupt termination never invents completion."""
    def __init__(self, session, case, out, label=None, change_note='', callback=None):
        self.session = Path(session).resolve()
        session_config(self.session)
        self.callback = callback
        self.record = {'id': secrets.token_hex(8), 'label': label or Path(out).name,
                       'case': str(Path(case).resolve()), 'source_case_sha256': sha256(Path(case)),
                       'out': str(Path(out).resolve()), 'state': 'pending', 'started_at_utc': now(),
                       'change_note': change_note, 'events': []}
        self.path = self.session / 'runs' / (self.record['id'] + '.json')
        atomic_json(self.path, self.record)

    def __call__(self, event):
        self.record['events'] = (self.record['events'] + [dict(event, at_utc=now())])[-80:]
        atomic_json(self.path, self.record)
        if self.callback:
            self.callback(event)

    def finish(self):
        try:
            finish_record(self.record, Path(self.record['out']) / 'result.json')
        except Exception as exc:
            self.record.update(state='unavailable', result=str(Path(self.record['out']) / 'result.json'),
                               error=f'Viewer import: {type(exc).__name__}: {exc}', finished_at_utc=now())
            atomic_json(self.path, self.record)
            export_session(self.session)
            return self.record['error']
        atomic_json(self.path, self.record)
        export_session(self.session)

    def fail(self, error):
        self.record.update(state='interrupted', error=str(error), finished_at_utc=now())
        atomic_json(self.path, self.record)
        export_session(self.session)


def dataset(path, label, body):
    level = body['levels'][-1]
    directory = contained(path.parent, level['directory'])
    for name in ('mesh.npz', 'fields.npz'):
        with zipfile.ZipFile(directory / name) as archive:
            if len(archive.infolist()) > 32 or sum(info.file_size for info in archive.infolist()) > MAX_FILE:
                raise ValueError('Expanded field evidence exceeds 128 MiB or 32 arrays')
        with np.load(directory / name, allow_pickle=False) as archive:
            if any(not np.all(np.isfinite(archive[k])) for k in archive.files):
                raise ValueError('Nonfinite mesh/field data cannot be displayed')
    data = viewer_data(directory, include_modes=False)
    with np.load(directory / 'mesh.npz', allow_pickle=False) as mesh:
        faces = [int(n) for n in mesh['surface_face_ids']]
        owners = {}
        for e, ns in zip(mesh['element_ids'], mesh['connectivity']):
            for face in ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)):
                owners[tuple(sorted(int(ns[i]) for i in face))] = int(e)
        elements = [owners[tuple(sorted(map(int, tri[:3])))] for tri in mesh['surface_tri6']]
    data.update(id=hashlib.sha256(label.encode()).hexdigest()[:12], label=label,
                face_ids=[f for f in faces for _ in range(4)],
                element_ids=[e for e in elements for _ in range(4)],
                mesh={k:v for k,v in level['mesh'].items() if k in ('node_count','element_count','mesh_size_mm','geometry','support_faces','loads','element_type','body_reports')}, results=level['results'], assessment=body.get('assessment', {}),
                case=body.get('case', {}), meaning='局部有限元坐标，mm；应力为相邻体单元积分点峰值。')
    # Modes have separate, arbitrary amplitudes. Keep legacy report modes outside this MVP.
    data.pop('modes', None)
    if body.get('diagnostic_only'):
        data.update(diagnostic_only=True,unaccepted_reason=body.get('unaccepted_reason'),
                    meaning='未通过的诊断原始场；仅供排查，不能用于判定通过、排名或承重预测。')
    if len(data['xyz']) > 300000 or len(data['triangles']) > 400000:
        raise ValueError('Display budget exceeded (300k nodes / 400k triangles); use the original report')
    return data


def snapshot(session):
    session = Path(session).resolve()
    cfg = session_config(session)
    records = []
    for file in sorted((session / 'runs').glob('*.json')):
        record = read_json(file)
        item = dict(record, datasets=[])
        item.pop('bindings', None)
        if record.get('design_review'):
            try:
                binding=record['design_review'];review_path=Path(binding['path'])
                if sha256(review_path)!=binding['sha256']:
                    raise ValueError('Design review changed; re-import the evidence')
                review=read_json(review_path)
                item['design_context']=review['context']
                item['design_depth']=review['depth']
                item['design_check_execution']=review['execution']
                item['design_check_feedback']=review['feedback']
                item['design_context_sha256']=review['context_contract_sha256']
                if review.get('usage_plan'):
                    from .use_plan import review_usage_feedback
                    if Path(review['result']['path']).resolve() != Path(record['result']).resolve():
                        raise ValueError('Usage review references a different displayed result')
                    expected = review_usage_feedback(review)
                    item['usage_feedback'] = expected
                    item['usage_contract_sha256'] = review['usage_plan']['contract_sha256']
                    item['usage_check_id'] = review['usage_plan']['selected_check_id']
                    item['usage_remaining_checks'] = [c['question'] for c in review['usage_plan']['contract']['checks']
                                                      if c['id'] in expected['remaining_required_checks']]
            except Exception as exc:
                item.update(state='unavailable',error=str(exc))
                records.append(item)
                continue
        if record['state'] == 'completed':
            try:
                if not record.get('bindings') or any(sha256(Path(p)) != h for p, h in record['bindings'].items()):
                    raise ValueError('Registered result or field files changed; re-import as a new revision')
                path = Path(record['result'])
                result = read_json(path)
                item['result_sha256'] = record['bindings'][str(path)]
                item['signal'] = design_signal(result)
                item['status'] = result['status']
                item['analysis'] = result.get('analysis')
                item['case'] = result.get('case', {})
                item['not_assessed'] = result.get('not_assessed', item['signal'].get('not_assessed', []))
                item['coverage'] = result.get('coverage', item['signal'].get('coverage', {}))
                item['poses'] = [{k: v for k, v in pose.items() if k not in ('components',)} for pose in result.get('poses', [])]
                item['datasets'] = [dataset(path, label, body) for label, body in leaves(result)]
                if result.get('analysis') == 'modal':
                    from .modal import viewer_dataset
                    modal_data = viewer_dataset(path, result)
                    item['datasets'] = [modal_data] if modal_data else []
                if result.get('analysis') == 'thermal_solid':
                    from .thermal_solid import viewer_dataset
                    thermal_data = viewer_dataset(path, result)
                    item['datasets'] = [thermal_data] if thermal_data else []
                if result.get('analysis') == 'thermal_network':
                    from .thermal_network import display_history
                    item['thermal_display'] = display_history(result)
                if result.get('analysis') == 'motion_loads':
                    item['motion_display'] = {'states': result.get('states', []),
                                              'meaning': '仅列出的刚体运动状态；不是应力、变形场或完整轨迹包络。'}
                if result.get('analysis') in ('fatigue_data', 'creep_data'):
                    item['durability_display'] = {'mode': result['analysis'], 'points': result.get('points', {}),
                        'criteria': result.get('criterion_assessments', {}),
                        'meaning': '仅限声明位置、使用条件及材料数据范围；不代表整件或产品寿命。'}
                if result.get('visualization'):
                    item['robot_visualization'] = result['visualization']
                if result.get('error'):
                    item['error'] = result['error']
            except Exception as exc:
                item.update(state='unavailable', status='invalid', error=f'{type(exc).__name__}: {exc}', datasets=[])
                item.pop('signal', None)
        records.append(item)
    records.sort(key=lambda r: (r['started_at_utc'], r['id']))
    notes = [read_json(p) for p in sorted((session / 'feedback').glob('*.json'))]
    tasks = []
    for reference in sorted((session / 'tasks').glob('*.json')):
        try:
            from .task import task_status
            tasks.append(task_status(read_json(reference)['session'], export=False))
        except Exception as exc:
            tasks.append({'status': 'insufficient_evidence', 'error': str(exc), 'checks': [],
                          'whole_product_pass_available': False})
    tasks.sort(key=lambda t: t.get('created_at_utc', ''), reverse=True)
    for item in records:
        review = item.get('design_review', {}).get('path')
        if not review:
            continue
        for task in tasks:
            if item.get('task_workspace') == task.get('session') or any(
                    c.get('latest', {}).get('review') == review for c in task['checks'] if c.get('latest')):
                item['usage_remaining_checks'] = [c['question'] for c in task['checks']
                    if c['required_for_claim'] and c['outcome'] != 'pass' and c['id'] != item.get('usage_check_id')]
                item['task_revision_sha256'] = task['revision_sha256']
                selected = next((c for c in task['checks'] if c['id'] == item.get('usage_check_id')), None)
                if selected and selected.get('latest', {}).get('analysis'):
                    item['task_guidance'] = selected['latest']['analysis']
                if task.get('changed_inputs') or not selected or not selected.get('latest') or selected['latest']['kind'] == 'unavailable':
                    item.update(state='unavailable', error='Task source or completion evidence changed; current acceptance withheld', datasets=[])
                    item.pop('signal', None)
                break
    return {'schema_version': SCHEMA, 'title': cfg['title'], 'exported_at_utc': now(),
            'session': str(session), 'runs': records, 'notes': notes, 'tasks': tasks}


def compare_runs(session, left_id, right_id):
    data = snapshot(session)
    runs = {r['id']: r for r in data['runs']}
    selected = [runs.get(i) for i in (left_id, right_id)]
    if not all(r and r['state'] == 'completed' and r.get('signal', {}).get('valid_for_comparison') for r in selected):
        return {'comparable': False, 'withheld_reasons': ['完整且有效的两份分析证据才可比较。']}
    if any(r.get('design_review') for r in selected):
        if not all(r.get('design_review') for r in selected):
            return {'comparable':False,'withheld_reasons':['设计检查需要相同范围与假设的配对记录。']}
        from .design_check import compare_design_checks
        return compare_design_checks([r['design_review']['path'] for r in selected])
    return compare_results([Path(r['result']) for r in selected])


def save_note(session, incoming):
    data = snapshot(session)
    run = next((r for r in data['runs'] if r['id'] == incoming.get('run_id')), None)
    if not run or run['state'] != 'completed' or run['result_sha256'] != incoming.get('result_sha256'):
        raise ValueError('Annotation must bind to unchanged completed evidence')
    text = incoming.get('text', '')
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError('Annotation text must be 1–4000 characters')
    note = {'schema_version': 'simplecae-viewer-feedback-1.0', 'id': secrets.token_hex(8),
            'created_at_utc': now(), 'run_id': run['id'], 'result': run['result'],
            'result_sha256': run['result_sha256'], 'label': run['label'], 'text': text.strip(),
            'state': 'unread', 'meaning': 'User review data for the agent; not a changed task or an executed instruction.'}
    if incoming.get('dataset_id'):
        d = next((d for d in run['datasets'] if d['id'] == incoming['dataset_id']), None)
        t = incoming.get('triangle')
        if not d or type(t) is not int or not 0 <= t < len(d['triangles']):
            raise ValueError('Invalid display triangle')
        xyz = np.asarray([d['xyz'][n] for n in d['triangles'][t]]).mean(axis=0).tolist()
        note['region'] = {'dataset_id': d['id'], 'dataset': d['label'], 'display_triangle': t,
                          'point_mm': xyz, 'element_id': d['element_ids'][t], 'face_id': d['face_ids'][t],
                          'meaning': 'Display triangle centroid, not an interpolated material probe or a new load/support.'}
    atomic_json(Path(session) / 'feedback' / (note['id'] + '.json'), note)
    return note


def export_session(session):
    data = snapshot(session)
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    template = (ASSETS / 'workbench.html').read_text(encoding='utf-8')
    (Path(session) / 'index.html').write_text(template.replace('__SIMPLECAE_DATA__', encoded), encoding='utf-8')
    for name in ('workbench.js', 'workbench.css'):
        shutil.copyfile(ASSETS / name, Path(session) / name)
    return data


def signature(session):
    records = sorted((Path(session) / 'runs').glob('*.json')) + sorted((Path(session) / 'feedback').glob('*.json')) + sorted((Path(session) / 'tasks').glob('*.json'))
    parts = []
    for file in records:
        parts.append((str(file), file.stat().st_mtime_ns, file.stat().st_size))
        if file.parent.name == 'tasks':
            task_dir = Path(read_json(file)['session'])
            task_files = [task_dir / 'task-state.json', *sorted((task_dir / 'records').glob('*.json'))]
            if (task_dir / 'task-state.json').is_file():
                task_files += [Path(p) for p in read_json(task_dir / 'task-state.json').get('bindings', {})]
            for receipt in (task_dir / 'records').glob('*.json'):
                try:
                    task_files += [Path(p) for p in read_json(receipt).get('bindings', {})]
                except (OSError, ValueError):
                    pass
            for p in task_files:
                if p.is_file():
                    parts.append((str(p), p.stat().st_mtime_ns, p.stat().st_size))
                else:
                    parts.append((str(p), None))
        if file.parent.name == 'runs':
            for name in read_json(file).get('bindings', {}):
                p = Path(name)
                parts.append((name, p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else (name, None))
    return hashlib.sha256(repr(parts).encode()).hexdigest()


def make_server(session, port=0):
    session = Path(session).resolve()
    cfg = session_config(session)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, value, kind='application/json; charset=utf-8'):
            payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() if isinstance(value, (dict, list)) else value
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def allowed(self):
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            return self.headers.get('Host') in hosts and self.headers.get('Origin', 'http://' + self.headers.get('Host', '')) in {'http://' + h for h in hosts}

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {'error': 'Loopback origin required'})
            route = urlsplit(self.path).path
            try:
                with lock:
                    if route == '/index':
                        return self.reply(200, {'signature': signature(session)})
                    if route == '/state':
                        return self.reply(200, dict(snapshot(session), feedback_token=cfg['feedback_token']))
                    if route in ('/', '/index.html'):
                        export_session(session)
                        return self.reply(200, (session / 'index.html').read_bytes(), 'text/html; charset=utf-8')
                    if route in ('/workbench.js', '/workbench.css'):
                        return self.reply(200, (session / route[1:]).read_bytes(), 'text/javascript; charset=utf-8' if route.endswith('.js') else 'text/css; charset=utf-8')
                self.reply(404, {'error': 'Not found'})
            except Exception as exc:
                self.reply(400, {'error': str(exc)})

        def do_POST(self):
            if not self.allowed() or self.headers.get('X-SimpleCAE-Token') != cfg['feedback_token']:
                return self.reply(403, {'error': 'Same-origin review token required'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 20000:
                    raise ValueError('Request exceeds the note budget')
                incoming = json.loads(self.rfile.read(size))
                with lock:
                    if self.path == '/feedback':
                        return self.reply(200, save_note(session, incoming))
                    if self.path == '/compare':
                        return self.reply(200, compare_runs(session, incoming['left'], incoming['right']))
                self.reply(404, {'error': 'Not found'})
            except Exception as exc:
                self.reply(400, {'error': str(exc)})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def serve(session, port=0, open_browser=False):
    server = make_server(session, port)
    print(json.dumps({'viewer_url': f'http://127.0.0.1:{server.server_port}/', 'session': str(Path(session).resolve()),
                      'meaning': 'Local review only; Ctrl+C stops the Viewer.'}, ensure_ascii=False), flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{server.server_port}/')
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
