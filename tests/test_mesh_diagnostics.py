from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from simplecae.mesh_diagnostics import native_mesh_call,high_order_quality,element_quality,rejected_high_order_mesh


def test_reported_native_error_rejected_and_policy_restored(tmp_path):
    # An operation can return normally after the native logger reports failure.
    # That result must never progress to a solver call.
    import gmsh
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal',0)
        original=gmsh.option.getNumber('General.AbortOnError')
        with pytest.raises(RuntimeError,match='mesh rejected.*critical value'):
            native_mesh_call(gmsh,'optimizer',lambda:gmsh.logger.write('Failed to reach critical value: synthetic regression','error'),tmp_path)
        assert gmsh.option.getNumber('General.AbortOnError')==original
        assert 'synthetic regression' in (tmp_path/'mesh-native.log').read_text()
        assert native_mesh_call(gmsh,'ok',lambda:42,tmp_path)==42
    finally:gmsh.finalize()


def test_python_failure_also_restores_native_policy(tmp_path):
    import gmsh
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal',0)
        original=gmsh.option.getNumber('General.AbortOnError')
        def fail():raise ValueError('cannot generate')
        with pytest.raises(ValueError,match='cannot generate'):native_mesh_call(gmsh,'generate',fail,tmp_path)
        assert gmsh.option.getNumber('General.AbortOnError')==original
        assert '[generate]' in (tmp_path/'mesh-native.log').read_text()
    finally:gmsh.finalize()


def test_inversion_between_quadrature_samples_is_rejected():
    # Positive sampled integration determinants do not establish positive
    # determinants everywhere in a curved quadratic tetrahedron.
    g=SimpleNamespace(model=SimpleNamespace(mesh=SimpleNamespace(getElementQualities=lambda ids,name:[.5] if name=='minSICN' else [-.01])))
    with pytest.raises(ValueError,match='adaptively checked'):high_order_quality(g,[71])


def test_peak_shape_diagnostic_is_bound_by_element_id(tmp_path):
    np.savez(tmp_path/'mesh.npz',element_ids=[77,42],element_min_sicn=[.5,.08],element_min_det_jac=[2.,.03])
    assert element_quality(tmp_path,42)['minimum_signed_inverse_condition_number']==pytest.approx(.08)
    with pytest.raises(ValueError,match='peak element missing'):element_quality(tmp_path,99)


def test_rejected_element_locations_keep_raw_ids_and_boundary_adjacency(tmp_path):
    import json
    xyz=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1],
                  [.5,0,0],[.5,.5,0],[0,.5,0],[0,0,.5],[.5,0,.5],[0,.5,.5]])
    def nodes(dim=-1, tag=-1, includeBoundary=False):
        if dim==2:return np.array([1,2,3,5,6,7]),[],[]
        return np.arange(1,11),xyz.ravel(),[]
    mesh=SimpleNamespace(
        getElementType=lambda *_:11,
        getElementsByType=lambda *_:(np.array([73]),np.arange(1,11)),
        getElementQualities=lambda ids,name:np.array([-.2 if name=="minDetJac" else -.1]),
        getNodes=nodes)
    record=rejected_high_order_mesh(SimpleNamespace(model=SimpleNamespace(mesh=mesh)),
        {"geometry_sha256":"a"*64,"faces":[{"id":9,"type":"Cylinder"}]},6,tmp_path)
    assert record["status"]=="rejected" and record["rejected_element_count"]==1
    bad=record["rejected_elements"][0]
    assert bad["element"]==73 and bad["minimum_adaptive_jacobian"]==-.2
    assert bad["adjacent_face_ids"]==[9] and bad["corner_centroid_mm"]==[.25,.25,.25]
    assert json.loads((tmp_path/"mesh-diagnostic.json").read_text())==record


def test_reported_native_failure_finishes_viewer_invalid_without_solver(tmp_path,monkeypatch):
    import gmsh
    from simplecae import workflow
    from simplecae.case import load_case,write_json
    from simplecae.workbench import create_session,RunRecorder,snapshot
    source=Path(__file__).resolve().parents[1]/'examples/integration/simplecad-beam-step.case.json'
    case=load_case(source);path=tmp_path/'case.json';write_json(path,case)
    session=create_session(tmp_path/'viewer');out=tmp_path/'analysis'
    recorder=RunRecorder(session,path,out)
    monkeypatch.setattr(workflow,'find_ccx',lambda _:Path('unused-solver'))
    def forbidden(*_):raise AssertionError('solver must not run after mesher Error')
    monkeypatch.setattr(workflow,'execute',forbidden)
    def failing_mesh(c,h,directory):
        gmsh.initialize()
        try:
            gmsh.option.setNumber('General.Terminal',0)
            return native_mesh_call(gmsh,'high_order_optimize',lambda:gmsh.logger.write('synthetic native optimizer failure','error'),directory)
        finally:gmsh.finalize()
    result=workflow.analyze(path,out,mesh_factory=failing_mesh,preview=False,progress=recorder)
    recorder.finish()
    record=snapshot(session)['runs'][0]
    assert result['status']=='invalid' and result['levels']==[]
    assert 'mesh rejected' in result['error']
    assert record['state']=='completed' and record['status']=='invalid'
    assert record['datasets']==[] and record['signal']['whole_installation_rating_available'] is False
    assert (out/'level-01/mesh-native.log').is_file()
