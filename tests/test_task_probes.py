import copy
import numpy as np
import pytest
from simplecae.probes import PointSampler,evaluate_probes,validate_probes,convergence
from simplecae.loads import tetra10_basis
from simplecae.benchmarks import bar_case
from simplecae.assessment import assess
from simplecae.case import validate_case
from simplecae.schemas import check_contract
from simplecae.signals import structural_contract,digest,design_signal

EDGES=((0,1),(1,2),(2,0),(0,3),(1,3),(2,3))
def tetra(scale=1.):
    corners=np.array([[0,0,0],[scale,0,0],[0,scale,0],[0,0,scale]],dtype=float)
    xyz=np.vstack([corners]+[(corners[i]+corners[j])[None,:]/2 for i,j in EDGES])
    return {i+1:p for i,p in enumerate(xyz)},{17:list(range(1,11))}
def polynomial(p):
    x,y,z=p;return np.array([x*x+y*z,-2*x*y,z*z])

def test_quadratic_probe_recovers_a_non_nodal_displacement_and_relative_projection():
    xyz,elements=tetra();c={'schema_version':'2.0','probes':[
        {'name':'a','type':'point','point_mm':[.1,.1,.1]},
        {'name':'b','type':'point','point_mm':[.2,.1,.1]},
        {'name':'gap','type':'relative','from_probe':'a','to_probe':'b','direction':[1,0,0],'max_displacement_mm':.04}]}
    fields={'displacements':{n:polynomial(p) for n,p in xyz.items()}}
    a,b,gap=evaluate_probes(c,(xyz,elements,[],{},{}),fields)
    assert np.allclose(a['displacement_vector_mm'],polynomial([.1,.1,.1]))
    assert np.allclose(b['displacement_vector_mm'],polynomial([.2,.1,.1]))
    assert gap['signed_projection_mm']==pytest.approx(.03) and gap['utilization']==pytest.approx(.75)
    assert not np.any(np.all(np.isclose(np.array(list(xyz.values())),[.1,.1,.1]),axis=1))

def test_curved_quadratic_geometry_is_inverted_without_corner_linearization():
    xyz,elements=tetra();xyz[5]=xyz[5]+[0,.15,.05]
    q=np.array([.2,.3,.1]);n=tetra10_basis(q[None,:])[0];point=n@np.array(list(xyz.values()))
    sample=PointSampler(xyz,elements).locate(point)
    assert np.allclose(sample['natural_coordinates'],q,atol=1e-8)
    assert sample['mapping_residual_mm']<1e-9
    u={i:np.array([2*p[0]-p[1],p[2],0]) for i,p in xyz.items()}
    actual=sum(w*u[i] for i,w in zip(sample['node_ids'],sample['weights']))
    assert np.allclose(actual,[2*point[0]-point[1],point[2],0])


def test_probe_mapping_rejects_inverted_isoparametric_orientation():
    xyz,elements=tetra();xyz={n:point[[1,0,2]] for n,point in xyz.items()}
    with pytest.raises(ValueError,match='non-positive'):PointSampler(xyz,elements).locate([.1,.1,.1])

def test_surface_average_integrates_the_field_instead_of_sampling_an_empty_centroid(tmp_path):
    xyz={1:np.array([0.,0,0]),2:np.array([2.,0,0]),3:np.array([0.,2,0]),
         4:np.array([1.,0,0]),5:np.array([1.,1,0]),6:np.array([0.,1,0])}
    np.savez(tmp_path/'mesh.npz',surface_tri6=np.array([[1,2,3,4,5,6]]),surface_face_ids=np.array([9]))
    meta={'geometry':{'geometry_sha256':'a'*64,'faces':[{'id':9,'type':'Plane','bbox_mm':[0,0,0,2,2,0]}]}}
    c={'schema_version':'2.0','probes':[{'name':'face','type':'surface_average','selector':{'type':'plane','axis':'z','position_mm':0},'max_displacement_mm':1.5}]}
    f={'_source_directory':str(tmp_path),'displacements':{n:np.array([0,0,p[0]**2+p[1]**2]) for n,p in xyz.items()}}
    p=evaluate_probes(c,(xyz,{},[],{},meta),f)[0]
    assert p['area_mm2']==pytest.approx(2.) and p['value_mm']==pytest.approx(4/3)
    assert p['value_mm']!=pytest.approx(8/9) # quadratic field at the area centroid
    assert p['point_mm']==pytest.approx([2/3,2/3,0])

