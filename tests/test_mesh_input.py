import json
from pathlib import Path
import numpy as np
import pytest
import trimesh
from simplecae.mesh_input import load_surface,triangle_overlap,check_self_intersection
from simplecae.geometry import inspect,make_mesh
from simplecae.benchmarks import bar_case


def save_box(tmp_path,suffix='.glb',transform=None):
    mesh=trimesh.creation.box(extents=[.1,.01,.01] if suffix=='.glb' else [100,10,10])
    scene=trimesh.Scene()
    scene.add_geometry(mesh,node_name='link',transform=transform)
    path=tmp_path/('box'+suffix)
    if suffix=='.glb': path.write_bytes(scene.export(file_type='glb'))
    else: mesh.export(path)
    return path


def test_glb_units_axis_and_scene_transform(tmp_path):
    t=np.eye(4);t[:3,3]=[.05,.03,.02]
    p=save_box(tmp_path,transform=t)
    mesh,record=load_surface({'path':str(p)})
    assert np.allclose(mesh.bounds,[[0,-25,25],[100,-15,35]],atol=1e-5)
    assert mesh.volume==pytest.approx(10000,rel=1e-6)
    assert record['source_up_axis']=='y' and record['self_intersection_check']['passed']


def test_stl_requires_units_and_closed_surface(tmp_path):
    p=save_box(tmp_path,'.stl')
    with pytest.raises(ValueError,match='units'): load_surface({'path':str(p)})
    mesh,_=load_surface({'path':str(p),'units':'mm'})
    assert mesh.volume==pytest.approx(10000)
    mesh.faces=mesh.faces[:-1]
    mesh.export(p)
    with pytest.raises(ValueError,match='closed'): load_surface({'path':str(p),'units':'mm'})


def test_multiscene_requires_explicit_occurrence(tmp_path):
    s=trimesh.Scene()
    for i in range(2):
        t=np.eye(4);t[0,3]=i*.2
        s.add_geometry(trimesh.creation.box(extents=[.1,.01,.01]),node_name=f'link{i}',transform=t)
    p=tmp_path/'assembly.glb';p.write_bytes(s.export(file_type='glb'))
    with pytest.raises(ValueError,match='occurrences'): load_surface({'path':str(p)})
    mesh,_=load_surface({'path':str(p),'scene_node':'link1'})
    assert mesh.bounds[0,0]==pytest.approx(150,abs=1e-4)


def test_triangle_intersection_including_coplanar():
    a=np.array([[0,0,0],[2,0,0],[0,2,0]],float)
    assert triangle_overlap(a,a+[.1,.1,0],1e-10)
    assert not triangle_overlap(a,a+[3,3,0],1e-10)
    assert triangle_overlap(a,np.array([[.5,.5,-1],[.5,.5,1],[1,.5,0]]),1e-10)
    assert not triangle_overlap(a,a+[0,0,1],1e-10)


def test_surface_intersection_detected_and_budget_explicit():
    a=np.array([[0,0,0],[2,0,0],[0,2,0],[.5,.5,-1],[.5,.5,1],[1,.5,0]],float)
    mesh=trimesh.Trimesh(vertices=a,faces=[[0,1,2],[3,4,5]],process=False)
    with pytest.raises(ValueError,match='intersecting'): check_self_intersection(mesh)
    with pytest.raises(ValueError,match='budget'): check_self_intersection(trimesh.creation.box(),pair_budget=0)


def test_discrete_surface_inventory_retains_planar_regions(tmp_path):
    p=save_box(tmp_path,'.stl')
    info=inspect(p,tmp_path/'faces.json',{'path':str(p),'units':'mm'})
    assert info['volume_mm3']==pytest.approx(10000)
    assert len(info['faces'])>=6
    assert all(f['type']=='Plane' for f in info['faces'])
    assert sum(f['area_mm2'] for f in info['faces'])==pytest.approx(4200)


def test_discrete_mesh_refinement_changes_volume_mesh(tmp_path):
    p=save_box(tmp_path,'.stl')
    c=bar_case('mesh',[0,0,-100],[5,4,3]);c['schema_version']='2.0'
    c['model']={'path':str(p),'units':'mm'}
    c['supports'][0]['selector']['position_mm']=-50
    c['loads'][0]['selector']['position_mm']=50
    counts=[]
    for i,h in enumerate([5,4,3]):
        out=tmp_path/f'level-{i}';out.mkdir();mesh=make_mesh(c,h,out)
        counts.append(mesh[-1]['element_count'])
        assert mesh[-1]['cad_mesh_volume_relative_error']<1e-6
        assert np.allclose(mesh[-1]['applied_force_n'],[0,0,-100])
    assert counts[0]<counts[1]<counts[2]
