"""Failure-oriented support and actionable displacement regressions."""
import numpy as np
import pytest
from simplecae.constraints import check_rigid_modes,support_dofs
from simplecae.signals import design_signal
from test_signals import result

def test_a_large_fixed_face_with_only_yz_still_leaves_axial_motion():
    coords={1:np.array([0.,-1,-1]),2:np.array([0.,1,-1]),3:np.array([0.,1,1]),4:np.array([0.,-1,1])}
    with pytest.raises(ValueError,match='rigid-body mode'):check_rigid_modes(coords,{n:[2,3] for n in coords})
    assert check_rigid_modes(coords,{n:[1,2,3] for n in coords})==6

def test_slide_guide_and_axial_stop_remove_different_modes():
    coords={1:np.array([0.,-1,-1]),2:np.array([10.,-1,-1]),3:np.array([0.,1,-1]),4:np.array([10.,1,-1])}
    restraints={n:[2,3] for n in coords}
    with pytest.raises(ValueError,match='1 rigid-body'):check_rigid_modes(coords,restraints)
    restraints[1]=[1,2,3]
    assert check_rigid_modes(coords,restraints)==6

@pytest.mark.parametrize('dofs',[[],[0],[4],[True],[1,1],['x']])
def test_invalid_solid_constraint_components_are_not_silently_fixed(dofs):
    with pytest.raises(ValueError):support_dofs({'dofs':dofs})

def test_stiffness_feedback_preserves_the_node_direction_and_functional_limit():
    from simplecae.assessment import assess
    r=result()
    for level in r['levels']:
        level['results'].update(max_displacement_mm=.48,max_displacement_node=27,
            max_displacement_location_mm=[0,0,53],max_displacement_vector_mm=[.48,0,0])
    r['case']['criteria']['max_displacement_mm']=.2
    r['assessment']=assess(r['case'],r['levels']);r['status']=r['assessment']['status']
    signal=design_signal(r)
    guidance=next(x for x in signal['feedback'] if x.get('kind')=='design_guidance')
    assert guidance['node']==27 and guidance['location_mm']==[0,0,53]
    assert guidance['displacement_vector_mm']==[.48,0,0]
    assert guidance['actual_displacement_mm']==.48 and guidance['allowed_displacement_mm']==.2
    assert guidance['required_stiffness_multiplier']==2.4 and signal['bottleneck_margin']<1
