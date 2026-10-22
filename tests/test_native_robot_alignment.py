from types import SimpleNamespace as S
import pytest
from simplecae_scad.robot import _joint_alignment


def parts(offset=(0,0,5),tilted=False):
    origin=S(origin=(0,0,0),x_axis=(1,0,0),y_axis=(0,1,0),z_axis=(0,0,1))
    moving=S(origin=offset,x_axis=(1,0,0),y_axis=(0,0,1) if tilted else (0,1,0),z_axis=(0,-1,0) if tilted else (0,0,1))
    part=S(get_connector=lambda _:S(placement=origin))
    return {'base':S(placement=origin,item=part),'slider':S(placement=moving,item=part)}


def constraint(kind):return S(connector_a=S(component_id='base',connector_id='guide'),connector_b=S(component_id='slider',connector_id='guide'),constraint_kind=kind,constraint_id='joint')


def test_prismatic_axial_travel_is_allowed_but_revolute_offset_is_not():
    _,error,transverse,angle=_joint_alignment(parts(),constraint('prismatic'))
    assert error==5 and transverse==0 and angle==0
    with pytest.raises(ValueError,match='alignment'):_joint_alignment(parts(),constraint('revolute'))


@pytest.mark.parametrize('offset,tilted',[((2,0,5),False),((0,0,5),True)])
def test_prismatic_transverse_offset_or_tilt_is_rejected(offset,tilted):
    with pytest.raises(ValueError,match='alignment'):_joint_alignment(parts(offset,tilted),constraint('prismatic'))
