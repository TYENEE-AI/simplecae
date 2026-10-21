"""Named displacement measurements on actual C3D10 fields; no nearest-node snap."""
from copy import deepcopy
import numpy as np
from .case import keys,number,vector
from .loads import tetra10_basis

EDGES=((0,1),(1,2),(2,0),(0,3),(1,3),(2,3))
GRAD_L=np.array([[-1.,-1.,-1.],[1,0,0],[0,1,0],[0,0,1]])

def validate_probes(case):
    specs=case.get('probes',[])
    if not isinstance(specs,list):raise ValueError('probes must be a list')
    robot=case['schema_version']=='robot-1.0'
    assembly=case['schema_version']=='assembly-1.0'
    names=[];points=set();bodies={b['name'] for b in case.get('bodies',[])}
    for spec in specs:
        if not isinstance(spec,dict):raise ValueError('each probe must be an object')
        common=['name','type','direction','max_displacement_mm','absolute_convergence_tolerance_mm','convergence_required']
        if spec.get('type')=='point':
            allowed=common+(['link','point_m'] if robot else ['body','point_mm']);required=['name','type']+(['link','point_m'] if robot else ['point_mm'])
        elif spec.get('type')=='surface_average':
            allowed=common+(['link','component_selector'] if robot else ['body','selector']);required=['name','type']+(['link','component_selector'] if robot else ['selector'])
        else:allowed=common+['from_probe','to_probe'];required=['name','type','from_probe','to_probe']
        keys(spec,allowed,required,'probe')
        if not isinstance(spec['name'],str) or not spec['name'].strip():raise ValueError('probe name must be nonempty')
        names.append(spec['name'])
        if spec['type'] in ('point','surface_average'):
            points.add(spec['name'])
            if spec['type']=='point':vector(spec['point_m' if robot else 'point_mm'],'probe point')
            else:
                from .case import selector
                selector(spec['component_selector' if robot else 'selector'])
            if robot and (not isinstance(spec['link'],str) or not spec['link']):raise ValueError('robot probe needs a link name')
            if assembly and spec.get('body') not in bodies:raise ValueError('assembly point probe needs an explicit known body')
            if not assembly and not robot and 'body' in spec:raise ValueError('body is for assembly probes; solid probes use analysis coordinates')
        elif spec['type'] not in ('relative','relative_length'):raise ValueError('probe type must be point, surface_average, relative or relative_length')
        if spec['type']=='relative_length' and robot:raise ValueError('relative_length is currently a solid/assembly field measurement; robot task probes use relative with explicit direction')
        if spec['type']=='relative_length' and 'direction' in spec:raise ValueError('relative_length derives direction from initial sample separation; omit direction')
        if 'direction' in spec:
            d=np.array(vector(spec['direction'],'probe direction'))
            if not np.isclose(np.linalg.norm(d),1,rtol=0,atol=1e-8):raise ValueError('probe direction must be a unit vector')
        for field in ('max_displacement_mm','absolute_convergence_tolerance_mm'):
            if field in spec:number(spec[field],'probe '+field,True)
        if 'convergence_required' in spec and type(spec['convergence_required']) is not bool:raise ValueError('probe convergence_required must be boolean')
    if len(set(names))!=len(names):raise ValueError('probe names must be unique')
    for spec in specs:
        if spec['type'] in ('relative','relative_length'):
            if spec['from_probe'] not in points or spec['to_probe'] not in points or spec['from_probe']==spec['to_probe']:
                raise ValueError('relative probe must reference two distinct named point probes')
    return specs

def basis_gradient(q):
    l=np.r_[1-np.sum(q),q]
    return np.vstack([(4*l[i]-1)*GRAD_L[i] for i in range(4)]+
                     [4*(l[i]*GRAD_L[j]+l[j]*GRAD_L[i]) for i,j in EDGES])

