"""Independent geometric and conservative-transfer guards, not product proof."""
from pathlib import Path
import copy
import numpy as np
import pytest
from simplecae.geometry import session,inventory
from simplecae.contact_footprint import cad_coverage,contained_samples
from simplecae.assembly import load_assembly_case,SurfaceProjector

ROOT=Path(__file__).resolve().parents[1]

def make_disk_body(path,outer,inner=0):
    with session() as g:
        solid=g.model.occ.addCylinder(0,0,-1,0,0,1,outer)
        if inner:
            hole=g.model.occ.addCylinder(0,0,-2,0,0,3,inner)
            g.model.occ.cut([(3,solid)],[(3,hole)])
        g.model.occ.synchronize();g.write(str(path))
        info=inventory(g,path)
    return {'brep':str(path),'local_geometry':info}

@pytest.mark.parametrize('hole,slave_inner,offset,accepted',[(0,0,0,True),(1,0,0,False),(1,1.5,0,True),(0,0,5,False)])
def test_exact_trimmed_face_containment_detects_holes_and_misplacement(tmp_path,hole,slave_inner,offset,accepted):
    data={'m':make_disk_body(tmp_path/'master.brep',4,hole),'s':make_disk_body(tmp_path/'slave.brep',2,slave_inner)}
    spec={r:{'body':b,'selector':{'type':'plane','axis':'z','position_mm':0}} for r,b in [('master','m'),('slave','s')]}
    bodies=[{'name':'m'},{'name':'s','placement':{'translation_mm':[offset,0,0],'rpy_rad':[0,0,0]}}]
    if accepted:
        report=cad_coverage(spec,bodies,data,[0,0,1],0)
        assert report['uncovered_area_mm2']<=report['area_tolerance_mm2']
        assert report['slave_cad_area_mm2']==pytest.approx(np.pi*(4-slave_inner**2))
    else:
        with pytest.raises(ValueError,match='not contained'):cad_coverage(spec,bodies,data,[0,0,1],0)

def test_contained_contact_interpolation_reproduces_curved_p2_rigid_motion():
    coords={i+1:p for i,p in enumerate(np.array([[0,0,0],[1,0,0],[0,1,0],[.5,-.08,0],[.5,.5,0],[0,.5,0]],float))}
    tri=list(coords);p=np.array(list(coords.values()));patch={'triangles':[tri],'points':p}
    samples=list(contained_samples(patch,patch,coords,100,1e-8))
    assert len(samples)==7 and sum(s[-2] for s in samples)>.5
    omega=np.array([.3,-.2,.4]);translation=np.array([2,3,4])
    for sn,sw,mn,mw,point,measure,_ in samples:
        u=lambda ns,w:sum((v*(translation+np.cross(omega,coords[n])) for n,v in zip(ns,w)),np.zeros(3))
        assert np.allclose(u(sn,sw),u(mn,mw))
    with pytest.raises(ValueError,match='budget'):list(contained_samples(patch,patch,coords,1,1e-8))
    shifted={n:v+np.array([10,0,0]) for n,v in coords.items()}
    with pytest.raises(ValueError,match='project'):list(contained_samples(patch,{'triangles':[tri],'points':np.array(list(shifted.values()))},coords,100,1e-8))

def test_new_contact_input_is_public_api_compatible(tmp_path):
    from simplecae.api import check_case
    import json
    c=load_assembly_case(ROOT/'examples/joints/bolt-locked.case.json')
    c['connections'][0]['footprint']='slave_within_master'
    c['bodies'][0]['local_refinements']=[]
    path=tmp_path/'case.json';path.write_text(json.dumps(c),encoding='utf8')
    check_case(path)
    for damage in ('unknown','bonded'):
        broken=copy.deepcopy(c)
        if damage=='unknown':broken['connections'][0]['footprint']='partial_magic'
        else:broken['connections'][0]['type']='bonded'
        path.write_text(json.dumps(broken),encoding='utf8')
        with pytest.raises(ValueError):check_case(path)

def test_curved_bolt_port_keeps_declared_cad_resultant_and_rejects_nonplanarity():
    from simplecae.bolts import attachment
    coords={i+1:p for i,p in enumerate(np.array([[0,0,0],[1,0,0],[0,1,0],[.5,-.08,0],[.5,.5,0],[0,.5,0]],float))}
    center=np.array([.3,.3,0.]);face={'id':1,'type':'Plane','area_mm2':.55,'centroid_mm':center.tolist(),'bbox_mm':[0,-.08,0,1,1,0]}
    body={'local_geometry':{'geometry_sha256':'a'*64,'faces':[face]},'surfaces':{1:[list(coords)]}}
    side={'body':'plate','selector':{'type':'face_ids','ids':[1],'geometry_sha256':'a'*64}}
    port=attachment(side,coords,{'plate':body})
    assert np.allclose(port['center'],center,atol=1e-12) and sum(port['weights'].values())==pytest.approx(1)
    resultant=sum((w*coords[n] for n,w in port['weights'].items()),np.zeros(3))
    assert np.allclose(resultant,center,atol=1e-12)
    coords[4][2]=.01
    with pytest.raises(ValueError,match='coplanar'):attachment(side,coords,{'plate':body})
