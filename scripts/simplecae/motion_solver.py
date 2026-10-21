"""Prescribed rigid-tree Newton--Euler loads, in world SI coordinates.

No integration, control model, drive loss, collision or flexible response.
Wrenches are [Fx,Fy,Fz,Mx,My,Mz]; every reported reference point is explicit.
"""
from __future__ import annotations

import numpy as np

from .robot import forward_kinematics


def _vector(value, name):
    a = np.asarray(value, dtype=float)
    if a.shape != (3,) or not np.isfinite(a).all():
        raise ValueError(name + " must be a finite three-vector")
    return a


def _coordinates(robot, values, name):
    expected = {n for n, j in robot["joints"].items() if j["type"] != "fixed"}
    if set(values) != expected:
        raise ValueError(name + " must explicitly cover every movable joint exactly once")
    if any(isinstance(v, bool) or not np.isfinite(float(v)) for v in values.values()):
        raise ValueError(name + " must contain finite scalars")
    return {n: float(v) for n, v in values.items()}


def kinematics(robot, positions, velocities, accelerations, base_pose=None, base_motion=None):
    """Actual (not gravity-shifted) velocities and accelerations at link origins."""
    if any(j["mimic"] for j in robot["joints"].values()):
        raise ValueError("Motion loads do not model mimic transmissions; expand an independent tree with explicit drive mechanics")
    q = _coordinates(robot, positions, "positions")
    qd = _coordinates(robot, velocities, "velocities")
    qdd = _coordinates(robot, accelerations, "accelerations")
    pose = np.eye(4) if base_pose is None else np.asarray(base_pose, dtype=float)
    if (pose.shape != (4, 4) or not np.isfinite(pose).all()
            or not np.allclose(pose[3], [0, 0, 0, 1], atol=1e-12, rtol=0)
            or not np.allclose(pose[:3, :3].T@pose[:3, :3], np.eye(3), atol=1e-12, rtol=0)
            or abs(np.linalg.det(pose[:3, :3])-1) > 1e-12):
        raise ValueError("base_pose must be a proper rigid SI transform")
    kin = forward_kinematics(robot, q, pose)
    names = ("velocity_m_s", "acceleration_m_s2", "omega_rad_s", "alpha_rad_s2")
    base_motion = dict.fromkeys(names, [0., 0., 0.]) if base_motion is None else base_motion
    if set(base_motion) != set(names):
        raise ValueError("base_motion must explicitly contain velocity, acceleration, omega and alpha")
    states = {robot["root"]: {key: _vector(base_motion[key], key) for key in names}}

    def walk(parent):
        p = states[parent]
        w, alpha = p["omega_rad_s"], p["alpha_rad_s2"]
        for name in robot["children"][parent]:
            joint = robot["joints"][name]
            child = joint["child"]
            r = kin["frames"][child][:3, 3]-kin["frames"][parent][:3, 3]
            axis = kin["axes"][name]
            v = p["velocity_m_s"]+np.cross(w, r)
            a = p["acceleration_m_s2"]+np.cross(alpha, r)+np.cross(w, np.cross(w, r))
            wc, ac = w.copy(), alpha.copy()
            if joint["type"] in ("revolute", "continuous"):
                wc += axis*qd[name]
                ac += axis*qdd[name]+np.cross(w, axis*qd[name])
            elif joint["type"] == "prismatic":
                v += axis*qd[name]
                a += axis*qdd[name]+2*np.cross(w, axis*qd[name])
            states[child] = dict(zip(names, (v, a, wc, ac)))
            walk(child)

    walk(robot["root"])
    return kin, states


def shift_wrench(wrench, old_point, new_point):
    """Same action, new moment reference; all expressed in the same frame."""
    w = np.asarray(wrench, dtype=float).copy()
    w[3:] += np.cross(np.asarray(old_point)-np.asarray(new_point), w[:3])
    return w


