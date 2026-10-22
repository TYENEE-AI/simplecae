import copy
import numpy as np
import pytest

from simplecae.case import validate_case
from simplecae.benchmarks import bar_case
from simplecae.loads import distribute_wrench, integrate_gravity, tetra10_basis
from simplecae.assessment import fixed_load_limit, field_metrics, assess
from simplecae.buckling import parse_buckling_dat


def synthetic_fields(sigma,u):
    return {"stresses":{(1,1):np.array([sigma,0.,0.,0.,0.,0.])},
            "strains":{(1,1):np.array([sigma/200000,0.,0.,0.,0.,0.])},
            "displacements":{1:np.array([u,0.,0.])}}


def test_fixed_loads_do_not_scale_with_payload():
    full,fixed=synthetic_fields(15.,.01),synthetic_fields(5.,.002)
    scale,governing=fixed_load_limit(full,fixed,100.,.02)
    assert scale==pytest.approx(2.25)
    assert governing=="stiffness"
    assert field_metrics(full,fixed,0)["max_von_mises_mpa"]==5.
    assert field_metrics(full,fixed,scale)["max_displacement_mm"]==pytest.approx(.02)


def test_fixed_loads_alone_can_fail():
    factor,reason=fixed_load_limit(synthetic_fields(25.,.03),synthetic_fields(20.,.025),100.,.02)
    assert factor is None and "fixed loads alone" in reason


def test_signed_wrench_with_offset_is_conserved():
    xyz={1:np.array([-1.,-1.,2.]),2:np.array([1.,-1.,2.]),3:np.array([1.,1.,2.]),4:np.array([-1.,1.,2.])}
    loads,center,moment=distribute_wrench(xyz,{n:1. for n in xyz},[10.,0.,-20.],[0.,5.,0.],[2.,0.,2.],allow_opposite_traction=True)
    assert np.allclose(sum(loads.values()),[10.,0.,-20.])
    assert np.allclose(sum(np.cross(xyz[n]-center,f) for n,f in loads.items()),[0.,45.,0.])
    assert np.allclose(moment,[0.,45.,0.])


def test_wrench_with_no_lever_arm_rejected():
    with pytest.raises(ValueError):
        distribute_wrench({1:np.zeros(3)},{1:1.},[0.,0.,0.],[0.,1.,0.])


def test_quadratic_body_load_conserves_weight_and_centroid():
    a,b=.5854101966249685,.1381966011250105
    ip=np.array([[b,b,b],[a,b,b],[b,a,b],[b,b,a]])
    weights=np.full(4,1/24)
    conn=np.arange(1,11)[None,:]
    forces=integrate_gravity(conn,np.ones((1,4)),ip,weights,6000.,[0.,0.,-10.])
    assert sum(forces.values())[2]==pytest.approx(-1e-5)
    # Corner nodal shares can be negative; suppressing them corrupts a P2 body load.
    assert forces[1][2]>0 and forces[5][2]<0
    corners=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]])
    xyz=np.vstack([corners]+[(corners[i]+corners[j])[None,:]/2 for i,j in [(0,1),(1,2),(2,0),(0,3),(1,3),(2,3)]])
    moment=sum(np.cross(xyz[n-1],f) for n,f in forces.items())
    assert np.allclose(moment,np.cross([.25,.25,.25],[0,0,-1e-5]))
    assert np.allclose(tetra10_basis(ip).sum(axis=1),1.)


@pytest.mark.parametrize("bad", [0,21,True,1.1])
def test_buckling_mode_budget_validated(bad):
    case=bar_case("bar",[-100.,0.,0.],[5.,4.,3.]);case["schema_version"]="2.0"
    case["buckling"]={"enabled":True,"modes":bad}
    with pytest.raises(ValueError):validate_case(case)


def test_gravity_requires_density():
    case=bar_case("bar",[0.,0.,-100.],[5.,4.,3.]);case["schema_version"]="2.0"
    case["gravity"]={"acceleration_m_s2":[0.,0.,-9.8]}
    with pytest.raises(ValueError,match="density"):
        validate_case(case)


def test_buckling_without_positive_factors_is_indeterminate():
    case=bar_case("bar",[100.,0.,0.],[5.,4.,3.]);case["schema_version"]="2.0"
    case["buckling"]={"enabled":True,"modes":3}
    levels=[{"results":{"max_von_mises_mpa":10.,"max_displacement_mm":.01,"max_strain_norm":.0001,"minimum_bbox_extent_mm":10.,"force_balance_relative_error":1e-8,"moment_balance_relative_error":1e-8},"buckling":{"lowest_positive_factor":None}} for _ in range(3)]
    result=assess(case,levels)
    assert result["status"]=="indeterminate"
    assert not result["conditional_body_limit"]["available"]


def test_nonfinite_eigenvalue_rejected(tmp_path):
    path=tmp_path/"buckling.dat"
    path.write_text("BUCKLING FACTOR OUTPUT\n 1 nan\n")
    with pytest.raises(RuntimeError):parse_buckling_dat(path)
