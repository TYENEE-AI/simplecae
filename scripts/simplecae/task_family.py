"""Compile, preview and analyze required gripper endpoints in one file workflow."""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from pathlib import Path
import json
from .case import write_json,sha256


def family_status(cases,contact_loss=False):
    required=[c for c in cases if c['analysis_required']]
    evaluated=required+[c for c in cases if not c['analysis_required'] and c.get('status') not in (None,'not_run')]
    if not required or any(c.get('status')=='invalid' for c in evaluated):return 'invalid'
    if any(c.get('status') in (None,'not_run','indeterminate') for c in evaluated):return 'indeterminate'
    if contact_loss or any(c['status']=='fail_under_stated_model' for c in evaluated):return 'fail_under_stated_model'
    return 'pass_under_stated_model'


def analyze_gripper_task(path,out,*,ccx=None,timeout=DEFAULT_NATIVE_TIMEOUT,preview=True,progress=None,cache=None,reuse_levels=None,include_nominal=False,ledger=None,storage='compact'):
    from .retention import validate_storage
    validate_storage(storage)
    from .api import analyze_case,check_case,check_gripper_task
    from .sources import SourceGuard,source_paths
    from .robot import read_urdf
    from .progress import emit
    from . import __version__
    path=Path(path).resolve();out=Path(out).resolve()
    if any(p is not None and Path(p).resolve().is_relative_to(out) for p in (cache,reuse_levels)):raise ValueError('task-family cache must be outside its output directory')
    out.mkdir(parents=True,exist_ok=False)
    guard=SourceGuard({path});source_hash=guard.hashes[str(path)]
    result={'schema_version':'simplecae-task-family-1.0','toolkit_version':__version__,
            'source_task':str(path),'source_task_sha256':source_hash,'cases':[],
            'whole_product_rating_available':False,'comparison_margin':None,
            'known_failures':[],'conditional_product_capacity_available':False,
            'scope':'Declared gripper task and separately analyzed force endpoints only; no universal ranking or product rating, and no interpolation guarantee for buckling, nonlinear behavior or changing contact.'}
    try:
        task=check_gripper_task(path);result['task_id']=task['task_id'];guard.check()
        emit(progress,'task_compile',task_id=task['task_id'])
        if 'force_measurement' in task:
            from .force_envelope import compile_force_envelope
            compiled=compile_force_envelope(task,path,out/'compiled');cases=compiled['cases'];result['force_budget']=compiled['force_budget']
            result['force_envelope_relative_path']='compiled/force-envelope.json'
        else:
            from .grasp import compile_gripper_task
            c=compile_gripper_task(task,path);directory=out/'compiled';directory.mkdir()
            child=directory/'nominal.robot.json';write_json(child,c)
            cases=[{'name':'nominal','case_path':str(child),'case_sha256':sha256(child),'normal_force_per_finger_n':task['normal_force_per_finger_n'],'analysis_required':True}]
        result['cases']=[dict(c,status='not_run',case_relative_path=str(Path(c['case_path']).relative_to(out))) for c in cases]
        resolved=[check_case(c['case_path']) for c in cases]
        guard.add([c['case_path'] for c in cases])
        for c in resolved:guard.add(source_paths(c))
        # Capture assets across the whole family, not just one endpoint run.
        robot=read_urdf(resolved[0]['model']['path'],resolved[0]['model']['package_roots'],resolved[0].get('massless_links',[]))
        guard.add([asset['path'] for asset in robot['assets']])
        if any(guard.hashes[a['path']]!=a['sha256'] for a in robot['assets']):raise RuntimeError('URDF visual/collision asset changed while preparing task family')
        result['source_files_sha256']=guard.hashes
        for i,c in enumerate(result['cases']):
            if not c['analysis_required'] and not include_nominal:continue
            guard.check();child=Path(c['case_path']);directory=out/c['name']
            if sha256(child)!=c['case_sha256']:raise RuntimeError('compiled force endpoint changed before analysis')
            emit(progress,'force_endpoint',name=c['name'],normal_force_n=c['normal_force_per_finger_n'])
            guard.check()
            if preview:
                from .preflight import preview_case
                p=preview_case(child,out/(c['name']+'-preview'))
                c['preview_relative_path']=str(Path(p['preview']).relative_to(out))
            solved=analyze_case(child,directory,ccx=ccx,timeout=timeout,preview=preview,progress=progress,cache=cache,reuse_levels=reuse_levels,storage=storage)
            c.update(status=solved['status'],result_relative_path=c['name']+'/result.json',report_relative_path=c['name']+'/report.html',
                     valid_for_comparison=solved['evaluation_signal']['valid_for_comparison'],
                     physical_conditions_verified=solved['evaluation_signal']['physical_conditions_verified'])
            if solved.get('error'):c['error']=solved['error']
            guard.check()
            if sha256(child)!=c['case_sha256']:raise RuntimeError('compiled force endpoint changed during analysis')
            write_json(out/'task-family.json',result)
        contact_loss=result.get('force_budget',{}).get('contact_not_assured',False)
        if contact_loss:result['known_failures'].append({'criterion':'force_lower_bound','status':'fail_under_stated_model','message':'Declared uncertainty permits zero contact force. Upper-force analysis cannot establish grip retention.'})
        result['status']=family_status(result['cases'],contact_loss)
        if result['status']=='invalid':result['error']='At least one analyzed force endpoint is invalid: '+'; '.join(c['name']+': '+c.get('error',c['status']) for c in result['cases'] if c['status']=='invalid')
        paths=[out/c['result_relative_path'] for c in result['cases'] if c.get('result_relative_path')]
        from .application import summarize_application
        application=summarize_application(paths,out/'application','夹爪任务：分别检查夹力端点与产品证据',ledger=ledger)
        result['application_relative_path']='application/application.html'
        guard.check()
    except Exception as exc:
        result['status']='invalid';result['error']=f'{type(exc).__name__}: {exc}'
    write_json(out/'task-family.json',result);render_family(result,out)
    return result


