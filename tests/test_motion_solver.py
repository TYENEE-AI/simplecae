"""Analytical inverse dynamics, frame invariance, and independent energy checks."""
import copy
import math
from pathlib import Path

import numpy as np
import pytest

from simplecae.robot import read_urdf, static_wrenches, forward_kinematics, transform
from simplecae.motion_solver import solve, kinematics


def link(name, mass=1., com=(.1, 0, 0), inertia=(.001, .004, .004), rpy=(0, 0, 0)):
    return (f'<link name="{name}"><inertial><origin xyz="{" ".join(map(str, com))}" '
            f'rpy="{" ".join(map(str, rpy))}"/><mass value="{mass}"/>'
            f'<inertia ixx="{inertia[0]}" iyy="{inertia[1]}" izz="{inertia[2]}" '
            'ixy="0" ixz="0" iyz="0"/></inertial></link>')


def joint(name, parent, child, kind="revolute", xyz=(0, 0, 0), axis=(0, 0, 1)):
    return (f'<joint name="{name}" type="{kind}"><parent link="{parent}"/><child link="{child}"/>'
            f'<origin xyz="{" ".join(map(str, xyz))}"/><axis xyz="{" ".join(map(str, axis))}"/>'
            '<limit lower="-6" upper="6" effort="100" velocity="20"/></joint>')


def robot(tmp_path, text):
    path = tmp_path/"model.urdf"
    path.write_text('<robot name="reference"><link name="base"/>'+text+'</robot>', encoding="utf-8")
    return read_urdf(path, massless_links=["base"])


def test_prismatic_acceleration_and_static_equivalence(tmp_path):
    r = robot(tmp_path, link("body", 2.)+joint("slide", "base", "body", "prismatic", axis=(0, 0, 1)))
    result = solve(r, {"slide": .3}, {"slide": 5.}, {"slide": 4.}, [0, 0, -9.81])
    assert result["joints"]["slide"]["effort"] == pytest.approx(2*(9.81+4))
    assert result["bodies"]["body"]["center_acceleration_m_s2"] == pytest.approx([0, 0, 4])
    static = static_wrenches(r, forward_kinematics(r, {"slide": .3}), [0, 0, -9.81])
    zero = solve(r, {"slide": .3}, {"slide": 0.}, {"slide": 0.}, [0, 0, -9.81])
    assert zero["joints"]["slide"]["effort"] == pytest.approx(static["joint_efforts"]["slide"])
    assert zero["base"]["robot_on_base_world"] == pytest.approx(static["subtree"]["base"])


def test_eccentric_rotation_centripetal_and_tangential_load(tmp_path):
    r = robot(tmp_path, link("body", 2., (.2, 0, 0))+joint("spin", "base", "body"))
    out = solve(r, {"spin": 0.}, {"spin": 3.}, {"spin": 4.}, [0, 0, 0])
    assert out["bodies"]["body"]["center_acceleration_m_s2"] == pytest.approx([-1.8, .8, 0])
    assert out["base"]["base_on_robot_world"][:3] == pytest.approx([-3.6, 1.6, 0])
    assert out["joints"]["spin"]["effort"] == pytest.approx((.004+2*.2**2)*4)


@pytest.mark.parametrize("q,qd,qdd", [
    ([.4, -.7], [1.2, -1.3], [2.2, .8]),
    ([-.9, 1.6], [-.7, 2.1], [-1.2, 1.5]),
    ([.2, .3], [0., 0.], [0., 0.]),
])
def test_two_link_against_analytical_lagrange(tmp_path, q, qd, qdd):
    l1, r1, r2, m1, m2, i1, i2, g = .4, .2, .15, 2., 1., .03, .01, 9.81
    r = robot(tmp_path, link("a", m1, (r1, 0, 0), (.001, i1, i1))+
              link("b", m2, (r2, 0, 0), (.001, i2, i2))+
              joint("j1", "base", "a")+joint("j2", "a", "b", xyz=(l1, 0, 0)))
    out = solve(r, dict(zip(("j1", "j2"), q)), dict(zip(("j1", "j2"), qd)),
                dict(zip(("j1", "j2"), qdd)), [0, -g, 0])
    h = m2*l1*r2
    m = np.array([[i1+i2+m1*r1*r1+m2*(l1*l1+r2*r2)+2*h*np.cos(q[1]),
                   i2+m2*r2*r2+h*np.cos(q[1])],
                  [i2+m2*r2*r2+h*np.cos(q[1]), i2+m2*r2*r2]])
    c = h*np.sin(q[1])*np.array([-2*qd[0]*qd[1]-qd[1]**2, qd[0]**2])
    gravity = np.array([(m1*r1+m2*l1)*g*np.cos(q[0])+m2*r2*g*np.cos(sum(q)),
                        m2*r2*g*np.cos(sum(q))])
    expected = m@qdd+c+gravity
    assert [out["joints"][n]["effort"] for n in ("j1", "j2")] == pytest.approx(expected, abs=1e-12)


def test_prismatic_coriolis_term(tmp_path):
    r = robot(tmp_path, link("arm", com=(0, 0, 0))+link("slider", com=(0, 0, 0))+
              joint("spin", "base", "arm")+joint("slide", "arm", "slider", "prismatic", axis=(1, 0, 0)))
    out = solve(r, {"spin": 0., "slide": .5}, {"spin": 2., "slide": 3.},
                {"spin": 0., "slide": 4.}, [0, 0, 0])
    assert out["bodies"]["slider"]["center_acceleration_m_s2"] == pytest.approx([2., 12., 0])
    assert out["joints"]["slide"]["effort"] == pytest.approx(2.)
    assert out["joints"]["spin"]["effort"] == pytest.approx(6.)