def test_outside_contact_pad_is_not_silently_snapped_to_the_metal():
    xyz,elements=tetra()
    with pytest.raises(ValueError,match='outside'):PointSampler(xyz,elements).locate([-0.01,0,0])

def test_assembly_probe_uses_declared_body_frame_and_global_displacement_direction():
    from simplecae.assembly import rotation_rpy
    xyz,elements=tetra();r=rotation_rpy([0,0,np.pi/2]);translation=np.array([5,2,-1])
    world={n:r@p+translation for n,p in xyz.items()}
    c={'schema_version':'assembly-1.0','bodies':[{'name':'jaw','placement':{'rpy_rad':[0,0,np.pi/2],'translation_mm':translation.tolist()}}],
       'probes':[{'name':'grasp','type':'point','body':'jaw','point_mm':[.2,.1,.1],'direction':[0,1,0]}]}
    fields={'displacements':{n:r@polynomial(p) for n,p in xyz.items()}}
    meta={'body_reports':[{'name':'jaw','material_id':'M0'}],'element_material':{'17':'M0'}}
    p=evaluate_probes(c,(world,elements,[],{},meta),fields)[0]
    assert np.allclose(p['point_mm'],r@np.array([.2,.1,.1])+translation)
    assert p['signed_projection_mm']==pytest.approx(.05)

def test_probe_sign_flip_does_not_fake_projection_convergence_and_zero_is_stable():
    p={'name':'p','signed_projection_mm':.01,'displacement_norm_mm':.01,'absolute_convergence_tolerance_mm':1e-9}
    q=dict(p,signed_projection_mm=-.01)
    assert not convergence([p],[q],.05)['p']['converged']
    z=dict(p,signed_projection_mm=0,displacement_norm_mm=0)
    assert convergence([z],[z],.05)['p']['converged']

def test_named_probe_only_stiffness_limit_controls_conditional_scale_and_task_contract():
    xyz,elements=tetra(100);c=bar_case('unused',[100,0,0],[5,4,3]);c['schema_version']='2.0';c['criteria']['max_displacement_mm']=None
    c['probes']=[{'name':'grasp','type':'point','point_mm':[80,5,5],'direction':[1,0,0],'max_displacement_mm':.016}]
    validate_case(c);check_contract(c)
    fields={'displacements':{n:np.array([p[0]*.0001,0,0]) for n,p in xyz.items()},
            'stresses':{(17,1):np.array([1.,0,0,0,0,0])},'strains':{(17,1):np.array([.00001,0,0,0,0,0])}}
    probes=evaluate_probes(c,(xyz,elements,[],{},{}),fields)
    r={'max_displacement_mm':.01,'max_von_mises_mpa':1.,'max_strain_norm':.00001,'minimum_bbox_extent_mm':100,
       'force_balance_relative_error':0.,'moment_balance_relative_error':0.,'probes':probes}
    levels=[{'results':copy.deepcopy(r)} for _ in range(3)]
    a=assess(c,levels,[(fields,None)]*3)
    assert a['status']=='pass_under_stated_model' and a['stiffness_utilization']==pytest.approx(.5)
    assert a['conditional_body_limit']['load_pattern_scale_factor']==pytest.approx(2.)
    changed=copy.deepcopy(c);changed['probes'][0]['point_mm'][0]=70
    assert digest(structural_contract(c))!=digest(structural_contract(changed))

@pytest.mark.parametrize('probes',[
    [{'name':'p','type':'point','point_mm':[0,0,0],'direction':[2,0,0]}],
    [{'name':'gap','type':'relative','from_probe':'missing','to_probe':'missing'}],
    [{'name':'p','type':'point','point_mm':[0,0,0],'body':'invented'}]])
def test_misleading_probe_declarations_are_rejected(probes):
    with pytest.raises(ValueError):validate_probes({'schema_version':'2.0','probes':probes})
