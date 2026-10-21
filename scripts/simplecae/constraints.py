"""Translational support components and the six rigid-motion modes."""
import numpy as np

def support_dofs(spec):
    dofs=spec.get('dofs',[1,2,3])
    if not isinstance(dofs,list) or not dofs or any(type(d) is not int or d not in (1,2,3) for d in dofs) or len(set(dofs))!=len(dofs):
        raise ValueError('support.dofs must be unique translational components from [1,2,3] (X,Y,Z)')
    return sorted(dofs)

def rigid_diagnostics(coords,fixed_dofs):
    if not fixed_dofs:return {'rank':0,'missing_modes':6,'missing_components':['Tx','Ty','Tz','Rx','Ry','Rz'],'null_modes':np.eye(6).tolist(),'scope':'Six common rigid motions only; not material/connection stiffness or independent-body mechanism verification.'}
    points=np.array([coords[int(n)] for n in fixed_dofs])
    center=points.mean(axis=0);span=max(float(np.linalg.norm(np.ptp(points,axis=0))),1e-12)
    rows=[]
    for node,dofs in fixed_dofs.items():
        r=(np.asarray(coords[int(node)])-center)/span
        for dof in dofs:
            axis=np.eye(3)[dof-1];rows.append(np.r_[axis,np.cross(r,axis)])
    a=np.asarray(rows);_,singular,v=np.linalg.svd(a,full_matrices=len(a)<6)
    tolerance=max(a.shape)*np.finfo(a.dtype).eps*singular[0];rank=int(np.count_nonzero(singular>tolerance));null=v[rank:]
    labels=['Tx','Ty','Tz','Rx','Ry','Rz']
    components=sorted({labels[i] for mode in null for i,x in enumerate(mode) if abs(x)>.1})
    return {'rank':rank,'missing_modes':6-rank,'missing_components':components,'null_modes':null.tolist(),
            'support_centroid_mm':center.tolist(),'rotation_normalization_length_mm':span,
            'scope':'Six common rigid motions, about the support centroid with normalized rotation; not material/connection stiffness or independent-body mechanism verification.'}


def check_rigid_modes(coords,fixed_dofs):
    diagnostics=rigid_diagnostics(coords,fixed_dofs);rank=diagnostics['rank']
    if rank<6:raise ValueError(f"support components leave {6-rank} rigid-body mode(s) unconstrained; involved axes: {', '.join(diagnostics['missing_components'])}; add only the actual missing restraint")
    return rank

def boundary_lines(fixed_dofs):
    return [f'{n},{d},{d}' for n,dofs in sorted(fixed_dofs.items(),key=lambda pair:int(pair[0])) for d in sorted(dofs)]
