import copy,json
from pathlib import Path
import numpy as np
import pytest
from simplecae.case import write_json
from simplecae.robot_probes import measure,component_specs,affine_displacement_limit
from simplecae.robot import transform
from simplecae.probes import convergence

def components(tmp_path):
    r=transform([0,0,0],[0,0,np.pi/2]);answer=[]
    for link,name,fixed,full in [('fixed','a',.001,.001),('moving','b',.011,.031)]:
        levels=[]
        for i in range(3):
            folder=tmp_path/link/str(i);folder.mkdir(parents=True)
            def probe(u):return {'name':'robot-probe:'+name,'element':4,'displacement_vector_mm':[u,0,0]}
            write_json(folder/'fixed-results.json',{'results':{'probes':[probe(fixed)]}})
            levels.append({'directory':str(folder),'mesh':{'fixed_nodal_forces':{'1':[1,0,0]}},'results':{'probes':[probe(full)]}})
        answer.append({'case':{'mesh':{}},'levels':levels,'robot_load_transfer':{'link':link,'world_from_component':r.tolist()}})
    case={'schema_version':'robot-1.0','probes':[{'name':'a','type':'point','link':'fixed','point_m':[0,0,0]},
         {'name':'b','type':'point','link':'moving','point_m':[0,0,0]},
         {'name':'gap','type':'relative','from_probe':'a','to_probe':'b','direction':[0,1,0],'max_displacement_mm':.05}]}
    kin={'frames':{'fixed':transform([1,2,3],[0,0,np.pi/2]),'moving':transform([1.1,2,3],[0,0,np.pi/2])}}
    return case,kin,answer

def test_relative_task_displacement_rotates_fields_and_keeps_fixed_loads_unscaled(tmp_path):
    c,k,fem=components(tmp_path);r=measure(c,k,fem);p={p['name']:p for p in r['probes']}
    assert r['status']=='pass_under_stated_model'
    assert p['gap']['signed_projection_mm']==pytest.approx(.03)
    assert p['gap']['utilization']==pytest.approx(.6)
    assert p['a']['point_world_m']==[1,2,3]
    assert r['payload_scale_limit']==pytest.approx(2.)
    assert r['fixed_loads_alone_pass']

def test_source_field_or_requested_link_is_not_replaced_by_zero_displacement(tmp_path):
    c,k,fem=components(tmp_path)
    with pytest.raises(ValueError,match='explicit component FEM'):measure(c,k,fem[:1])
    fem[1]['levels'][0]['results']['probes']=[]
    with pytest.raises(ValueError,match='field is missing'):measure(c,k,fem)

def test_component_point_frame_mapping_and_required_relative_dependency():
    case={'probes':[{'name':'a','type':'point','link':'moving','point_m':[.01,.002,.003],'direction':[1,0,0]},
                   {'name':'b','type':'point','link':'fixed','point_m':[0,0,0]},
                   {'name':'gap','type':'relative','from_probe':'a','to_probe':'b','max_displacement_mm':.1}]}
    component={'link':'moving','link_from_component':{'xyz_m':[.01,0,0],'rpy_rad':[0,0,np.pi/2]}}
    p=component_specs(case,component,transform([0,0,0],[0,0,np.pi/2]))[0]
    assert np.allclose(p['point_mm'],[2,0,3]) and np.allclose(p['direction'],[0,-1,0])
    assert p['convergence_required'] is True

def test_affine_vector_limit_handles_counteracting_load_and_three_dimensional_norm():
    assert affine_displacement_limit([3,0,0],[-1,0,0],5)[0]==pytest.approx(8)
    assert affine_displacement_limit([3,4,0],[0,0,1],13)[0]==pytest.approx(12)
    assert affine_displacement_limit([3,0,0],[-1,0,0],5,[1,0,0])[0]==pytest.approx(8)
    assert affine_displacement_limit([6,0,0],[-1,0,0],5)==(None,False)

def test_equal_norms_with_different_vector_directions_do_not_appear_converged():
    a={'name':'a','displacement_vector_mm':[.01,0,0],'displacement_norm_mm':.01,'absolute_convergence_tolerance_mm':1e-9}
    b=dict(a,displacement_vector_mm=[0,.01,0])
    assert not convergence([a],[b],.05)['a']['converged']
