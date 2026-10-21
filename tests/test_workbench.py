"""Evidence and interaction guards; synthetic tetrahedra are not mechanical validation."""
import http.client
import json
import threading

import numpy as np
import pytest

from simplecae.case import write_json
from simplecae.workbench import (RunRecorder, add_result, compare_runs, create_session,
    export_session, make_server, save_note, session_config, snapshot)
from test_signals import result as assessed_result


def evidence(tmp_path, name='solve', change=None):
    root=tmp_path/name;level=root/'level-03';level.mkdir(parents=True)
    xyz=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1],[.5,0,0],[.5,.5,0],
                  [0,.5,0],[0,0,.5],[.5,0,.5],[0,.5,.5]])
    np.savez(level/'mesh.npz',node_ids=np.arange(1,11),xyz=xyz,element_ids=[42],
             connectivity=[np.arange(1,11)],surface_tri6=[[1,2,3,5,6,7]],surface_face_ids=[9])
    np.savez(level/'fields.npz',node_ids=np.arange(1,11),displacements=np.tile([.002,0,0],(10,1)),
             stress_ids=[[42,1],[42,2]],stresses=[[1,0,0,0,0,0],[10,0,0,0,0,0]],strength_utilizations=[.1,.4])
    r=assessed_result()
    for l in r['levels']:l['directory']=str(level)
    if change:change(r)
    write_json(root/'result.json',r)
    return root/'result.json'


def test_fields_preserve_peak_and_material_region(tmp_path):
    path=evidence(tmp_path);s=create_session(tmp_path/'viewer')
    add_result(s,path);r=snapshot(s)['runs'][0];d=r['datasets'][0]
    assert r['signal']['valid_for_comparison']
    assert d['stress']==[10]*4 and d['strength']==[.4]*4
    assert d['face_ids']==[9]*4 and d['element_ids']==[42]*4
    assert d['displacements'][0]==[.002,0,0]
    assert not r['signal']['whole_installation_rating_available']

def test_surface_display_omits_unused_nodes_without_changing_geometry_fields_or_modes(tmp_path):
    from simplecae.viewer import viewer_data
    path=evidence(tmp_path);directory=path.parent/'level-03'
    with np.load(directory/'mesh.npz') as mesh:
        original_xyz=mesh['xyz'].copy()
    with np.load(directory/'fields.npz') as fields:
        values={key:fields[key] for key in fields.files}
    # Distinct fields catch incorrect index remapping, including mode vectors.
    values['displacements']=np.arange(30,dtype=float).reshape(10,3)
    np.savez(directory/'fields.npz',**values)
    vectors=np.arange(30,dtype=float).reshape(10,3)*.25
    np.savez(directory/'buckling-mode-01.npz',node_ids=np.arange(1,11),displacements=vectors)
    field=viewer_data(directory)
    used=[0,1,2,4,5,6]
    assert field['xyz']==original_xyz[used].tolist()
    assert field['displacements']==values['displacements'][used].tolist()
    assert field['modes']['buckling-mode-01']==vectors[used].tolist()
    expected=[[0,4,6],[4,1,5],[6,5,2],[4,5,6]]
    actual=np.array(field['xyz'])[field['triangles']]
    assert np.array_equal(actual,original_xyz[expected])
    assert field['stress']==[10]*4 and field['strength']==[.4]*4
    assert field['display']=={'volume_node_count':10,'surface_node_count':6,
                             'omitted_interior_nodes':4,'surface_triangles_unchanged':True}
    session=create_session(tmp_path/'viewer');add_result(session,path)
    shown=snapshot(session)['runs'][0]['datasets'][0]
    assert shown['face_ids']==[9]*4 and shown['element_ids']==[42]*4
    assert shown['results']==json.loads(path.read_text())['levels'][-1]['results']


def test_invalid_contact_diagnostic_keeps_peaks_without_promoting_evidence(tmp_path):
    path=evidence(tmp_path)
    r=json.loads(path.read_text());r['status']='invalid';r['error']='compression-only contact unexpectedly carries tensile pressure'
    level=r['levels'][-1];level.update(diagnostic_only=True,unaccepted_reason=r['error'])
    r['levels']=[];r['diagnostic_levels']=[level];r.pop('assessment',None);write_json(path,r)
    session=create_session(tmp_path/'viewer');add_result(session,path)
    record=snapshot(session)['runs'][0];field=record['datasets'][0]
    assert record['status']=='invalid' and not record['signal']['valid_for_comparison']
    assert field['diagnostic_only'] and field['stress']==[10]*4 and field['strength']==[.4]*4
    assert field['unaccepted_reason']==r['error'] and not record['signal']['whole_installation_rating_available']