def render_family(result,out):
    import html
    from .product import STYLE
    labels={'not_run':'参考输入，未求解','pass_under_stated_model':'声明模型下满足','fail_under_stated_model':'声明模型下不满足','indeterminate':'尚有数值证据不足','invalid':'计算无效'}
    rows=''
    for c in result['cases']:
        refs=[]
        for key,label in (('preview_relative_path','求解前载荷'),('report_relative_path','计算与覆盖')):
            if c.get(key):refs.append('<a href="'+html.escape(c[key],quote=True)+'">'+label+'</a>')
        rows+='<tr><td>'+html.escape(c['name'])+'</td><td>'+f"{c['normal_force_per_finger_n']:.6g} N"+'</td><td>'+('必检' if c['analysis_required'] else '参考')+'</td><td>'+labels[c['status']]+'</td><td>'+' / '.join(refs)+'</td></tr>'
    body='<h1>夹爪任务与夹力端点</h1><p><b>'+labels[result['status']]+'</b>。下限和上限均需检查结构、驱动与抓取；反向固定载荷下，较小夹力也可能更苛刻。没有根据单个目标夹力跳过端点。</p>'
    if result.get('force_budget'):
        b=result['force_budget'];body+='<p>测得保持区间 '+html.escape(str(b['measured_hold_interval_n']))+f" N，声明误差 ±{b['absolute_error_n']:.6g} N → 声明真实力范围 {b['lower_normal_force_n']:.6g}–{b['upper_normal_force_n']:.6g} N。"+('测量与保持窗口有外部核对声明。' if b['measurement_conditions_verified'] else '标定/保持误差仍未实物验证。')+'</p>'
    if result.get('error'):body+='<p>'+html.escape(result['error'])+'</p>'
    body+='<table><tr><th>端点</th><th>每指法向力</th><th>必要性</th><th>结果</th><th>证据</th></tr>'+rows+'</table>'
    for failure in result['known_failures']:body+='<p><b>已确认的声明条件失败：</b>'+html.escape(failure['message'])+'</p>'
    if result.get('application_relative_path'):body+='<p><a href="'+result['application_relative_path']+'">查看所有零件覆盖、未评估项和产品证据清单</a></p>'
    body+='<p>本报告检查明确列出的端点；不保证屈曲、非线性或变化接触的区间内行为。没有给出整机认证、额定承重或统一优化分数。</p>'
    (Path(out)/'task-family.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>SimpleCAE gripper task</title><style>'+STYLE+'table{width:100%;border-collapse:collapse}td,th{border:1px solid #cbd5df;padding:10px}</style>'+body+'</html>',encoding='utf-8')
