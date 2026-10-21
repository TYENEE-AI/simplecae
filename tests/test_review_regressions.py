"""Behavioral regressions for the seven demonstrated 1.0.0 audit defects."""
import copy
import json
from pathlib import Path
from html.parser import HTMLParser
import pytest
from simplecae.case import write_json
from simplecae.signals import design_signal,compare_results
from simplecae.sources import SourceGuard,source_paths
from simplecae.robot import analyze_robot,load_robot_case
from simplecae.release import delivery_hashes,check_qualification
from simplecae.report import render_report
from test_signals import result

ROOT=Path(__file__).resolve().parents[1]


def envelope(child):
    return {'analysis':'load_case_envelope','case':copy.deepcopy(child['case']),
        'status':child['status'],'cases':[{'name':'compression','status':child['status'],
            'case':child['case'],'assessment':child['assessment']}],'common_payload_scale_limit':.76}


def test_buckling_failure_is_the_envelope_bottleneck():
    child=result();child['case']['buckling']={'enabled':True}
    child['status']=child['assessment']['status']='fail_under_stated_model'
    child['assessment']['buckling']={'mesh_converged':True,'reference_utilization':1.312}
    single=design_signal(child);combined=design_signal(envelope(child))
    assert combined['valid_for_comparison'] and combined['feasible_under_stated_model'] is False
    assert combined['bottleneck_margin']==pytest.approx(single['bottleneck_margin'])
    assert combined['bottleneck_margin']<1
    assert combined['utilizations']=={'compression/'+n:u for n,u in single['utilizations'].items()}


@pytest.mark.parametrize('buckling',[{}, {'mesh_converged':False,'reference_utilization':.5},
    {'mesh_converged':True,'reference_utilization':None},
    {'mesh_converged':True,'reference_utilization':float('nan')}])
def test_unresolved_buckling_withholds_envelope_reward(buckling):
    child=result();child['case']['buckling']={'enabled':True};child['assessment']['buckling']=buckling
    combined=design_signal(envelope(child))
    assert not combined['valid_for_comparison'] and combined['bottleneck_margin'] is None
    json.dumps(combined,allow_nan=False)


def test_component_fem_does_not_change_actuator_metric():
    case=load_robot_case(ROOT/'examples/robots/one-link.robot.json')
    case['poses']=case['poses'][:1]
    child=result();child['assessment']['strength_utilization']=.8;child['robot_load_transfer']={'link':'arm'}
    robot={'analysis':'urdf_static','case':case,'status':'pass_under_stated_model','poses':[
        {'name':'extended','status':'pass_under_stated_model','actuator_efforts':{'shoulder':{'utilization':.03}},
         'contact_equilibrium':None,'components':[child]}]}
    signal=design_signal(robot)
    assert signal['metrics']['max_actuator_utilization']==pytest.approx(.03)
    assert signal['bottleneck_margin']==pytest.approx(1/.8)


@pytest.mark.parametrize('override',[False,True])
def test_actual_urdf_ratings_and_overrides_define_comparability(tmp_path,override):
    fixture=ROOT/'examples/robots';case=load_robot_case(fixture/'one-link.robot.json')
    case['components']=[];case['required_components']=[];case['poses']=case['poses'][:1]
    source=(fixture/'one-link.urdf').read_text(encoding='utf-8').replace('assets/cadgen-beam.stl',str(fixture/'assets/cadgen-beam.stl').replace('\\','/'))
    paths=[];signals=[]
    for rating in (8,80):
        urdf=tmp_path/f'rating-{rating}.urdf'
        urdf.write_text(source.replace('effort="8"',f'effort="{rating}"'),encoding='utf-8')
        c=copy.deepcopy(case);c['model']['path']=str(urdf)
        if override:c['effort_limits']={'shoulder':12}
        path=tmp_path/f'rating-{rating}.json';write_json(path,c)
        solved=analyze_robot(path,tmp_path/f'out-{rating}',preview=False)
        assert solved['status']=='pass_under_stated_model'
        paths.append(tmp_path/f'out-{rating}/result.json');signals.append(solved['evaluation_signal'])
    assert compare_results(paths)['comparable'] is override
    assert (signals[0]['task_contract_sha256']==signals[1]['task_contract_sha256']) is override
    if override:assert signals[0]['bottleneck_margin']==pytest.approx(signals[1]['bottleneck_margin'])


def test_changed_manifest_is_rejected_before_solving(tmp_path,monkeypatch):
    from simplecae.case import load_case
    from simplecae.geometry import make_mesh
    from simplecae.workflow import analyze
    fixture=ROOT/'examples/integration'
    c=load_case(fixture/'simplecad-beam-step.case.json')
    manifest=tmp_path/'interfaces.json'
    original=json.loads((fixture/'simplecad-beam.interfaces.json').read_text(encoding='utf-8'))
    write_json(manifest,original);c['model']['interface_manifest']=str(manifest)
    path=tmp_path/'case.json';write_json(path,c)
    def changed(case,h,out):
        mesh=make_mesh(case,h,out)
        m=copy.deepcopy(original);m['regions']['mount'],m['regions']['payload']=m['regions']['payload'],m['regions']['mount']
        write_json(manifest,m)
        return mesh
    def forbidden(*args):raise AssertionError('A changed mechanical source must not reach the solver')
    monkeypatch.setattr('simplecae.workflow.execute',forbidden)
    solved=analyze(path,tmp_path/'out',preview=False,mesh_factory=changed)
    assert solved['status']=='invalid' and 'source changed' in solved['error']
    assert 'assessment' not in solved and solved['evaluation_signal']['bottleneck_margin'] is None