def test_unused_modes_are_not_loaded_or_depicted(tmp_path):
    path=evidence(tmp_path)
    (path.parent/'level-03/buckling-mode-01.npz').write_bytes(b'not a mode archive')
    s=create_session(tmp_path/'viewer');add_result(s,path)
    r=snapshot(s)['runs'][0]
    assert r['state']=='completed' and 'modes' not in r['datasets'][0]

def test_viewer_does_not_embed_solver_only_payload_but_preserves_all_field_peaks(tmp_path):
    path=evidence(tmp_path)
    r=json.loads(path.read_text())
    for level in r['levels']:level['mesh']['fixed_nodal_forces']={'opaque_solver_payload':'x'*1_000_000}
    write_json(path,r);session=create_session(tmp_path/'viewer');add_result(session,path)
    record=snapshot(session)['runs'][0];field=record['datasets'][0]
    assert len(json.dumps(field))<100_000 and field['stress']==[10]*4
    assert record['signal']['valid_for_comparison'] and 'opaque_solver_payload' in path.read_text()


@pytest.mark.parametrize('node_row',[0,3])
def test_nonfinite_fields_do_not_take_down_other_revisions(tmp_path,node_row):
    path=evidence(tmp_path,'bad');fields=path.parent/'level-03/fields.npz'
    with np.load(fields) as f:values={k:f[k] for k in f.files}
    values['displacements'][node_row,0]=float('nan');np.savez(fields,**values)
    s=create_session(tmp_path/'viewer');add_result(s,path);add_result(s,evidence(tmp_path,'good'))
    bad,good=snapshot(s)['runs']
    assert bad['state']=='unavailable' and good['state']=='completed'


@pytest.mark.parametrize('file',['result.json','level-03/fields.npz','level-03/mesh.npz'])
def test_modified_evidence_withholds_model_and_verdict(tmp_path,file):
    path=evidence(tmp_path);s=create_session(tmp_path/'viewer');add_result(s,path)
    with (path.parent/file).open('ab') as stream:stream.write(b' ')
    r=snapshot(s)['runs'][0]
    assert r['state']=='unavailable' and r['status']=='invalid' and not r['datasets'] and 'signal' not in r


def test_same_task_comparison_rejects_changed_load_or_gate(tmp_path):
    s=create_session(tmp_path/'viewer');a=add_result(s,evidence(tmp_path,'a'))
    b=add_result(s,evidence(tmp_path,'b'))
    assert compare_runs(s,a,b)['comparable']
    c=add_result(s,evidence(tmp_path,'c',lambda r:r['case']['loads'][0]['total_force_n'].__setitem__(2,-50)))
    assert not compare_runs(s,a,c)['comparable']
    d=add_result(s,evidence(tmp_path,'d',lambda r:r['assessment']['verification'].__setitem__('mesh_converged',False)))
    assert not compare_runs(s,a,d)['comparable']


def test_foreign_field_path_rejected(tmp_path):
    foreign=evidence(tmp_path,'foreign');path=evidence(tmp_path,'actual')
    r=json.loads(path.read_text());r['levels'][-1]['directory']=str(foreign.parent/'level-03');write_json(path,r)
    s=create_session(tmp_path/'viewer')
    with pytest.raises(ValueError,match='within'):add_result(s,path)


def test_note_binds_derived_region_and_stays_unread(tmp_path):
    s=create_session(tmp_path/'viewer');add_result(s,evidence(tmp_path));r=snapshot(s)['runs'][0];d=r['datasets'][0]
    incoming={'run_id':r['id'],'result_sha256':r['result_sha256'],'dataset_id':d['id'],
              'triangle':0,'point_mm':[99,99,99],'text':'检查安装孔'}
    n=save_note(s,incoming)
    assert np.allclose(n['region']['point_mm'],[1/6,1/6,0])
    assert n['region']['element_id']==42 and n['region']['face_id']==9 and n['state']=='unread'
    incoming['result_sha256']='wrong'
    with pytest.raises(ValueError):save_note(s,incoming)
    incoming['result_sha256']=r['result_sha256'];incoming['triangle']=-1
    with pytest.raises(ValueError):save_note(s,incoming)