def solve(robot, positions, velocities, accelerations, gravity, *,
          base_pose=None, base_motion=None, loads=()):
    kin, states = kinematics(robot, positions, velocities, accelerations, base_pose, base_motion)
    frames = kin["frames"]
    gravity = _vector(gravity, "gravity")
    own, applied, bodies = {}, {}, {}
    for name, link in robot["links"].items():
        t, s = frames[name], states[name]
        r = t[:3, :3]@link["com_m"]
        center = t[:3, 3]+r
        omega, alpha = s["omega_rad_s"], s["alpha_rad_s2"]
        a = s["acceleration_m_s2"]+np.cross(alpha, r)+np.cross(omega, np.cross(omega, r))
        inertia = t[:3, :3]@link["inertia_kg_m2"]@t[:3, :3].T
        inertial_force = link["mass_kg"]*a
        inertial_moment = inertia@alpha+np.cross(omega, inertia@omega)
        gravity_force = link["mass_kg"]*gravity
        applied[name] = np.r_[gravity_force, np.cross(r, gravity_force)]
        own[name] = applied[name]-np.r_[inertial_force, inertial_moment+np.cross(r, inertial_force)]
        bodies[name] = {"origin_world_m": t[:3, 3], "center_world_m": center,
                       "rotation_link_to_world": t[:3, :3], **s,
                       "center_acceleration_m_s2": a,
                       "center_velocity_m_s": s["velocity_m_s"]+np.cross(omega, r),
                       "inertial_force_n": inertial_force, "inertial_moment_at_com_n_m": inertial_moment}
    for load in loads:
        name = load["link"]
        if name not in frames:
            raise ValueError("External load references an unknown link")
        if load.get("frame") not in ("world", "link") or load.get("position_frame") not in ("world", "link"):
            raise ValueError("External force/moment and position frames must be explicit")
        t = frames[name]
        f = _vector(load["force_n"], "external force")
        m = _vector(load["moment_n_m"], "external moment")
        point = _vector(load["position_m"], "external position")
        if load["frame"] == "link":
            f, m = t[:3, :3]@f, t[:3, :3]@m
        if load["position_frame"] == "link":
            point = t[:3, :3]@point+t[:3, 3]
        wrench = np.r_[f, m+np.cross(point-t[:3, 3], f)]
        applied[name] += wrench
        own[name] += wrench
    subtree = {}

    def collect(name):
        wrench = own[name].copy()
        for jn in robot["children"][name]:
            child = robot["joints"][jn]["child"]
            wrench += shift_wrench(collect(child), frames[child][:3, 3], frames[name][:3, 3])
        subtree[name] = wrench
        return wrench

    collect(robot["root"])
    joints = {}
    for name, j in robot["joints"].items():
        point = kin["joint_frames"][name][:3, 3]
        reaction = -shift_wrench(subtree[j["child"]], frames[j["child"]][:3, 3], point)
        effort = (float(kin["axes"][name]@reaction[:3]) if j["type"] == "prismatic" else
                  float(kin["axes"][name]@reaction[3:]) if j["type"] != "fixed" else None)
        joints[name] = {"point_world_m": point, "axis_world": kin["axes"][name],
                        "parent_on_child_world": reaction,
                        "effort": effort, "effort_unit": "N" if j["type"] == "prismatic" else "N m",
                        "speed": velocities.get(name, 0.), "acceleration": accelerations.get(name, 0.)}
    # Independent whole-system sum about the world origin, not tree recursion.
    applied_world, inertia_world = np.zeros(6), np.zeros(6)
    for name, body in bodies.items():
        applied_world += shift_wrench(applied[name], body["origin_world_m"], np.zeros(3))
        inertia_world += np.r_[body["inertial_force_n"],
                              body["inertial_moment_at_com_n_m"]+np.cross(body["center_world_m"], body["inertial_force_n"])]
    base_point = frames[robot["root"]][:3, 3]
    base_on_robot = -subtree[robot["root"]]
    residual = applied_world+shift_wrench(base_on_robot, base_point, np.zeros(3))-inertia_world
    # Scale force and moment separately; no mixed-unit norm gate.
    scales = np.maximum(1., np.maximum(np.abs(applied_world), np.abs(inertia_world)))
    if np.any(np.abs(residual) > 1e-10*scales):
        raise ValueError("Motion load recursion fails whole-system momentum balance")
    if not all(np.isfinite(v).all() for v in (*own.values(), *subtree.values(), base_on_robot, residual)):
        raise ValueError("Nonfinite motion loads")
    return {"bodies": bodies, "joints": joints, "effective_body_wrenches_world": own,
            "base": {"point_world_m": base_point, "base_on_robot_world": base_on_robot,
                     "robot_on_base_world": -base_on_robot},
            "verification": {"momentum_balance_passed": True,
                             "force_residual_n": residual[:3], "moment_residual_n_m": residual[3:]}}
