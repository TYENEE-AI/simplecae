"""Consistent quadratic body loads and conservative surface-wrench distribution."""
from __future__ import annotations
import numpy as np


def cross_matrix(r):
    x, y, z = r
    return np.array([[0,-z,y],[z,0,-x],[-y,x,0]], dtype=float)


def validate_distribution(spec):
    if spec.get('distribution', 'consistent') not in ('consistent', 'bearing_only'):
        raise ValueError('distribution must be consistent or bearing_only')
    if 'allow_opposite_traction' in spec and type(spec['allow_opposite_traction']) is not bool:
        raise ValueError('allow_opposite_traction must be boolean')


def distribute_wrench(coords, integrals, force, moment, application_point=None, *,
                      distribution='consistent', allow_opposite_traction=False, diagnostics=None):
    validate_distribution({'distribution':distribution,'allow_opposite_traction':allow_opposite_traction})
    area = sum(integrals.values())
    if not np.isfinite(area) or area <= 0:
        raise ValueError("wrench surface has no positive integrated area")
    center = sum((coords[n]*w for n,w in integrals.items()), np.zeros(3))/area
    force, moment = np.array(force, dtype=float), np.array(moment, dtype=float)
    if application_point is not None:
        moment = moment + np.cross(np.array(application_point)-center, force)
    result = {n: force*w/area for n,w in integrals.items()}
    if distribution == 'bearing_only':
        from scipy.optimize import lsq_linear
        magnitude = float(np.linalg.norm(force))
        if not magnitude:
            raise ValueError('bearing_only requires a nonzero force; a pure couple needs an explicit traction model')
        direction = force/magnitude
        nodes = [n for n,w in integrals.items() if w > area*1e-12]
        positions = np.array([coords[n]-center for n in nodes])
        length = max(float(np.linalg.norm(positions,axis=1).max()),np.finfo(float).eps)
        # A bearing traction is parallel to the declared resultant. No artificial
        # transverse force couples are introduced to make an infeasible patch fit.
        matrix = np.vstack((np.ones(len(nodes)),np.cross(positions,direction).T/length))
        target = np.r_[1.,moment/(magnitude*length)]
        solution = lsq_linear(matrix,target,bounds=(0,np.inf),lsq_solver='lsmr',tol=1e-12,lsmr_tol=1e-13)
        shares = solution.x
        if shares.sum() > 0: shares = shares/shares.sum()
        result = {n:np.zeros(3) for n in integrals}
        result.update({n:force*w for n,w in zip(nodes,shares)})
    elif np.linalg.norm(moment) > 1e-14:
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
    magnitude=float(np.linalg.norm(force))
    projections={n:float(np.dot(f,force/magnitude)) if magnitude else 0. for n,f in result.items()}
    absolute=sum(abs(v) for v in projections.values())
    reverse=sum(max(0.,-v) for v in projections.values())
    ratio=reverse/absolute if absolute else 0.
    reversed_nodes=[n for n,v in projections.items() if v < -max(magnitude,1.)*1e-12]
    points=np.array([coords[n] for n in integrals])
    size=float(np.linalg.norm(np.ptp(points,axis=0)))
    offset=float(np.linalg.norm(np.array(application_point)-center)) if application_point is not None else 0.
    # For a zero target moment, normalize by the patch force/length scale.
    moment_scale=max(float(np.linalg.norm(moment)),magnitude*size*1e-9,1e-12)
    moment_residual=float(np.linalg.norm(actual_moment-moment)/moment_scale)
    report={'distribution':distribution,'opposite_fraction':ratio,'reverse_projected_force_n':reverse,
            'reverse_resultant_n':sum((result[n] for n in reversed_nodes),np.zeros(3)).tolist(),
            'reverse_bbox_mm':[np.min([coords[n] for n in reversed_nodes],axis=0).tolist(),
                               np.max([coords[n] for n in reversed_nodes],axis=0).tolist()] if reversed_nodes else None,
            'allow_opposite_traction':allow_opposite_traction,'application_offset_mm':offset,
            'patch_characteristic_size_mm':size,'moment_relative_residual':moment_residual,
            'actual_force_n':actual_force.tolist(),'actual_moment_n_mm':actual_moment.tolist(),
            'requested_moment_n_mm':moment.tolist(),'centroid_mm':center.tolist(),
            'nodes':[{'id':int(n),'xyz_mm':coords[n].tolist(),'force_n':f.tolist()} for n,f in result.items()],
            'warnings':(['opposite_sign_traction'] if ratio>.05 else [])+
                       (['remote_application_point'] if offset>.5*size else []),
            'assumptions':['Input explicitly permits opposite-direction surface traction; verify its physical justification.'] if allow_opposite_traction else [],
            'force_projection_defined':bool(magnitude)}
    if diagnostics is not None: diagnostics.update(report)
    from .diagnostics import WorkflowError
    if distribution=='bearing_only' and moment_residual>.01:
        raise WorkflowError('infeasible_bearing_distribution: partition the CAD contact patch; see references/cad-partitioning.md',
            'infeasible_bearing_distribution',fields=['loads.*.selector','loads.*.application_point_mm'],
            next_action='partition_cad_contact_patch',details={k:v for k,v in report.items() if k!='nodes'})
    if ratio>.20 and not allow_opposite_traction:
        raise WorkflowError(f'opposite_sign_traction: {ratio:.1%} reverse traction requires explicit allow_opposite_traction or a physically appropriate patch',
            'opposite_sign_traction',fields=['loads.*.allow_opposite_traction','loads.*.selector'],
            next_action='review_load_distribution',details={k:v for k,v in report.items() if k!='nodes'})
    if not np.allclose(actual_force,force,rtol=1e-9,atol=1e-9) or (distribution!='bearing_only' and not np.allclose(actual_moment,moment,rtol=1e-9,atol=1e-8)):
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
