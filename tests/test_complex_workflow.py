"""Regressions discovered by curved parts, directional guides and cost advice."""
from pathlib import Path
import numpy as np
import pytest
from simplecae.case import load_case,write_json,sha256
from simplecae.constraints import check_shared_face_load

ROOT=Path(__file__).resolve().parents[1]


def assembly_reference():
    import json
    case=json.loads((ROOT/'examples/assemblies/bonded.case.json').read_text())
    for body in case['bodies']:body['model']['path']=str(ROOT/'examples/assemblies/half-bar.step')
    return case


def test_body_mesh_multiplier_preserves_physical_advice_size_and_cost(tmp_path):
    from simplecae.advice import advise
    case=assembly_reference()
    for body in case['bodies']:body['mesh_size_factor']=2.
    case['mesh'].update(sizes_mm=[4.,3.2,2.],max_elements=100000)
    write_json(tmp_path/'case.json',case)
    write_json(tmp_path/'mesh-diagnostic.json',{'geometry_sha256':sha256(Path(case['bodies'][0]['model']['path'])),
        'mesh_size_mm':8.,'element_count':100,'adjacent_cad_faces':[
        {'id':1,'type':'Cylinder','bbox_mm':[0,0,0,8,8,8]}]})
    advice=advise(tmp_path/'case.json',tmp_path,tmp_path/'advice.json')
    assert not any(a['kind']=='element_budget' for a in advice['actions'])
    for action in advice['actions']:
        assert action['kind']=='local_refinement'
        assert action['proposed_entry']['distance_mm']==8.
        assert action['sizing_estimate']['geometry_requested_factor']==.25
        assert action['sizing_estimate']['observed_finest_element_estimate']==800.
    case['mesh']['max_elements']=2000
    write_json(tmp_path/'case.json',case)
    bounded=advise(tmp_path/'case.json',tmp_path,tmp_path/'bounded.json')
    # Both explicitly meshed bodies consume the shared cap, even when they
    # reuse the same CAD hash: 2 * 800 * 1.5 planning headroom = 2400.
    assert next(a for a in bounded['actions'] if a['kind']=='element_budget')['proposed_max_elements']==2400
    assert all(a['sizing_estimate']['budget_limited'] for a in bounded['actions'] if 'sizing_estimate' in a)


def test_rotated_assembly_guide_uses_world_support_dofs(tmp_path):
    from simplecae.assembly import load_assembly_case,make_assembly_mesh
    case=assembly_reference()
    for i,body in enumerate(case['bodies']):
        body['placement']={'translation_mm':[0,0,-50*i],'rpy_rad':[0,np.pi/2,0]}
    case['supports'].append({'name':'guide','body':'right','selector':case['loads'][0]['selector'],'dofs':[1,2]})
    case['loads'][0]['total_force_n']=[0,0,-10]
    write_json(tmp_path/'case.json',case)
    out=tmp_path/'mesh';out.mkdir()
    _,_,_,forces,_=make_assembly_mesh(load_assembly_case(tmp_path/'case.json'),5.,out)
    assert np.allclose(sum(forces.values()),[0,0,-10],rtol=0,atol=1e-10)


def test_shared_face_load_uses_actual_support_axes_and_does_not_discard_force():
    # A body is rotated 90 degrees about Y: local X becomes world -Z.
    rotation=np.array([[0,0,1],[0,1,0],[-1,0,0.]])
    force={1:np.array([10.,0,0])};before=force[1].copy()
    check_shared_face_load(force,{1:{1,2}},{1},rotation)
    assert np.array_equal(force[1],before)
    with pytest.raises(ValueError,match='constrained DOF'):
        check_shared_face_load(force,{1:{1,2}},{1})
    # Equal/opposite constrained forces have zero resultant but a real couple.
    with pytest.raises(ValueError,match='constrained DOF'):
        check_shared_face_load({1:np.array([1.,0,0]),2:np.array([-1.,0,0])},{1:{1},2:{1}},{1,2})


def test_directional_guide_and_free_direction_load_share_real_mesh_face(tmp_path):
    from simplecae.geometry import make_mesh
    case=load_case(ROOT/'examples/integration/simplecad-beam-step.case.json')
    tip=case['loads'][0]['selector']
    case['supports'].append({'name':'tip_guide','selector':tip,'dofs':[1,2]})
    case['loads'][0]['total_force_n']=[0,0,-10]
    out=tmp_path/'valid';out.mkdir()
    _,_,_,forces,meta=make_mesh(case,8.,out)
    assert np.allclose(sum(forces.values()),[0,0,-10],rtol=0,atol=1e-10)
    assert set(meta['support_faces']['tip_guide'])==set(meta['loads'][0]['face_ids'])
    case['loads'][0]['total_force_n']=[10,0,0]
    out=tmp_path/'constrained';out.mkdir()
    with pytest.raises(ValueError,match='constrained DOF'):make_mesh(case,8.,out)
    case['supports'][-1]['dofs']=[1,2,3]
    out=tmp_path/'clamped';out.mkdir()
    with pytest.raises(ValueError,match='fully constrained'):make_mesh(case,8.,out)


def test_tiny_trimmed_extent_cannot_drive_unbounded_refinement_proposal(tmp_path):
    from simplecae.advice import advise
    from simplecae.local_mesh import validate_refinements
    case=load_case(ROOT/'examples/integration/simplecad-beam-step.case.json')
    case['mesh'].update(sizes_mm=[3.,2.4,1.92],max_elements=140000)
    write_json(tmp_path/'case.json',case)
    write_json(tmp_path/'mesh-diagnostic.json',{'geometry_sha256':sha256(Path(case['model']['path'])),
       'mesh_size_mm':3.,'element_count':3246,'adjacent_cad_faces':[
       {'id':1,'type':'Cylinder','bbox_mm':[0,0,0,.2858,18,3]}]})
    advice=advise(tmp_path/'case.json',tmp_path,tmp_path/'advice.json')
    action=next(a for a in advice['actions'] if a['kind']=='local_refinement')
    proposal=action['proposed_entry'];estimate=action['sizing_estimate']
    validate_refinements({'local_refinements':[proposal]})
    assert estimate['budget_limited']
    assert estimate['geometry_requested_factor']<.025<proposal['size_factor']<1
    assert estimate['observed_finest_element_estimate']/proposal['size_factor']**3*1.25<=140000*(1+1e-12)
    assert not advice['automatic_retry'] and not advice['input_modified']


def test_optimizer_failure_without_inverted_elements_has_explicit_broad_trial(tmp_path):
    from simplecae.geometry import session
    from simplecae.advice import advise
    model=tmp_path/'round_bar.step'
    with session() as g:
        g.model.occ.addCylinder(0,0,0,100,0,0,5);g.model.occ.synchronize();g.write(str(model))
    case=load_case(ROOT/'examples/integration/simplecad-beam-step.case.json')
    case['model']={'path':str(model)}
    write_json(tmp_path/'case.json',case)
    write_json(tmp_path/'mesh-diagnostic.json',{'stage':'high_order_optimize','status':'rejected',
       'geometry_sha256':sha256(model),'mesh_size_mm':4.,'element_count':100,
       'rejected_element_count':0,'adjacent_cad_faces':[]})
    advice=advise(tmp_path/'case.json',tmp_path,tmp_path/'advice.json')
    action=next(a for a in advice['actions'] if a['kind']=='local_refinement')
    assert 'Unlocalized' in action['location_basis']
    assert len(action['proposed_entry']['selector']['ids'])==1
    assert not advice['evidence_numerically_qualified']
