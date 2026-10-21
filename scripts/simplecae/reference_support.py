"""Six pure gauge equations for a single self-balanced elastic solid.

Material points use the actual quadratic element map. This supplies no fixture,
contact or inertial relief and refuses any nonzero resultant wrench.
"""
import numpy as np
from .case import keys,vector,sha256

def validate(case):
    if not case.get('reference_only',False):return
    if case['schema_version']!='2.0' or case.get('bodies') or case.get('buckling',{}).get('enabled'):
        raise ValueError('reference_only supports one solid, static analysis only')
    count=0
    for spec in case['supports']:
        keys(spec,['name','point_mm','dofs','geometry_sha256'],['name','point_mm','dofs','geometry_sha256'],'reference support')
        vector(spec['point_mm'],'reference material point')
        from .constraints import support_dofs
        count+=len(support_dofs(spec))
        if not isinstance(spec['geometry_sha256'],str) or len(spec['geometry_sha256'])!=64:raise ValueError('reference support needs current geometry_sha256')
    if count!=6:raise ValueError('reference_only requires exactly six independent translation equations')
    if case['criteria'].get('max_displacement_mm') is not None:
        raise ValueError('reference_only global displacement depends on the numerical gauge; set its limit to null')
    limited=[p for p in case.get('probes',[]) if p.get('max_displacement_mm')]
    if not limited or any(p['type']!='relative_length' for p in limited):
        raise ValueError('reference_only displacement criteria require gauge-invariant relative_length probes')

def rigid_basis(points):
    points=np.asarray(points,dtype=float);center=points.mean(axis=0)
    length=max(float(np.linalg.norm(np.ptp(points,axis=0))),1e-12)
    r=(points-center)/length
    matrix=np.zeros((len(points),3,6));matrix[:,:,:3]=np.eye(3)
    for i,(x,y,z) in enumerate(r):matrix[i,:,3:]=[[0,z,-y],[-z,0,x],[y,-x,0]]
    return matrix.reshape(-1,6)

def balanced(coords,forces,meta,tolerance=1e-8):
    scale=meta['load_force_scale_n'];length=max(float(np.linalg.norm(np.ptp(list(coords.values()),axis=0))),1e-12)
    force=sum(forces.values(),np.zeros(3))
    moment=sum((np.cross(coords[n],f) for n,f in forces.items()),np.zeros(3))
    if scale<=0 or np.linalg.norm(force)>scale*tolerance or np.linalg.norm(moment)>scale*length*tolerance:
        raise ValueError('reference_only requires a self-balanced total force AND moment, including gravity and fixed-load subcases; add the actual physical reaction/load path')

def prepare(case,coords,tets,source_hash):
    from .probes import PointSampler
    from .constraints import support_dofs
    from scipy.linalg import qr
    sampler=PointSampler(coords,tets);samples=[];rows=[]
    for spec in case['supports']:
        if spec['geometry_sha256']!=source_hash:raise ValueError('reference support belongs to a different geometry hash')
        sample=sampler.locate(spec['point_mm']);samples.append(dict(sample,name=spec['name'],dofs=spec['dofs']))
        for dof in support_dofs(spec):
            rows.append({(n,dof):w for n,w in zip(sample['node_ids'],sample['weights']) if abs(w)>1e-14})
    columns=sorted({key for row in rows for key in row})
    matrix=np.array([[row.get(key,0.) for key in columns] for row in rows])
    nodes=sorted({n for n,_ in columns});index={n:i for i,n in enumerate(nodes)}
    basis=rigid_basis([coords[n] for n in nodes]);selected=np.array([basis[3*index[n]+d-1] for n,d in columns])
    values=np.linalg.svd(matrix@selected,compute_uv=False)
    if values[-1]<=values[0]*1e-10:raise ValueError('reference supports do not independently remove all six rigid modes')
    _,_,pivots=qr(matrix,mode='economic',pivoting=True);dependent=list(pivots[:6])
    reduced=np.linalg.solve(matrix[:,dependent],matrix)
    reduced[:,dependent]=np.eye(6)
    equations=[]
    for i,pivot in enumerate(dependent):
        rest=[(*columns[j],float(reduced[i,j])) for j in range(len(columns)) if j not in dependent and abs(reduced[i,j])>1e-14]
        equations.append([(*columns[pivot],1.),*rest])
    return {'equations':equations,'samples':samples,'rank':6,'singular_values':values.tolist(),
        'method':'Six material-point C3D10 homogeneous equations, algebraically reduced to unique dependent DOFs',
        'physical_fixture':False,'reaction_nodes':nodes}

def equation_deck(data):
    lines=[]
    for terms in data['equations']:
        lines+=['*EQUATION',str(len(terms))]
        for i in range(0,len(terms),4):lines.append(','.join(f'{n},{d},{v:.12e}' for n,d,v in terms[i:i+4]))
    return lines

def summarize(data,coords,displacements,reactions,forces,meta):
    residual=max(abs(sum(v*displacements[n][d-1] for n,d,v in terms)) for terms in data['equations'])
    if residual>1e-6:raise RuntimeError('reference equation displacement residual exceeded 1e-6 mm')
    norms=sum(np.linalg.norm(reactions[n]-forces.get(n,np.zeros(3))) for n in reactions)
    if norms/meta['load_force_scale_n']>meta.get('reference_reaction_tolerance',5e-4):
        raise RuntimeError('reference constraints carry significant force; the solve is not a pure numerical gauge')
    nodes=sorted(coords);u=np.array([displacements[n] for n in nodes]);basis=rigid_basis([coords[n] for n in nodes])
    rigid=basis@np.linalg.lstsq(basis,u.ravel(),rcond=None)[0]
    deformation=u-rigid.reshape(-1,3)
    return {'reference_equation_residual_mm':float(residual),'reference_reaction_norm_n':float(norms),
        'deformation_displacement_mm':float(np.linalg.norm(deformation,axis=1).max()),
        'deformation_displacement_method':'Maximum after unweighted least-squares removal of six rigid modes from all mesh nodes; used only for the small-response screen',
        'reference_only':True}
