"""General workflow regressions: no implicit physics changes or evidence deletion."""
import http.client
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import zipfile
import pytest
from simplecae.case import write_json,sha256
from simplecae.defaults import DEFAULT_EXECUTION_BUDGET,DEFAULT_NATIVE_TIMEOUT
from simplecae.cli import main
from simplecae import api
from simplecae.task import start_task,brief_task_status
from simplecae.region_rules import bind_regions,select_region
from simplecae.cache_lifecycle import plan_cache,archive_cache,restore_cache,verify_archive
from simplecae.diagnostics import WorkflowError,diagnostic
from test_task import request
from test_workflow_iteration import rules

ROOT=Path(__file__).resolve().parents[1]


def test_default_budget_and_cli_api_dispatch_preserve_explicit_limits(tmp_path,monkeypatch,capsys):
    from simplecae.design_check import design_check
    from simplecae.task import run_task_check
    assert DEFAULT_EXECUTION_BUDGET==DEFAULT_NATIVE_TIMEOUT==3000
    assert inspect.signature(design_check).parameters['budget_seconds'].default==3000
    assert inspect.signature(run_task_check).parameters['budget_seconds'].default==3000
    captured=[]
    def analyze(path,out,**kw):captured.append(kw);return {'status':'fail_under_stated_model'}
    monkeypatch.setattr(api,'analyze_case',analyze)
    for options,limit in [([],3000),(['--timeout','17'],17)]:
        assert main(['analyze','case.json','--out',str(tmp_path/'out'),'--quiet',*options])==0
        assert captured[-1]['timeout']==limit and captured[-1]['predict_capacity']
        assert json.loads(capsys.readouterr().out)['status']=='fail_under_stated_model'


def test_planning_surfaces_mesh_policy_and_does_not_silently_ignore_allowance(tmp_path,capsys):
    task=request(tmp_path,fem=True)
    report=brief_task_status(start_task(task,tmp_path/'task'))
    policy=next(c['mesh_policy'] for c in report['checks'] if c['method']=='fem')
    assert policy['minimum_levels']==3 and policy['successive_ratio_maximum']==.8
    assert not policy['coarse_only_can_pass'] and not report['whole_product_pass_available']
    rejected=tmp_path/'ignored'
    assert main(['task','start',str(task),'--out',str(rejected),'--total-budget-seconds','5000'])==2
    assert not rejected.exists() and json.loads(capsys.readouterr().out)['recovery']['code']=='invalid_input'


def test_region_revision_diagnostics_and_native_export_are_hash_bound(tmp_path):
    from simplecae.geometry import session,inventory
    spec=tmp_path/'rules.json';write_json(spec,rules());previous=None
    for i,width in enumerate((10.,12.)):
        model=tmp_path/f'model{i}.step'
        with session() as g:
            g.model.occ.addBox(0,0,0,100,width,10);g.model.occ.synchronize();g.write(str(model))
        out=tmp_path/f'bind{i}.json';r=bind_regions(model,spec,out,previous=previous)
        previous=out
    d=r['region_diagnostics']['mount']
    assert d['area_change_fraction']==pytest.approx(.2)
    assert d['centroid_shift_mm']==pytest.approx([0,1,0]) and not d['intent_verified']
    copied=bind_regions(model,None,tmp_path/'native.json',native_manifest=out,previous=out)
    assert copied['regions']==r['regions']
    with session(model,{'path':str(model)}) as g:info=inventory(g,model)
    with pytest.raises(WorkflowError) as exc:select_region(info,{'surface_types':['Plane'],'face_count':[1,1]})
    assert len(exc.value.diagnostic['details']['candidate_faces'])==6
    wrong=json.loads(out.read_text());wrong['model_sha256']='0'*64;write_json(tmp_path/'stale.json',wrong)
    with pytest.raises(ValueError,match='different model hash'):bind_regions(model,None,tmp_path/'reject.json',native_manifest=tmp_path/'stale.json')


def test_assembly_cost_sums_bodies_without_treating_unknown_as_zero():
    from simplecae.advice import assembly_cost_coverage
    case={'mesh':{'sizes_mm':[4,3,2]},'bodies':[{'name':'a'},{'name':'b','mesh_size_factor':2}]}
    levels={'levels':[{'mesh_size_mm':4,'mesh':{'body_reports':[{'name':'a','element_count':10},{'name':'b','element_count':20}]}}]}
    full=assembly_cost_coverage(case,levels,[],{'a':'A','b':'B'})
    assert full['estimated_total_elements']==240 and full['planning_total_elements']==360
    partial=assembly_cost_coverage(case,{},[{'geometry_sha256':'B','mesh_size_mm':8,'element_count':20}],{'a':'A','b':'B'})
    assert partial['missing_bodies']==['a'] and partial['estimated_total_elements'] is None
    assert partial['observed_subtotal_elements']==160


def make_cache(tmp_path):
    root=tmp_path/'cache';leaf=root/'levels'/('a'*64)/'revision';leaf.mkdir(parents=True)
    (leaf/'job.dat').write_bytes(b'original native evidence\n'*50)
    write_json(leaf.parent/'latest.json',{'directory':'revision','files':{'job.dat':sha256(leaf/'job.dat')}})
    return root,leaf


