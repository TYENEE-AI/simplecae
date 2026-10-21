import copy
from pathlib import Path
import numpy as np
import pytest
from simplecae.assembly import compile_interfaces,load_assembly_case,clip_triangle,make_assembly_mesh
from simplecae.case import write_json
from simplecae.geometry import session,inspect_bodies,inspect
from simplecae.case import sha256


def patches(kind):
    coords={};bodies={};counter=0
    for name,cells in [('master',[(0,1,2),(0,2,3)]),('slave',[(0,1,3),(1,2,3)])]:
        points=[np.array([0.,-1,-1]),np.array([0.,1,-1]),np.array([0.,1,1]),np.array([0.,-1,1])]
        ids={};triangles=[]
        def node(p):
            nonlocal counter
            key=tuple(p)
            if key not in ids:counter+=1;coords[counter]=p;ids[key]=counter
            return ids[key]
        for a,b,c in cells:
            p=[points[a],points[b],points[c]]
            triangles.append([node(v) for v in p]+[node((p[i]+p[j])/2) for i,j in [(0,1),(1,2),(2,0)]])
        bodies[name]={'surfaces':{1:triangles},'local_geometry':{'geometry_sha256':'a'*64,'faces':[{'id':1,'type':'Plane','bbox_mm':[0,-1,-1,0,1,1]}]}}
    sel={'type':'face_ids','ids':[1],'geometry_sha256':'a'*64}
    c={'connections':[{'name':'joint','type':kind,'master':{'body':'master','selector':sel},'slave':{'body':'slave','selector':sel}}]}
    if kind=='linear_interface':c['connections'][0].update(normal=[1,0,0],normal_stiffness_n_mm3=1000.,tangential_stiffness_n_mm3=500.)
    return c,coords,bodies,counter


@pytest.mark.parametrize('kind',['bonded','linear_interface'])
def test_nonmatching_interfaces_preserve_all_rigid_motions(kind):
    c,coords,bodies,n=patches(kind);data=compile_interfaces(c,coords,bodies,set(),n,0)
    translation=np.array([1,2,3]);omega=np.array([.2,-.1,.3])
    displacements={node:translation+np.cross(omega,p) for node,p in coords.items()}
    displacements.update({int(node):np.zeros(3) for node in data['auxiliary_nodes']})
    assert all(abs(sum(coef*displacements[node][dof-1] for node,dof,coef in terms))<1e-10 for terms in data['equations'])
    assert data['reports'][0]['integrated_area_mm2']==pytest.approx(4.)
    if kind=='linear_interface':
        # A uniform normal jump transmits K_area*area*jump exactly.
        for node in {n for t in bodies['slave']['surfaces'][1] for n in t}:displacements[node]=np.array([.01,0,0])
        for node in {n for t in bodies['master']['surfaces'][1] for n in t}:displacements[node]=np.zeros(3)
        energy=0.
        for spring,terms in zip(data['springs'],data['equations']):
            relative=-sum(coef*displacements[node][dof-1] for node,dof,coef in terms[1:])
            energy+=.5*spring['stiffness_n_mm']*relative**2
        assert energy==pytest.approx(.5*1000*4*.01**2)


def test_dual_bond_uniform_traction_patch_consistency():
    c,coords,bodies,n=patches('bonded');data=compile_interfaces(c,coords,bodies,set(),n,0)
    loads={}
    for name in bodies:
        f={}
        for tri in bodies[name]['surfaces'][1]:
            p=np.array([coords[i] for i in tri[:3]]);area=np.linalg.norm(np.cross(p[1]-p[0],p[2]-p[0]))/2
            for i in tri[3:]:f[i]=f.get(i,0.)+area/3
        loads[name]=f
    transferred={n:0. for n in {n for t in bodies['master']['surfaces'][1] for n in t}}
    for terms in data['equations']:
        node,dof,_=terms[0]
        if dof!=1:continue
        for m,_,coefficient in terms[1:]:transferred[m]-=coefficient*loads['slave'].get(node,0.)
    for n,actual in transferred.items():assert actual==pytest.approx(loads['master'].get(n,0.),abs=1e-10)


def test_overlap_or_offset_and_unverified_paths_are_rejected(tmp_path):
    c,coords,bodies,n=patches('bonded')
    for node in {n for t in bodies['slave']['surfaces'][1] for n in t}:coords[node]=coords[node]+[.01,0,0]
    with pytest.raises(ValueError,match='project|coincident'):compile_interfaces(c,coords,bodies,set(),n,0)
    root=Path(__file__).resolve().parents[1];case=__import__('json').loads((root/'examples/assemblies/bonded.case.json').read_text())
    for body in case['bodies']:body['model']['path']=str(root/'examples/assemblies/half-bar.step')
    case['connections']=[];path=tmp_path/'case.json';write_json(path,case)
    with pytest.raises(ValueError,match='connections'):load_assembly_case(path)


def test_bonded_slave_support_conflict_rejected():
    c,coords,bodies,n=patches('bonded');fixed={bodies['slave']['surfaces'][1][0][0]}
    with pytest.raises(ValueError,match='slave node is fixed'):compile_interfaces(c,coords,bodies,fixed,n,0)


def test_triangle_segmentation_has_correct_intersection_area():
    polygon=np.array(clip_triangle([[0,0],[2,0],[0,2]],[[0,0],[2,0],[2,2]]))
    area=abs(sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(polygon,np.roll(polygon,-1,axis=0))))/2
    assert area==pytest.approx(1.)


def test_multibody_step_requires_current_explicit_solid_selection(tmp_path):
    p=tmp_path/'assembly.step'
    with session() as g:
        g.model.occ.addBox(0,0,0,10,10,10);g.model.occ.addBox(10,0,0,20,10,10)
        g.model.occ.synchronize();g.write(str(p))
    inventory=inspect_bodies(p,tmp_path/'all.json')
    assert len(inventory['bodies'])==2
    model={'path':str(p),'solid_id':{'id':2,'geometry_sha256':sha256(p)}}
    info=inspect(p,tmp_path/'selected.json',model)
    assert info['solid_count']==1 and info['volume_mm3']==pytest.approx(2000)
    assert info['center_of_mass_mm']==pytest.approx([20,5,5])
    model['solid_id']['geometry_sha256']='0'*64
    with pytest.raises(ValueError,match='different STEP hash'):inspect(p,tmp_path/'stale.json',model)


@pytest.mark.parametrize('mesh_body',[False,True])
def test_penetration_rejected_before_connection_or_solver(tmp_path,mesh_body):
    import json,trimesh
    root=Path(__file__).resolve().parents[1]
    c=json.loads((root/'examples/assemblies/bonded.case.json').read_text())
    for body in c['bodies']:body['model']['path']=str(root/'examples/assemblies/half-bar.step')
    c['bodies'][1]['placement']['translation_mm']=[25,0,0]
    if mesh_body:
        model=trimesh.creation.box(extents=[50,10,10]);model.apply_translation([25,0,0]);p=tmp_path/'half.stl';model.export(p)
        c['bodies'][1]['model']={'path':str(p),'units':'mm'}
    path=tmp_path/'case.json';write_json(path,c);case=load_assembly_case(path)
    out=tmp_path/'mesh';out.mkdir()
    with pytest.raises(ValueError,match='penetrate'):make_assembly_mesh(case,5,out)
