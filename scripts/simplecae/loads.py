"""Consistent quadratic body loads and conservative surface-wrench distribution."""
from __future__ import annotations
import numpy as np


def cross_matrix(r):
    x, y, z = r
    return np.array([[0,-z,y],[z,0,-x],[-y,x,0]], dtype=float)


def distribute_wrench(coords, integrals, force, moment, application_point=None):
    area = sum(integrals.values())
    if not np.isfinite(area) or area <= 0:
        raise ValueError("wrench surface has no positive integrated area")
    center = sum((coords[n]*w for n,w in integrals.items()), np.zeros(3))/area
    force, moment = np.array(force, dtype=float), np.array(moment, dtype=float)
    if application_point is not None:
        moment = moment + np.cross(np.array(application_point)-center, force)
    result = {n: force*w/area for n,w in integrals.items()}
    if np.linalg.norm(moment) > 1e-14:
        # P2 face corner weights are zero; use positive area-carrying nodes for the couple.
        nodes = [n for n,w in integrals.items() if w > area*1e-12]
        positions = np.array([coords[n]-center for n in nodes])
        weights = np.array([integrals[n]/area for n in nodes])
        length = float(np.max(np.linalg.norm(positions,axis=1)))
        if length <= 1e-10:
            raise ValueError("moment distribution requires a finite surface lever arm")
        matrix = np.hstack([np.vstack((np.eye(3), cross_matrix(r)/length)) for r in positions])
        metric = np.repeat(weights,3)
        gram = (matrix*metric) @ matrix.T
        if np.linalg.matrix_rank(gram) < 6 or np.linalg.cond(gram) > 1e12:
            raise ValueError("selected surface cannot carry the requested full wrench")
        target = np.r_[np.zeros(3), moment/length]
        corrections = (metric*(matrix.T @ np.linalg.solve(gram,target))).reshape((-1,3))
        for n,v in zip(nodes,corrections):
            result[n] += v
    actual_force = sum(result.values(),np.zeros(3))
    actual_moment = sum((np.cross(coords[n]-center,f) for n,f in result.items()),np.zeros(3))
    if not np.allclose(actual_force,force,rtol=1e-9,atol=1e-9) or not np.allclose(actual_moment,moment,rtol=1e-9,atol=1e-8):
        raise ValueError("surface wrench failed force/moment conservation")
    return result, center, moment


def tetra10_basis(points):
    p = np.asarray(points).reshape((-1,3))
    bary = np.column_stack((1-p.sum(axis=1),p))
    values = [bary[:,i]*(2*bary[:,i]-1) for i in range(4)]
    values += [4*bary[:,a]*bary[:,b] for a,b in ((0,1),(1,2),(2,0),(0,3),(1,3),(2,3))]
    return np.array(values).T


def integrate_gravity(connectivity, jacobians, integration_points, integration_weights, density, acceleration):
    basis = tetra10_basis(integration_points)
    measures = np.asarray(jacobians)*np.asarray(integration_weights)
    weights = measures @ basis
    forces = {}
    acceleration = np.asarray(acceleration,dtype=float)
    for conn,w in zip(connectivity,weights):
        for node,weight in zip(conn,w):
            n = int(node)
            forces[n] = forces.get(n,np.zeros(3)) + weight*density*1e-9*acceleration
    return forces