def test_archive_roundtrip_preserves_originals_and_reports_viewer_references(tmp_path):
    root,leaf=make_cache(tmp_path);ref=tmp_path/'viewer';ref.mkdir()
    write_json(ref/'run.json',{'bindings':{str(leaf/'job.dat'):sha256(leaf/'job.dat')}})
    plan=plan_cache(root,[ref]);assert plan['references'] and not plan['deletion_authorized']
    p=tmp_path/'plan.json';write_json(p,plan)
    archive=tmp_path/'cache.zip';receipt=archive_cache(p,archive)
    assert receipt['originals_retained'] and (leaf/'job.dat').exists()
    restored=tmp_path/'recovered';r=restore_cache(archive,restored)
    assert r['verified_files']==2 and sha256(restored/'levels'/('a'*64)/'revision/job.dat')==sha256(leaf/'job.dat')
    with pytest.raises(ValueError,match='fresh'):restore_cache(archive,restored)
    (leaf/'job.dat').write_text('changed')
    with pytest.raises(ValueError,match='changed'):archive_cache(p,tmp_path/'stale.zip')


def test_archive_rejects_traversal_before_creating_destination(tmp_path):
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('cache-manifest.json',json.dumps({'schema_version':'simplecae-cache-plan-1','files':{'../escape':{'bytes':1,'sha256':'X'}}}))
        z.writestr('data/../escape',b'X')
    out=tmp_path/'new'
    with pytest.raises(ValueError,match='Unsafe'):restore_cache(path,out)
    assert not out.exists()


def test_execution_observation_covers_phases_and_never_overwrites_old_output(tmp_path,monkeypatch):
    def analyze(path,out,**kw):
        Path(out).mkdir(exist_ok=False)
        kw['progress']({'stage':'mesh'});kw['progress']({'stage':'static'});kw['observation'].mark('retention')
        return {'status':'indeterminate'}
    monkeypatch.setattr(api,'_analyze_case',analyze)
    out=tmp_path/'run';r=api.analyze_case('dummy',out)
    observation=out/'execution-observation.json';before=sha256(observation)
    data=json.loads(observation.read_text())
    assert {'mesh','static','retention'}<=set(p['stage'] for p in data['phases'])
    assert data['total_wall_seconds']>=0 and data['native_children_peak_bytes'] is None
    assert r['status']=='indeterminate'
    with pytest.raises(FileExistsError):api.analyze_case('dummy',out)
    assert sha256(observation)==before


def test_disconnect_has_one_response_and_next_request_works(tmp_path):
    from simplecae.workbench import create_session,make_server
    server=make_server(create_session(tmp_path/'viewer'))
    class Broken:
        def write(self,payload):raise ConnectionAbortedError(10053,'Injected Windows disconnect')
    calls=[]
    fake=SimpleNamespace(send_response=lambda code:calls.append(code),send_header=lambda *a:None,
                         end_headers=lambda:None,wfile=Broken())
    server.RequestHandlerClass.reply(fake,200,{'result':'unchanged'})
    assert calls==[200] and fake.close_connection
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10);c.request('GET','/index')
        response=c.getresponse();assert response.status==200
        assert json.loads(response.read())['transport']['aborted_responses']==1;c.close()
    finally:server.shutdown();server.server_close();thread.join()


def test_observation_write_failure_preserves_original_analysis_error(tmp_path,monkeypatch):
    from simplecae.observations import Observation
    def analyze(path,out,**kw):
        Path(out).mkdir()
        raise WorkflowError('Native failure','native_failure',next_action='inspect_solver_log')
    def failed_save(self,completed):raise OSError('disk full')
    monkeypatch.setattr(api,'_analyze_case',analyze)
    monkeypatch.setattr(Observation,'finish',failed_save)
    with pytest.raises(WorkflowError) as caught:api.analyze_case('dummy',tmp_path/'run')
    assert diagnostic(caught.value)['code']=='native_failure'
    assert 'disk full' in caught.value.__notes__[0]


def test_existing_binding_report_is_not_overwritten(tmp_path):
    out=tmp_path/'binding.json';report=out.with_name(out.name+'.binding-report.json')
    report.write_text('retained audit')
    with pytest.raises(ValueError,match='fresh'):bind_regions(tmp_path/'model.step',tmp_path/'rules.json',out)
    assert report.read_text()=='retained audit' and not out.exists()


def test_structured_recovery_preserves_explicit_budget_stop():
    from simplecae import task_budget
    exc=WorkflowError('No allowance','branch_budget_exhausted',fields=['total_budget_seconds'],next_action='review_execution_budget')
    d=diagnostic(exc)
    assert d['code']=='branch_budget_exhausted' and not d['retryable_unchanged']
    assert diagnostic(FileNotFoundError('missing'))['code']=='missing_file'


@pytest.mark.parametrize('module_name',['modal','thermal_solid'])
def test_specialized_viewer_uses_shared_expanded_size_guard(tmp_path,monkeypatch,module_name):
    import importlib
    from simplecae import defaults
    module=importlib.import_module('simplecae.'+module_name)
    class Archive:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def infolist(self):return [SimpleNamespace(file_size=129*1024**2)]
    monkeypatch.setattr(zipfile,'ZipFile',Archive)
    # At 256 MiB this passes the size gate and reaches the missing field file.
    result={'levels':[{}, {}, {'directory':'level-03'}]}
    with pytest.raises(FileNotFoundError):module.viewer_dataset(tmp_path/'result.json',result)
    monkeypatch.setattr(defaults,'DEFAULT_VIEWER_FILE_BYTES',128*1024**2)
    with pytest.raises(ValueError,match='exceeds'):module.viewer_dataset(tmp_path/'result.json',result)