def test_inertial_axes_and_gyroscopic_moment(tmp_path):
    r = robot(tmp_path, link("body", 2., (0, 0, 0), (2., 3., 4.), (0, 0, math.pi/2))+
              joint("fixed", "base", "body", "fixed"))
    assert r["links"]["body"]["inertia_kg_m2"] == pytest.approx(np.diag([3., 2., 4.]))
    motion = {"velocity_m_s": [0, 0, 0], "acceleration_m_s2": [1, 2, 3],
              "omega_rad_s": [1, 2, 3], "alpha_rad_s2": [4, 5, 6]}
    out = solve(r, {}, {}, {}, [0, 0, 0], base_motion=motion)
    # I alpha + omega x I omega = [12,10,24] + [12,-3,-2].
    assert out["base"]["base_on_robot_world"] == pytest.approx([2, 4, 6, 24, 7, 22])


def test_rotated_translated_world_and_external_action(tmp_path):
    r = robot(tmp_path, link("a")+link("b")+
              joint("j1", "base", "a")+joint("j2", "a", "b", xyz=(.2, 0, 0), axis=(0, 1, 0)))
    q, qd, qdd = {"j1": .4, "j2": -.7}, {"j1": 1., "j2": 2.}, {"j1": 3., "j2": -2.}
    loads = [{"link": "b", "force_n": [1., 2., 3.], "moment_n_m": [2., 0., 1.],
              "position_m": [.1, 0, 0], "frame": "link", "position_frame": "link"}]
    a = solve(r, q, qd, qdd, [0, 0, -9.81], loads=loads)
    t = transform([3., -2., 1.], [.6, -.9, 1.2])
    b = solve(r, q, qd, qdd, t[:3, :3]@np.array([0, 0, -9.81]), base_pose=t, loads=loads)
    for name in q:
        assert b["joints"][name]["effort"] == pytest.approx(a["joints"][name]["effort"], abs=1e-12)
    for section in (slice(0, 3), slice(3, 6)):
        assert b["base"]["base_on_robot_world"][section] == pytest.approx(
            t[:3, :3]@a["base"]["base_on_robot_world"][section], abs=1e-12)


def test_nonplanar_tree_power_matches_finite_difference_energy(tmp_path):
    r = robot(tmp_path, link("a")+link("b")+link("c")+
              joint("j1", "base", "a")+joint("j2", "a", "b", xyz=(.2, 0, 0), axis=(0, 1, 0))+
              joint("j3", "a", "c", "prismatic", xyz=(0, .2, 0), axis=(1, 0, 0)))
    names = ["j1", "j2", "j3"]
    q, qd, qdd = np.array([.4, -.7, .12]), np.array([1.2, -.9, .5]), np.array([-.2, .3, -.4])
    def at(dt):
        return solve(r, dict(zip(names, q+dt*qd+.5*dt*dt*qdd)),
                     dict(zip(names, qd+dt*qdd)), dict(zip(names, qdd)), [0, 0, 0])
    def kinetic(result):
        total = 0.
        for n, b in result["bodies"].items():
            rot = b["rotation_link_to_world"]
            v, w = b["center_velocity_m_s"], b["omega_rad_s"]
            total += .5*(r["links"][n]["mass_kg"]*(v@v)+w@(rot@r["links"][n]["inertia_kg_m2"]@rot.T)@w)
        return total
    h = 1e-5
    rate = (kinetic(at(h))-kinetic(at(-h)))/(2*h)
    out = at(0)
    power = sum(out["joints"][n]["effort"]*qd[i] for i, n in enumerate(names))
    assert power == pytest.approx(rate, abs=1e-9)


@pytest.mark.parametrize("defect", ["missing_velocity", "nan", "fixed_position", "reflection", "mimic", "missing_base"])
def test_invalid_states_reject(tmp_path, defect):
    r = robot(tmp_path, link("body")+joint("j", "base", "body"))
    q, v, a, kwargs = {"j": 0.}, {"j": 0.}, {"j": 0.}, {}
    if defect == "missing_velocity":
        v = {}
    elif defect == "nan":
        a["j"] = float("nan")
    elif defect == "fixed_position":
        r["joints"]["j"]["type"] = "fixed"
    elif defect == "reflection":
        kwargs["base_pose"] = np.diag([-1, 1, 1, 1])
    elif defect == "mimic":
        r["joints"]["j"]["mimic"] = {"joint": "j", "multiplier": 1., "offset": 0.}
    else:
        kwargs["base_motion"] = {"velocity_m_s": [0, 0, 0]}
    with pytest.raises(ValueError):
        solve(r, q, v, a, [0, 0, -9.81], **kwargs)


def test_missing_inertia_and_closed_loop_reject(tmp_path):
    with pytest.raises(ValueError, match="no inertial"):
        robot(tmp_path, '<link name="body"/>'+joint("j", "base", "body"))
    with pytest.raises(ValueError, match="tree root"):
        robot(tmp_path, link("body")+joint("j", "base", "body")+joint("loop", "body", "base"))
