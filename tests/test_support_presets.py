import numpy as np
import pytest
from simplecae.support_presets import support_from_preset
from simplecae.constraints import rigid_diagnostics,check_rigid_modes

SELECTOR={'type':'plane','axis':'x','position_mm':0}


def test_explicit_translation_dofs_for_seat_guide_pin_and_stop():
    assert support_from_preset('seat',SELECTOR,'normal_seat','x')['dofs']==[1]
    assert support_from_preset('guide',SELECTOR,'sliding_guide','x')['dofs']==[2,3]
    assert support_from_preset('pin',SELECTOR,'pin_position','y')['dofs']==[1,3]
    assert support_from_preset('stop',SELECTOR,'axial_stop','z')['dofs']==[3]
    assert support_from_preset('mount',SELECTOR,'fixed')['dofs']==[1,2,3]
    assert support_from_preset('body-seat',SELECTOR,'normal_seat','x',body='plate')['body']=='plate'


def test_arbitrary_direction_not_silently_fixed_to_all_axes():
    with pytest.raises(ValueError,match='explicitly rotated analysis frame'):support_from_preset('tilted',SELECTOR,'normal_seat',[1,1,0])
    with pytest.raises(ValueError,match='no directional axis'):support_from_preset('all',SELECTOR,'fixed','x')


def test_guide_reports_missing_axial_stop_and_real_stop_restores_rank():
    points={i+1:np.array([x,5,z],float) for i,(x,z) in enumerate([(0,-5),(0,5),(100,-5),(100,5)])}
    fixed={n:[2,3] for n in points};d=rigid_diagnostics(points,fixed)
    assert d['missing_modes']==1 and d['missing_components']==['Tx']
    with pytest.raises(ValueError,match='involved axes: Tx'):check_rigid_modes(points,fixed)
    fixed[1]=[1,2,3];assert check_rigid_modes(points,fixed)==6


def test_seat_does_not_prove_all_motion_restrained():
    points={i+1:np.array([x,y,0.]) for i,(x,y) in enumerate([(0,0),(1,0),(0,1),(1,1)])}
    d=rigid_diagnostics(points,{n:[3] for n in points})
    assert d['missing_modes']==3 and set(d['missing_components'])=={'Tx','Ty','Rz'}
