import copy
import numpy as np
import pytest
from simplecae.contact_wrench import finite_pad_wrench

def pads(gap=.020,normal=13,mu=.3):
    return [{'name':name,'center_world_m':[x,0,0],'inward_normal_world':[direction,0,0],
        'tangent_u_world':[0,1,0],'tangent_v_world':[0,0,1],'half_extents_m':[.008,.012],
        'normal_force_n':normal,'friction_coefficient':mu} for name,x,direction in [('left',-gap/2,1),('right',gap/2,-1)]]

@pytest.mark.parametrize('gap',[.008,.020,.032])
def test_eccentric_payload_wrench_matches_force_limit_and_independent_moments(gap):
    f=np.array([0,0,-.25*(9.80665+2)*2]);w=np.r_[f,np.cross([.002,.002,0],f)]
    r=finite_pad_wrench(pads(gap),[0]*6,w,reference_world_m=[0,0,0])
    assert r['payload_scale_limit']==pytest.approx(7.8/5.903325,rel=1e-7)
    assert max(r['relative_force_residual'],r['relative_moment_residual'])<1e-8
    for name in ['left','right']:
        assert sum(c['normal_force_n'] for c in r['contact_forces'] if c['pad']==name)==pytest.approx(13)

def test_torsional_failure_is_visible_even_when_vertical_friction_is_sufficient():
    demand=[0,0,-5.903325,0,0,.5]
    r=finite_pad_wrench(pads(.032),demand)
    assert 2*.3*13>abs(demand[2]) and not r['feasible']

def test_low_friction_failure_is_not_relabelled_a_solver_error():
    r=finite_pad_wrench(pads(mu=.2),[0,0,-5.903325,0,0,0])
    assert r['feasible'] is False and r['solver_status']==2

def test_translated_rotated_world_frame_preserves_the_same_force_and_torque_limit():
    from simplecae.robot import rotation_rpy
    rotation=rotation_rpy([.3,-.2,.7]);translation=np.array([15,-3,9]);p=pads()
    for pad in p:
        pad['center_world_m']=(rotation@pad['center_world_m']+translation).tolist()
        for key in ('inward_normal_world','tangent_u_world','tangent_v_world'):pad[key]=(rotation@pad[key]).tolist()
    w=np.r_[rotation@np.array([0,0,-5.903325]),rotation@np.array([-.01180665,.01180665,0])]
    r=finite_pad_wrench(p,[0]*6,w,reference_world_m=translation.tolist())
    assert r['payload_scale_limit']==pytest.approx(7.8/5.903325,rel=1e-7)

def test_declared_per_pad_wrenches_are_constrained_not_silently_redistributed():
    p=pads();fixed=[[13,0,0,0,0,0],[-13,0,0,0,0,0]]
    # The left pad would need5N tangential force though its capacity is3.9N;
    # total6N could otherwise be balanced by redistributing it across pads.
    variable=[[0,0,5,0,.05,0],[0,0,1,0,-.01,0]]
    total_w=[0,0,-6,0,-.04,0] # opposing external wrench about the common reference
    r=finite_pad_wrench(p,[0]*6,total_w,declared_pad_fixed=fixed,declared_pad_variable=variable)
    assert r['payload_scale_limit']==pytest.approx(3.9/5)

def test_invalid_pad_basis_or_missing_variable_allocation_is_rejected():
    p=pads();p[0]['tangent_u_world']=[1,0,0]
    with pytest.raises(ValueError,match='orthonormal'):finite_pad_wrench(p,[0]*6)
    with pytest.raises(ValueError,match='provided together'):finite_pad_wrench(pads(),[0]*6,[0,0,-1,0,0,0],declared_pad_fixed=[[0]*6]*2)