def test_actual_stage_records_preserve_incomplete_and_interrupted(tmp_path):
    path=evidence(tmp_path);s=create_session(tmp_path/'viewer');case=tmp_path/'case.json';case.write_text('{}')
    recorder=RunRecorder(s,case,path.parent,'V1','thin wall')
    recorder({'stage':'mesh','level':1});recorder({'stage':'static','level':1})
    r=snapshot(s)['runs'][0]
    assert r['state']=='pending' and 'signal' not in r and r['events'][-1]['stage']=='static'
    recorder.fail('native process failed');assert snapshot(s)['runs'][0]['state']=='interrupted'
    recorder2=RunRecorder(s,case,path.parent);recorder2.finish()
    assert snapshot(s)['runs'][-1]['state']=='completed'


def test_display_registration_failure_preserves_numerical_output(tmp_path,monkeypatch):
    from simplecae import workbench
    path=evidence(tmp_path);s=create_session(tmp_path/'viewer');case=tmp_path/'case.json';case.write_text('{}')
    original=path.read_bytes();recorder=RunRecorder(s,case,path.parent)
    def fail(*_):raise ValueError('display budget exceeded')
    monkeypatch.setattr(workbench,'evidence_files',fail)
    assert 'display budget' in recorder.finish()
    assert path.read_bytes()==original and snapshot(s)['runs'][0]['state']=='unavailable'


def test_export_escapes_script_and_has_no_remote_dependency(tmp_path):
    s=create_session(tmp_path/'viewer','</script><script>alert(1)</script>');add_result(s,evidence(tmp_path))
    export_session(s);html=(s/'index.html').read_text('utf8')
    assert '<script>alert(1)' not in html and '\\u003c/script>' in html
    assert 'https://' not in html and (s/'workbench.js').exists() and (s/'workbench.css').exists()


def test_live_first_open_does_not_require_an_eager_offline_export(tmp_path,monkeypatch,capsys):
    from simplecae.cli import main
    import simplecae.workbench as wb
    session=tmp_path/'first-view'
    visited=[]
    def serve(path,port,open_browser):
        assert path==session and not (session/'index.html').exists()
        visited.append(path)
    monkeypatch.setattr(wb,'serve',serve)
    main(['view','--out',str(session),'--serve'])
    result=json.loads(capsys.readouterr().out)
    assert visited==[session] and result['viewer']==str(session/'index.html')
    assert (session/'index.html').is_file()


def test_http_scope_origins_and_feedback(tmp_path,monkeypatch):
    s=create_session(tmp_path/'viewer');add_result(s,evidence(tmp_path));server=make_server(s)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(method,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        c.request(method,path,body=body,headers=headers or {});r=c.getresponse();data=r.read();status=r.status;c.close();return status,data
    try:
        # Initial HTML is a small shell; loading it must not reconstruct all
        # fields. /state retains the source-bound validation and complete data.
        import simplecae.workbench as wb
        with monkeypatch.context() as context:
            context.setattr(wb,'snapshot',lambda *_:(_ for _ in ()).throw(AssertionError('eager fields')))
            status,page=request('GET','/')
        assert status==200 and b'"loading":true' in page and len(page)<30000
        assert b'"triangles":' not in page
        assert request('GET','/../viewer.json')[0]==404
        assert request('GET','/viewer.json')[0]==404
        assert request('GET','/state',headers={'Origin':'https://foreign.invalid'})[0]==403
        assert request('GET','/state',headers={'Host':'foreign.invalid'})[0]==403
        status,body=request('GET','/state');r=json.loads(body)['runs'][0];assert status==200
        note=json.dumps({'run_id':r['id'],'result_sha256':r['result_sha256'],'text':'review'})
        assert request('POST','/feedback',note)[0]==403
        headers={'X-SimpleCAE-Token':session_config(s)['feedback_token']}
        assert request('POST','/feedback',note,headers)[0]==200
        assert request('POST','/feedback','x'*20001,headers)[0]==400
        assert len(list((s/'feedback').glob('*.json')))==1
        assert request('POST','/execute','{}',headers)[0]==404
    finally:server.shutdown();server.server_close();thread.join()