class PointSampler:
    def __init__(self,coords,tets):
        self.coords=coords;self.elements=sorted(tets);self.connectivity=[tets[e] for e in self.elements]
        self.xyz=np.array([[coords[n] for n in nodes] for nodes in self.connectivity])
        # Bernstein control points enclose the entire curved quadratic map,
        # unlike a bounding box of just the physical corner/midside nodes.
        controls=self.xyz.copy()
        for k,(i,j) in enumerate(EDGES):controls[:,4+k]=2*self.xyz[:,4+k]-.5*(self.xyz[:,i]+self.xyz[:,j])
        self.lo=controls.min(axis=1);self.hi=controls.max(axis=1)

    def locate(self,point,allowed_elements=None):
        p=np.asarray(point,dtype=float);scale=max(float(np.linalg.norm(np.ptp(self.xyz.reshape(-1,3),axis=0))),1.)
        tol=scale*1e-10
        candidates=np.flatnonzero(np.all(p>=self.lo-tol,axis=1)&np.all(p<=self.hi+tol,axis=1))
        for index in candidates:
            element=self.elements[index]
            if allowed_elements is not None and element not in allowed_elements:continue
            xyz=self.xyz[index];edge_scale=max(float(np.linalg.norm(np.ptp(xyz,axis=0))),1e-12)
            try:
                q=np.linalg.solve((xyz[1:4]-xyz[0]).T,p-xyz[0])
                for _ in range(25):
                    n=tetra10_basis(q[None,:])[0];residual=p-n@xyz
                    if np.linalg.norm(residual)<=tol:break
                    q+=np.linalg.solve(xyz.T@basis_gradient(q),residual)
                    if not np.all(np.isfinite(q)) or np.linalg.norm(q)>100:break
                n=tetra10_basis(q[None,:])[0];l=np.r_[1-q.sum(),q]
                if np.linalg.norm(n@xyz-p)>tol or l.min() < -tol/edge_scale or l.max()>1+tol/edge_scale:continue
                jacobian=float(np.linalg.det(xyz.T@basis_gradient(q)))
                if jacobian<=edge_scale**3*1e-14:raise ValueError('probe mapping has a non-positive or nearly singular Jacobian; inspect the actual mesh/geometry')
            except np.linalg.LinAlgError:continue
            return {'element':int(element),'node_ids':[int(x) for x in self.connectivity[index]],
                    'weights':n.tolist(),'natural_coordinates':q.tolist(),'mapping_residual_mm':float(np.linalg.norm(n@xyz-p)),
                    'point_mm':p.tolist(),'mapping_jacobian_determinant_mm3':jacobian,'method':'C3D10 isoparametric quadratic interpolation'}
        raise ValueError(f'probe point {p.tolist()} is outside the selected finite-element body; select a point on/in modeled material, not an omitted pad or a nearby node')

def surface_sample(case,mesh,spec,path):
    from .geometry import select_faces,integrate_tri6
    coords,_,_,_,meta=mesh
    if path is None:raise ValueError('surface-average probes need the actual surface mesh from this solve')
    info=meta['geometry']
    if case['schema_version']=='assembly-1.0':
        body=next(b for b in meta['body_reports'] if b['name']==spec['body'])
        local=select_faces(body['source_geometry'],spec['selector'])
        faces=[f['id'] for f in info['faces'] if f['body']==spec['body'] and f['local_face_id'] in local]
    else:faces=select_faces(info,spec['selector'])
    with np.load(path,allow_pickle=False) as data:
        triangles=data['surface_tri6'][np.isin(data['surface_face_ids'],faces)]
    integrals={};area=0.;first=np.zeros(3)
    for tri in triangles:
        weights,a,moment=integrate_tri6(np.array([coords[int(n)] for n in tri]));area+=a;first+=moment
        for n,w in zip(tri,weights):integrals[int(n)]=integrals.get(int(n),0.)+float(w)
    if not np.isfinite(area) or area<=0:raise ValueError('surface-average probe has no positive finite material area')
    nodes=sorted(integrals)
    return {'node_ids':nodes,'weights':[integrals[n]/area for n in nodes],'point_mm':(first/area).tolist(),'area_mm2':area,'face_ids':faces,
        'method':'Area-weighted quadratic surface displacement',
        'point_meaning':'Area centroid may be in a hole; this is a material-surface average, not displacement at the centroid.'}

def prepare_context(case,mesh,surface_path=None):
    specs=validate_probes(case)
    if not specs:return None
    coords,tets,_,_,meta=mesh;sampler=PointSampler(coords,tets) if any(p['type']=='point' for p in specs) else None;samples={}
    for spec in specs:
        if spec['type'] in ('relative','relative_length'):continue
        if spec['type']=='surface_average':
            samples[spec['name']]=surface_sample(case,mesh,spec,surface_path);continue
        point=np.array(spec['point_mm'],dtype=float);elements=None
        if case['schema_version']=='assembly-1.0':
            from .assembly import rotation_rpy
            body=next(b for b in case['bodies'] if b['name']==spec['body']);placement=body.get('placement',{})
            point=rotation_rpy(placement.get('rpy_rad',[0,0,0]))@point+placement.get('translation_mm',[0,0,0])
            material=next(b['material_id'] for b in meta['body_reports'] if b['name']==spec['body'])
            elements={int(e) for e,m in meta['element_material'].items() if m==material}
        samples[spec['name']]=sampler.locate(point,elements)
    return {'specs':deepcopy(specs),'samples':samples}

