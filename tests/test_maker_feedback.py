import copy
import numpy as np
import pytest
from simplecae.signals import design_signal,compact_probes
from simplecae.reference_support import prepare,balanced,rigid_basis
from simplecae.probes import records_from_vectors
from simplecae.local_mesh import validate_refinements
from simplecae.schemas import check_contract

def test_invalid_gravity_never_verifies_missing_physics():
    case={'schema_version':'2.0','gravity':{'acceleration_m_s2':[0,0,-9.8]},'conditions':{}}
    signal=design_signal({'case':case,'status':'invalid','error':'native meshing failed'})
    assert signal['physical_conditions_verified'] is False
    assert signal['not_assessed'] and signal['bottleneck_margin'] is None

def test_empty_envelope_has_no_physical_evidence():
    signal=design_signal({'case':{},'analysis':'load_case_envelope','cases':[],'status':'invalid'})
    assert not signal['physical_conditions_verified'] and not signal['valid_for_comparison']

def test_probe_signal_retains_meaning_without_interpolation_arrays():
    assert compact_probes([{'name':'tip','point_mm':[1,2,3],'value_mm':.1,'weights':[1]*10000,'node_ids':list(range(10000))}])==[{'name':'tip','point_mm':[1,2,3],'value_mm':.1}]

def test_relative_length_is_rigid_motion_invariant():
    a=np.array([2.,3,4]);b=np.array([5.,6,7]);rotation=np.array([.02,-.03,.04]);translation=np.array([7.,8,9])
    specs=[{'name':'a','type':'point'},{'name':'b','type':'point'},{'name':'length','type':'relative_length','from_probe':'a','to_probe':'b','max_displacement_mm':.1}]
    records={'a':{'point_mm':a.tolist()},'b':{'point_mm':b.tolist()}}
    vectors={'a':translation+np.cross(rotation,a),'b':translation+np.cross(rotation,b)}
    result=records_from_vectors(specs,vectors,records)[-1]
    assert result['value_mm']<1e-12 and result['gauge_invariant']

def tet():
    xyz=np.array([[0.,0,0],[10,0,0],[0,10,0],[0,0,10]])
    xyz=np.vstack([xyz,*[(xyz[a]+xyz[b])/2 for a,b in ((0,1),(1,2),(2,0),(0,3),(1,3),(2,3))]])
    return {i+1:p for i,p in enumerate(xyz)},{1:list(range(1,11))}

def reference_case():
    return {'supports':[{'name':'A','point_mm':[1,1,1],'dofs':[1,2,3],'geometry_sha256':'a'*64},
        {'name':'B','point_mm':[1,4,1],'dofs':[1,3],'geometry_sha256':'a'*64},
        {'name':'C','point_mm':[1,1,4],'dofs':[1],'geometry_sha256':'a'*64}]}

def test_material_point_gauge_has_six_unique_dependents_and_rank():
    coords,tets=tet();case=reference_case();data=prepare(case,coords,tets,'a'*64)
    dependent={tuple(terms[0][:2]) for terms in data['equations']}
    assert len(dependent)==6 and data['rank']==6
    assert all(tuple(term[:2]) not in dependent for terms in data['equations'] for term in terms[1:])
    # Every interpolation actually maps onto the requested material location.
    for sample in data['samples']:
        assert np.allclose(sum(w*coords[n] for n,w in zip(sample['node_ids'],sample['weights'])),sample['point_mm'])

@pytest.mark.parametrize('kind',['hash','rank','outside'])
def test_bad_reference_points_rejected(kind):
    coords,tets=tet();case=reference_case()
    if kind=='hash':case['supports'][0]['geometry_sha256']='b'*64
    if kind=='rank':case['supports'][2]['point_mm']=case['supports'][1]['point_mm']
    if kind=='outside':case['supports'][0]['point_mm']=[20,20,20]
    with pytest.raises(ValueError):prepare(case,coords,tets,'a'*64)

def test_unbalanced_reference_wrench_including_gravity_rejected():
    coords,_=tet()
    with pytest.raises(ValueError,match='self-balanced'):balanced(coords,{1:np.array([0,0,-1.])},{'load_force_scale_n':10.})
    # A pure couple cannot be hidden by zero resultant force.
    with pytest.raises(ValueError,match='self-balanced'):balanced(coords,{1:np.array([0,1.,0]),2:np.array([0,-1.,0])},{'load_force_scale_n':10.})

@pytest.mark.parametrize('factor',[0,-.1,1.1])
def test_invalid_local_sizing_rejected(factor):
    with pytest.raises(ValueError):validate_refinements({'local_refinements':[{'name':'root','selector':{'type':'plane','axis':'x','position_mm':0},'size_factor':factor,'distance_mm':2}]})

def test_schema_error_is_concise_and_names_actual_branch():
    with pytest.raises(ValueError) as error:check_contract({'schema_version':'2.0','material':{'name':'Al','source':'assumed','youngs_modulus_mpa':-1,'poisson_ratio':.3},'unknown_typo':True})
    assert len(str(error.value))<1200 and 'youngs_modulus_mpa' in str(error.value)
