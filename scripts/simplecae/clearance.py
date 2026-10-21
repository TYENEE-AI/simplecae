"""Conservative clearance screen for an omitted straight cylindrical shaft.

This is a postprocessing guard, not a cylindrical contact or bolt shear model.
Quadratic triangle Bezier hulls bound the entire deformed bore surface, not
only its mesh nodes. An inconclusive lower bound must not be called contact.
"""
import numpy as np

def cross2(a,b):return float(a[0]*b[1]-a[1]*b[0])

def convex_polygon(points):
    points=sorted(set(map(tuple,points)))
    cross=lambda a,b,c:cross2(np.asarray(b)-a,np.asarray(c)-a)
    def chain(sequence):
        result=[]
        for point in sequence:
            while len(result)>1 and cross(result[-2],result[-1],point)<=0:result.pop()
            result.append(point)
        return result
    return np.asarray(chain(points)[:-1]+chain(points[::-1])[:-1] if len(points)>1 else points)


def radial_clearance(coords,displacements,triangles,axis_start_mm,axis_end_mm,shaft_radius_mm):
    start=np.asarray(axis_start_mm,float);direction=np.asarray(axis_end_mm,float)-start
    radius=float(shaft_radius_mm)
    if start.shape!=(3,) or direction.shape!=(3,):raise ValueError('clearance axis endpoints must be 3-vectors')
    if not np.all(np.isfinite(np.r_[start,direction,radius])) or radius<=0 or np.linalg.norm(direction)<=1e-12:
        raise ValueError('clearance requires a finite straight axis and positive shaft radius')
    direction/=np.linalg.norm(direction);seed=np.eye(3)[np.argmin(abs(direction))]
    u=np.cross(direction,seed);u/=np.linalg.norm(u);basis=np.column_stack((u,np.cross(direction,u)))
    lower=np.inf;sampled=np.inf;count=0
    for tri in triangles:
        if len(tri)!=6:raise ValueError('clearance requires complete C3D10 boundary triangles')
        p=np.array([np.asarray(coords[int(n)])+np.asarray(displacements[int(n)]) for n in tri])
        if p.shape!=(6,3):raise ValueError('clearance coordinates/displacements must be 3-vectors')
        if not np.all(np.isfinite(p)):raise ValueError('nonfinite clearance surface')
        controls=np.vstack((p[:3],2*p[3:]-(p[[0,1,2]]+p[[1,2,0]])/2))
        xy=(controls-start)@basis
        polygon=convex_polygon(xy)
        inside=len(polygon)>2 and all(cross2(b-a,-a)>=0 for a,b in zip(polygon,np.roll(polygon,-1,axis=0)))
        if inside:distance=0.
        elif len(polygon)==1:distance=float(np.linalg.norm(polygon[0]))
        else:
            distance=np.inf
            for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
                edge=b-a;t=float(np.clip(-a@edge/(edge@edge),0,1))
                distance=min(distance,float(np.linalg.norm(a+t*edge)))
        rounding=256*np.finfo(float).eps*max(np.linalg.norm(p,axis=1).max(),np.linalg.norm(start),1.)
        lower=min(lower,distance-radius-rounding)
        sampled=min(sampled,float(np.linalg.norm((p-start)@basis,axis=1).min())-radius);count+=1
    if not count:raise ValueError('clearance surface is empty')
    return {'status':'clear_under_stated_axis' if lower>0 else 'interference_at_sample' if sampled<0 else 'unresolved',
            'minimum_clearance_lower_bound_mm':float(lower),'minimum_sampled_clearance_mm':float(sampled),
            'surface_triangle_count':count,
            'meaning':'Conservative full quadratic-surface Bezier hull bound to a prescribed infinite straight cylinder. Finite-end effects, shaft bending, bearing forces and nonlinear contact are not evaluated.'}