def evaluate_context(context,nodal_displacement):
    if context is None:return []
    vectors={};records={}
    for spec in context['specs']:
        if spec['type'] in ('relative','relative_length'):continue
        sample=context['samples'][spec['name']]
        vectors[spec['name']]=sum((w*np.asarray(nodal_displacement(n)) for n,w in zip(sample['node_ids'],sample['weights'])),np.zeros(3))
        records[spec['name']]=dict(sample,name=spec['name'],type=spec['type'],body=spec.get('body'))
    return records_from_vectors(context['specs'],vectors,records)

def records_from_vectors(specs,vectors,records):
    vectors=dict(vectors);records=deepcopy(records)
    for spec in specs:
        if spec['type'] in ('relative','relative_length'):
            vectors[spec['name']]=vectors[spec['to_probe']]-vectors[spec['from_probe']]
            records[spec['name']]={'name':spec['name'],'type':spec['type'],'from_probe':spec['from_probe'],'to_probe':spec['to_probe'],
                'from_point_mm':records[spec['from_probe']]['point_mm'],'to_point_mm':records[spec['to_probe']]['point_mm'],
                'meaning':'Change in separation from modeled elastic displacement only; excludes omitted pad, joint, mount and fixture compliance.'}
    for spec in specs:
        rec=records[spec['name']];u=vectors[spec['name']];magnitude=float(np.linalg.norm(u))
        rec.update(displacement_vector_mm=u.tolist(),displacement_norm_mm=magnitude)
        if spec['type']=='relative_length' or 'direction' in spec:
            if spec['type']=='relative_length':
                initial=np.array(rec['to_point_mm'])-rec['from_point_mm'];length=float(np.linalg.norm(initial))
                if length<=1e-12:raise ValueError('relative_length needs distinct initial sample locations')
                direction=initial/length;rec.update(initial_length_mm=length,gauge_invariant=True,meaning='First-order signed change in sample separation; rigid translation and infinitesimal rotation cancel. Excludes omitted joint, contact and pad compliance.')
            else:direction=spec['direction']
            projection=float(np.dot(u,direction));rec.update(direction=list(direction),signed_projection_mm=projection,value_mm=abs(projection))
        else:rec['value_mm']=magnitude
        rec['allowable_displacement_mm']=spec.get('max_displacement_mm')
        rec['utilization']=rec['value_mm']/spec['max_displacement_mm'] if spec.get('max_displacement_mm') else None
        rec['absolute_convergence_tolerance_mm']=spec.get('absolute_convergence_tolerance_mm',1e-9)
    return [records[s['name']] for s in specs]

def evaluate_probes(case,mesh,fields):
    from pathlib import Path
    directory=fields.get('_source_directory')
    context=prepare_context(case,mesh,Path(directory)/'mesh.npz' if directory else None);fields['_probe_context']=context
    return evaluate_context(context,lambda n:fields['displacements'][n])

def scaled_probes(full,fixed,factor):
    def value(n):
        base=fixed['displacements'][n] if fixed else np.zeros(3)
        return base+factor*(full['displacements'][n]-base)
    return evaluate_context(full.get('_probe_context'),value)

def stiffness_utilization(metrics,allowable):
    values=[metrics['max_displacement_mm']/allowable] if allowable else []
    values += [p['utilization'] for p in metrics.get('probes',[]) if p.get('utilization') is not None]
    return max(values) if values else None

def convergence(previous,current,tolerance):
    old={p['name']:p for p in previous};answer={}
    for p in current:
        if p['name'] not in old:raise ValueError('probe identity changed during refinement')
        a,b=old[p['name']],p
        if 'signed_projection_mm' in b:
            delta=abs(b['signed_projection_mm']-a['signed_projection_mm']);denom=abs(b['signed_projection_mm'])
        else:
            delta=float(np.linalg.norm(np.array(b['displacement_vector_mm'])-a['displacement_vector_mm']));denom=b['displacement_norm_mm']
        relative=delta/max(denom,1e-30)
        answer[p['name']]={'relative_change':relative,'absolute_change_mm':delta,
            'converged':relative<=tolerance or delta<=b['absolute_convergence_tolerance_mm']}
    return answer
