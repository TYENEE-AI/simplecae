import numpy as np
import pytest
from simplecae.mjcf import convert
from simplecae.robot import read_urdf,forward_kinematics


def model(tmp_path,extra=''):
    p=tmp_path/'arm.xml'
    p.write_text('''<mujoco model="arm"><compiler angle="radian" coordinate="local"/>
    '''+extra+'''<worldbody><body name="upper" pos=".2 0 0" quat=".7071067811865476 0 0 .7071067811865476">
    <joint name="shoulder" type="hinge" pos=".02 0 0" axis="0 0 1" range="-2 2"/>
    <inertial pos=".08 0 0" mass="1" diaginertia=".01 .01 .01"/>
    <body name="forearm" pos=".15 0 0"><joint name="elbow" type="hinge" axis="0 1 0" range="-2 2"/>
    <inertial pos=".05 0 0" mass=".5" diaginertia=".005 .005 .005"/></body></body></worldbody></mujoco>''')
    return p


def test_two_dof_preserves_offset_joint_and_com(tmp_path):
    r=convert(model(tmp_path),tmp_path/'out')
    robot=read_urdf(r['urdf'],massless_links=r['massless_links'])
    kin=forward_kinematics(robot,{'shoulder':0,'elbow':0})
    np.testing.assert_allclose(kin['frames']['upper'][:3,3],[.2,.02,0],atol=1e-12)
    np.testing.assert_allclose(kin['frames']['forearm'][:3,3],[.2,.15,0],atol=1e-12)
    np.testing.assert_allclose(robot['links']['upper']['com_m'],[.06,0,0],atol=1e-12)
    rotated=forward_kinematics(robot,{'shoulder':np.pi/2,'elbow':0})
    np.testing.assert_allclose(rotated['frames']['forearm'][:3,3],[.07,.02,0],atol=1e-12)
    assert r['whole_product_pass_available'] is False
    assert all(j['effort_limit'] is None for j in robot['joints'].values())


@pytest.mark.parametrize('extra',['<default><joint damping="1"/></default>','<equality><connect body1="upper" body2="forearm"/></equality>', '<actuator><motor joint="elbow"/></actuator>'])
def test_unsupported_mjcf_semantics_not_dropped(tmp_path,extra):
    with pytest.raises(ValueError,match='Unsupported MJCF'):convert(model(tmp_path,extra),tmp_path/'out')


def test_missing_inertia_does_not_infer_from_density(tmp_path):
    p=model(tmp_path);p.write_text(p.read_text().replace('<inertial pos=".08 0 0" mass="1" diaginertia=".01 .01 .01"/>',''))
    with pytest.raises(ValueError,match='--inertials'):convert(p,tmp_path/'out')


@pytest.mark.parametrize('before,after',[
    ('name="upper"','name="upper" sleep="allowed"'),
    ('range="-2 2"','limited="true"'),
    ('range="-2 2"','range="2 -2"'),
    ('diaginertia=".01 .01 .01"','diaginertia=".01 .01 .01" fullinertia="1 1 1 0 0 0"'),
    ('</worldbody>','<site name="ignored"/></worldbody>'),
])
def test_unsupported_or_ambiguous_frames_fail_closed(tmp_path,before,after):
    p=model(tmp_path);p.write_text(p.read_text().replace(before,after))
    with pytest.raises(ValueError):convert(p,tmp_path/'out')


def test_obj_assets_packaged_portably_with_coordinates_and_scale(tmp_path):
    import trimesh
    import xml.etree.ElementTree as ET
    from simplecae.case import sha256
    original=trimesh.creation.box(extents=[10,20,30]);obj=tmp_path/'part.obj';original.export(obj)
    p=model(tmp_path,'<asset><mesh name="part" file="part.obj" scale=".001 .001 .001"/></asset>')
    p.write_text(p.read_text().replace('<body name="forearm"','<geom type="mesh" mesh="part"/><body name="forearm"'))
    out=tmp_path/'out';result=convert(p,out)
    mesh=ET.parse(result['urdf']).find('.//mesh');relative=mesh.get('filename')
    assert not __import__('pathlib').Path(relative).is_absolute() and relative.endswith('.stl')
    np.testing.assert_allclose(trimesh.load(out/relative).bounds,original.bounds)
    np.testing.assert_allclose([float(v) for v in mesh.get('scale').split()],[.001]*3)
    assert result['output_files_sha256'][relative]==sha256(out/relative)