@pytest.mark.parametrize('changed',['case','urdf'])
def test_robot_source_changes_withhold_pose_envelope_limit(tmp_path,monkeypatch,changed):
    import simplecae.robot as module
    fixture=ROOT/'examples/robots';c=load_robot_case(fixture/'one-link.robot.json')
    c['components']=[];c['required_components']=[]
    urdf=tmp_path/'robot.urdf'
    urdf.write_text((fixture/'one-link.urdf').read_text(encoding='utf-8').replace('assets/cadgen-beam.stl',str(fixture/'assets/cadgen-beam.stl').replace('\\','/')),encoding='utf-8')
    c['model']['path']=str(urdf);case=tmp_path/'case.json';write_json(case,c)
    original=module.static_wrenches;calls=[]
    def mutate(*args,**kwargs):
        result=original(*args,**kwargs)
        if not calls:
            if changed=='case':write_json(case,dict(c,effort_safety_factor=10))
            else:urdf.write_text(urdf.read_text(encoding='utf-8').replace('effort="8"','effort="80"'),encoding='utf-8')
        calls.append(True)
        return result
    monkeypatch.setattr(module,'static_wrenches',mutate)
    solved=module.analyze_robot(case,tmp_path/'out',preview=False)
    assert solved['status']=='invalid' and 'source changed' in solved['error']
    assert 'conditional_payload_limit' not in solved
    assert solved['evaluation_signal']['bottleneck_margin'] is None


@pytest.mark.parametrize('dependency',['model','manifest','template'])
def test_robot_component_guard_covers_all_mechanical_files(tmp_path,dependency):
    from simplecae.benchmarks import bar_case
    model=tmp_path/'bar.step';model.write_bytes(b'stable model')
    manifest=tmp_path/'interfaces.json';write_json(manifest,{'regions':{}})
    c=bar_case('bar',[100,0,0],[5,4,3]);c['schema_version']='2.0'
    c['model']['interface_manifest']='interfaces.json'
    template=tmp_path/'component.json';write_json(template,c)
    paths=source_paths({'components':[{'case_path':str(template)}]})
    assert paths=={model,manifest,template}
    guard=SourceGuard(paths)
    {'model':model,'manifest':manifest,'template':template}[dependency].write_bytes(b'changed')
    with pytest.raises(RuntimeError,match='source changed'):guard.check()


def qualified_fixture(root):
    for folder in ('scripts','assets','examples','references','agents','tests','validation'):(root/folder).mkdir()
    for name in ('SKILL.md','pyproject.toml','requirements-lock.txt','.gitignore'): (root/name).write_text('fixture',encoding='utf-8')
    for name in ('scripts/solver.py','assets/viewer.js','examples/case.json','references/guide.md'):(root/name).write_text('original',encoding='utf-8')
    write_json(root/'validation/standard-validation.json',{'passed':True})
    write_json(root/'validation/release-verification.json',{'passed':True,'toolkit_version':'1.0.1',
        'source_files_sha256':delivery_hashes(root,include_validation=False)})
    write_json(root/'validation/release-audit.json',{'complete':True,'toolkit_version':'1.0.1',
        'requirements':{f'R{i}':{'status':'verified'} for i in range(14)},
        'release_files_sha256':delivery_hashes(root,include_audit=False)})


@pytest.mark.parametrize('changed',['scripts/solver.py','assets/viewer.js','examples/case.json',
    'references/guide.md','SKILL.md','pyproject.toml','validation/standard-validation.json','added','removed'])
def test_qualification_rejects_stale_source_docs_templates_and_evidence(tmp_path,changed):
    qualified_fixture(tmp_path)
    assert check_qualification(tmp_path,'1.0.1')['complete']
    if changed=='added':(tmp_path/'scripts/new.py').write_text('new')
    elif changed=='removed':(tmp_path/'references/guide.md').unlink()
    else:(tmp_path/changed).write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='snapshot'):check_qualification(tmp_path,'1.0.1')


def test_qualification_rejects_other_version(tmp_path):
    qualified_fixture(tmp_path)
    with pytest.raises(ValueError,match='version'):check_qualification(tmp_path,'1.0.2')


class Tables(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ('td','th'):self.cell=''
    def handle_data(self,data):
        if self.cell is not None:self.cell+=data
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:self.row.append(self.cell);self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None


def test_report_preserves_fixed_load_and_couple_semantics(tmp_path):
    r=result();r['case']['gravity']={'acceleration_m_s2':[0,0,-9.81]}
    for i,level in enumerate(r['levels']):
        level.update(mesh_size_mm=5-i,directory=str(tmp_path/f'level-{i}'))
        level['mesh'].update(element_count=1,loads=[
            {'name':'payload','scalable':True,'total_force_n':[-100,0,0],'area_mm2':100,'face_ids':[1],
             'total_moment_n_mm_about_patch_centroid':[0,1,0]},
            {'name':'preload','scalable':False,'total_force_n':[-20,0,0],'area_mm2':100,'face_ids':[2]}])
    render_report(r,tmp_path)
    text=(tmp_path/'report.html').read_text(encoding='utf-8');tables=Tables();tables.feed(text)
    loads={row[0]:row[1:] for row in tables.rows if row and row[0] in ('payload','preload')}
    assert loads['payload'][:3]==['可缩放','[-100, 0, 0]','[0, 1, 0]']
    assert loads['preload'][:3]==['固定不变','[-20, 0, 0]','[0, 0, 0]']
    assert '固定载荷和已建模自重保持不变' in text and '各组载荷同时乘以' not in text
