"""Independent body meshes with explicit bonded, elastic or planar contact interfaces.

Bonding uses exact quadratic displacement interpolation. Compliant interfaces
integrate positive spring energy at coincident surface quadrature points. No
body fusion, implicit contact or uncalibrated adhesive strength is inferred.
"""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from .defaults import DEFAULT_STRUCTURAL_ELEMENTS
from pathlib import Path
import json
import copy
import numpy as np
from scipy.spatial import cKDTree
from .case import keys,number,vector,selector,validate_case,sha256,write_json,CONDITIONS
from .materials import validate_material,axes
from .geometry import make_mesh,select_faces
from .robot import rotation_rpy
from .signals import digest


def tri_basis(r,s):
    l=1-r-s
    n=np.array([l*(2*l-1),r*(2*r-1),s*(2*s-1),4*l*r,4*r*s,4*s*l])
    dr=np.array([1-4*l,4*r-1,0,4*(l-r),4*s,-4*s])
    ds=np.array([1-4*l,0,4*s-1,-4*r,4*r,4*(l-s)])
    return n,dr,ds


def quadrature():
    result=[(1/3,1/3,.225)]
    for a,b,w in ((.059715871789770,.470142064105115,.132394152788506),(.797426985353087,.101286507323456,.125939180544827)):
        result.extend([(b,b,w),(a,b,w),(b,a,w)])
    return result


class SurfaceProjector:
    def __init__(self,coords,triangles,tolerance):
        self.triangles=triangles;self.points=np.array([[coords[n] for n in t] for t in triangles])
        if not len(self.points):raise ValueError('connection surface is empty')
        self.centers=self.points[:,:3,:].mean(axis=1)
        self.radii=np.linalg.norm(self.points-self.centers[:,None,:],axis=2).max(axis=1)
        self.tree=cKDTree(self.centers);self.tolerance=tolerance

    def project(self,point):
        candidates=self.tree.query_ball_point(point,self.radii.max()+self.tolerance)
        for i in sorted(candidates,key=lambda i:np.linalg.norm(point-self.centers[i])):
            p=self.points[i];uv=np.linalg.lstsq(np.c_[p[1]-p[0],p[2]-p[0]],point-p[0],rcond=None)[0]
            for _ in range(12):
                n,dr,ds=tri_basis(*uv);res=n@p-point
                delta=np.linalg.lstsq(np.c_[dr@p,ds@p],res,rcond=None)[0];uv-=delta
                if np.linalg.norm(delta)<1e-12:break
            n,_,_=tri_basis(*uv);error=np.linalg.norm(n@p-point)
            param_tolerance=self.tolerance/max(self.radii[i],1e-12)
            if error<=self.tolerance and uv.min()>=-param_tolerance and uv.sum()<=1+param_tolerance:
                return self.triangles[i],n,float(error)
        raise ValueError('connection point does not project onto the declared opposing face; check footprint/placement or refine the master mesh')


def clip_triangle(subject,clip,tolerance=1e-12):
    """Convex polygon clipping in the common interface plane."""
    clip=np.asarray(clip,float)
    cross=lambda a,b:float(a[0]*b[1]-a[1]*b[0])
    if cross(clip[1]-clip[0],clip[2]-clip[0])<0:clip=clip[::-1]
    polygon=list(np.asarray(subject,float))
    for a,b in zip(clip,np.roll(clip,-1,axis=0)):
        if not polygon:return []
        edge=b-a;output=[];previous=polygon[-1];prev=cross(edge,previous-a)
        for current in polygon:
            value=cross(edge,current-a)
            inside=value>=-tolerance;prev_inside=prev>=-tolerance
            if inside!=prev_inside:
                denominator=prev-value
                if abs(denominator)>1e-20:output.append(previous+(current-previous)*(prev/denominator))
            if inside:output.append(current)
            previous=current;prev=value
        polygon=output
    return polygon


def overlay_samples(master,slave,coords,budget):
    """Integrate each intersection of the two straight-sided planar P2 grids.

    Segmenting both grids is essential: a master basis is piecewise quadratic,
    so a quadrature rule on an unsegmented slave triangle is not exact.
    """
    origin=slave['center'];normal=np.linalg.svd(slave['points']-origin)[2][-1]
    p=np.array([coords[n] for n in slave['triangles'][0]])
    axis=p[1]-p[0];axis/=np.linalg.norm(axis);second=np.cross(normal,axis)
    basis=np.column_stack((axis,second));patches={};scale=max(np.linalg.norm(np.ptp(slave['points'],axis=0)),1.)
    for role,patch in [('master',master),('slave',slave)]:
        triangles=np.array([[coords[n] for n in t] for t in patch['triangles']])
        mids=np.stack(((triangles[:,0]+triangles[:,1])/2,(triangles[:,1]+triangles[:,2])/2,(triangles[:,2]+triangles[:,0])/2),axis=1)
        deviation=float(np.max(np.linalg.norm(triangles[:,3:]-mids,axis=2)))
        if deviation>scale*1e-9:
            raise ValueError(f'current segmented planar interfaces require straight finite-element edges; {role} midside deviation {deviation:.6g} mm exceeds {scale*1e-9:.6g} mm. For an actual flat straight-edged CAD port consider explicit mesh.preserve_boundary_nodes=true with curvature-resolving refinement; native optimizer and quality errors still reject the mesh. Curved port boundaries need an applicable supported model, not node projection.')
        uv=(triangles[:,:3]-origin)@basis;centers=uv.mean(axis=1);radii=np.linalg.norm(uv-centers[:,None,:],axis=2).max(axis=1)
        patches[role]={'uv':uv,'centers':centers,'radii':radii,'tree':cKDTree(centers)}
    m=patches['master'];s=patches['slave'];count=0;total_area=0.
    cross=lambda a,b:float(a[0]*b[1]-a[1]*b[0])
    for i,uv in enumerate(s['uv']):
        for j in m['tree'].query_ball_point(s['centers'][i],s['radii'][i]+m['radii'].max()+scale*1e-10):
            polygon=clip_triangle(uv,m['uv'][j],scale**2*1e-12)
            if len(polygon)<3:continue
            ma=m['uv'][j];s_matrix=np.c_[uv[1]-uv[0],uv[2]-uv[0]];m_matrix=np.c_[ma[1]-ma[0],ma[2]-ma[0]]
            for k in range(1,len(polygon)-1):
                triangle=np.array([polygon[0],polygon[k],polygon[k+1]])
                area=abs(cross(triangle[1]-triangle[0],triangle[2]-triangle[0]))/2
                if area<=scale**2*1e-15:continue
                for r,t,w in quadrature():
                    point=(1-r-t)*triangle[0]+r*triangle[1]+t*triangle[2]
                    source_uv=np.linalg.solve(s_matrix,point-uv[0]);master_uv=np.linalg.solve(m_matrix,point-ma[0])
                    ns=tri_basis(*source_uv)[0];nm=tri_basis(*master_uv)[0];measure=area*w
                    count+=1;total_area+=measure
                    if count>budget:raise ValueError('segmented interface quadrature exceeds declared budget')
                    yield slave['triangles'][i],ns,master['triangles'][j],nm,origin+basis@point,measure,i
    expected=[sum(abs(cross(t[1]-t[0],t[2]-t[0]))/2 for t in patches[role]['uv']) for role in ('master','slave')]
    if any(abs(total_area-a)>max(a,1.)*1e-8 for a in expected):
        raise ValueError('master/slave interface footprints do not overlap completely; no implicit contact extrapolation')


def load_assembly_case(path):
    path=Path(path).resolve();c=json.loads(path.read_text(encoding='utf-8-sig'))
    keys(c,['schema_version','bodies','connections','supports','loads','criteria','mesh','conditions','gravity','buckling','provenance','notes','probes','contact_control','bolts','stress_regions'],
         ['schema_version','bodies','connections','supports','loads','criteria','mesh','conditions'],'assembly case')
    if c['schema_version']!='assembly-1.0':raise ValueError('assembly schema_version must be assembly-1.0')
    if not isinstance(c['bodies'],list) or len(c['bodies'])<2:raise ValueError('assembly needs at least two explicit bodies')
    names=[]
    for body in c['bodies']:
        keys(body,['name','model','material','placement','mesh_size_factor','local_refinements'],['name','model','material'],'body')
        if not isinstance(body['name'],str) or not body['name']:raise ValueError('body names must be nonempty')
        names.append(body['name']);validate_material(body['material'])
        model=body['model'];keys(model,['path','expected_bbox_mm','units','scene_node','source_up_axis','pose','interface_manifest','solid_id'],['path'],'body model')
        p=(path.parent/model['path']).resolve()
        if not p.is_file() or p.suffix.lower() not in ('.step','.stp','.glb','.stl','.obj'):raise ValueError('body model must reference a supported solid/mesh')
        model['path']=str(p)
        if p.suffix.lower() in ('.stl','.obj') and 'units' not in model:raise ValueError('STL/OBJ body requires units')
        if 'interface_manifest' in model:model['interface_manifest']=str((path.parent/model['interface_manifest']).resolve())
        if 'placement' in body:
            keys(body['placement'],['translation_mm','rpy_rad'],['translation_mm','rpy_rad'],'body placement')
            vector(body['placement']['translation_mm'],'body translation');vector(body['placement']['rpy_rad'],'body rotation')
        if 'mesh_size_factor' in body:number(body['mesh_size_factor'],'mesh_size_factor',True)
    if len(set(names))!=len(names):raise ValueError('body names must be unique')
    if 'stress_regions' in c:
        from .stress_regions import validate_regions
        validate_regions(c)
    if 'probes' in c:
        from .probes import validate_probes
        validate_probes(c)
    body_names=set(names);support_names=[];load_names=[]
    for field,names_out in [('supports',support_names),('loads',load_names)]:
        if not isinstance(c[field],list) or (field=='supports' and not c[field]):raise ValueError('assembly supports required; loads must be a list')
        for item in c[field]:
            allowed=['name','body','selector']+(['total_force_n','total_moment_n_mm','application_point_mm','scalable','distribution','allow_opposite_traction'] if field=='loads' else ['dofs','service_displacement_mm'])
            keys(item,allowed,['name','body','selector']+(['total_force_n'] if field=='loads' else []),field)
            if not isinstance(item['name'],str) or not item['name'] or item['body'] not in body_names:raise ValueError('support/load references an invalid name/body')
            names_out.append(item['name']);selector(item['selector'])
            if field=='supports':
                from .constraints import support_dofs
                support_dofs(item)
                if 'service_displacement_mm' in item:
                    values=vector(item['service_displacement_mm'],'service fixture displacement')
                    if any(v and i+1 not in support_dofs(item) for i,v in enumerate(values)):raise ValueError('fixture displacement requires its DOF to be constrained')
            if field=='loads':
                from .loads import validate_distribution
                validate_distribution(item)
                f=vector(item['total_force_n'],'force');m=vector(item.get('total_moment_n_mm',[0,0,0]),'moment')
                if not any(f) and not any(m):raise ValueError('load wrench must be nonzero')
                if 'application_point_mm' in item:vector(item['application_point_mm'],'application point')
                if 'scalable' in item and type(item['scalable']) is not bool:raise ValueError('scalable must be boolean')
        if len(set(names_out))!=len(names_out):raise ValueError('support/load names must be unique')
    driven=any(any(s.get('service_displacement_mm',[0,0,0])) for s in c['supports'])
    if not c['loads'] and not c.get('gravity') and not c.get('bolts') and not driven:
        raise ValueError('assembly needs loads, gravity, explicit bolt pretension or nonzero prescribed fixture motion')
    if c.get('gravity'):
        keys(c['gravity'],['acceleration_m_s2'],['acceleration_m_s2'],'gravity');g=vector(c['gravity']['acceleration_m_s2'],'gravity')
        if not any(g):raise ValueError('gravity must be nonzero')
        if any('density_kg_m3' not in b['material'] for b in c['bodies']):raise ValueError('each gravity-loaded body needs density')
    keys(c['conditions'],[*CONDITIONS,'connection_parameters_verified'],[*CONDITIONS,'connection_parameters_verified'],'conditions')
    if any(type(v) is not bool for v in c['conditions'].values()):raise ValueError('conditions must be booleans')
    # Reuse the solid settings validator with actual first-body material/model
    # and actual declared regions. This object is validation-only, never meshed.
    first=c['bodies'][0];probe={'schema_version':'2.0','model':first['model'],'material':first['material'],
         'supports':[{k:v for k,v in s.items() if k not in ('body','service_displacement_mm')} for s in c['supports']],
         'loads':[{k:v for k,v in l.items() if k!='body'} for l in c['loads']],
         'criteria':c['criteria'],'mesh':c['mesh'],'conditions':{k:c['conditions'][k] for k in CONDITIONS}}
    for field in ('gravity','buckling'): 
        if field in c:probe[field]=c[field]
    for body in c['bodies']:
        probe['model']=body['model'];probe['material']=body['material']
        probe['mesh']=dict(c['mesh'])
        if 'local_refinements' in body:probe['mesh']['local_refinements']=body['local_refinements']
        validate_case(probe,allow_unloaded=bool(c.get('bolts')) or driven)
        suffix=Path(body['model']['path']).suffix.lower()
        if suffix in ('.step','.stp'):
            if body['model'].get('units','mm')!='mm':raise ValueError('body.model.units: STEP is imported into mm; omit units or use "mm" as the analysis-unit annotation')
            if any(k in body['model'] for k in ('scene_node','source_up_axis','pose')):
                raise ValueError('body.model: STEP carries its own frame; remove scene_node/source_up_axis/pose and inspect solid_id instead')
        if suffix not in ('.step','.stp') and 'solid_id' in body['model']:raise ValueError('mesh body uses scene_node, not STEP solid_id')
    if not isinstance(c['connections'],list) or not c['connections']:raise ValueError('explicit connections are required; no implicit fusion')
    conn_names=[];graph={n:set() for n in body_names}
    for connection in c['connections']:
        keys(connection,['name','type','master','slave','position_tolerance_mm','normal','normal_stiffness_n_mm3','tangential_stiffness_n_mm3','max_quadrature_points','calibration','initial_gap_mm','gap_convergence_tolerance_mm','friction_coefficient','max_tangential_displacement_mm','slip_convergence_tolerance_mm','footprint'],
             ['name','type','master','slave'],'connection')
        if not isinstance(connection['name'],str) or not connection['name']:raise ValueError('connection names must be nonempty')
        conn_names.append(connection['name'])
        if connection['type'] not in ('bonded','linear_interface','frictionless_contact','frictional_contact'):raise ValueError('unsupported explicit connection type')
        if 'footprint' in connection and (connection['type'] not in ('frictionless_contact','frictional_contact') or connection['footprint'] not in ('matching','slave_within_master')):
            raise ValueError('footprint must be matching or slave_within_master, for planar contact only')
        for role in ('master','slave'):
            keys(connection[role],['body','selector'],['body','selector'],'connection side')
            if connection[role]['body'] not in body_names:raise ValueError('connection references unknown body')
            selector(connection[role]['selector'])
        a,b=connection['master']['body'],connection['slave']['body']
        if a==b:raise ValueError('connection must link distinct bodies')
        graph[a].add(b);graph[b].add(a)
        number(connection.get('position_tolerance_mm',1e-4),'connection tolerance',True)
        if type(connection.get('max_quadrature_points',30000)) is not int or not 1<=connection.get('max_quadrature_points',30000)<=200000:
            raise ValueError('max_quadrature_points must be 1..200000')
        if connection['type'] in ('linear_interface','frictionless_contact','frictional_contact'):
            n=vector(connection.get('normal'),'interface normal')
            if abs(np.linalg.norm(n)-1)>1e-8:raise ValueError('interface normal must be a unit vector in assembly frame')
            number(connection.get('normal_stiffness_n_mm3'),'normal stiffness',True)
            if connection['type'] in ('linear_interface','frictional_contact'):number(connection.get('tangential_stiffness_n_mm3'),'tangential stiffness',True)
            elif 'tangential_stiffness_n_mm3' in connection:raise ValueError('frictionless contact has no tangential stiffness')
            if 'calibration' in connection:
                keys(connection['calibration'],['reference','applicability'],['reference','applicability'],'interface calibration')
                if any(not isinstance(v,str) or not v.strip() for v in connection['calibration'].values()):raise ValueError('interface calibration must be nonempty')
        elif any(k in connection for k in ('normal','normal_stiffness_n_mm3','tangential_stiffness_n_mm3')):
            raise ValueError('bonded connection has no compliance constants')
        if 'initial_gap_mm' in connection:
            if connection['type'] not in ('frictionless_contact','frictional_contact') or number(connection['initial_gap_mm'],'initial gap')<0:raise ValueError('initial_gap_mm is nonnegative and contact-only')
        if 'gap_convergence_tolerance_mm' in connection:
            if connection['type'] not in ('frictionless_contact','frictional_contact'):raise ValueError('gap tolerance is contact-only')
            number(connection['gap_convergence_tolerance_mm'],'gap convergence tolerance',True)
        if connection['type']=='frictional_contact':
            for field in ('friction_coefficient','max_tangential_displacement_mm'):number(connection.get(field),field,True)
            number(connection.get('slip_convergence_tolerance_mm',1e-5),'slip convergence tolerance',True)
            if not connection.get('calibration'):raise ValueError('frictional contact needs explicit parameter sources and applicability')
        elif any(k in connection for k in ('friction_coefficient','max_tangential_displacement_mm','slip_convergence_tolerance_mm')):raise ValueError('friction settings require frictional_contact')
    if len(set(conn_names))!=len(conn_names):raise ValueError('connection names must be unique')
    from .contact import validate_control
    validate_control(c)
    from .bolts import validate as validate_bolts
    validate_bolts(c)
    if any('service_displacement_mm' in s for s in c['supports']) and not any(j['type'] in ('frictionless_contact','frictional_contact') for j in c['connections']):raise ValueError('service fixture motion requires the staged contact backend')
    if c.get('buckling',{}).get('enabled') and any(j['type']=='linear_interface' for j in c['connections']):
        raise ValueError('elastic buckling with compliant interfaces is not qualified; current assembly buckling supports bonded planar interfaces only')
    seen={s['body'] for s in c['supports']};queue=list(seen)
    for body in queue:
        for neighbor in graph[body]-seen:seen.add(neighbor);queue.append(neighbor)
    if seen!=body_names:raise ValueError('assembly has a disconnected body/load path to supports')
    validate_cad_interfaces(c)
    return c


def validate_cad_interfaces(c):
    """Reject known curved CAD ports before allocating any volume mesh.

    This is an early rejection only. Other surfaces, mesh inputs, coplanarity,
    trimmed-footprint coverage and mesh projection retain their existing gates.
    """
    from .geometry import session, inventory
    from .bridge import resolve_interfaces
    ports={}
    for connection in c['connections']:
        for role in ('master','slave'):
            side=connection[role]
            # Plane selectors already require a constant-coordinate full face
            # during mesh selection. Avoid extra STEP imports for that common
            # path; explicit face IDs and named interfaces need the early check.
            if side['selector']['type']!='plane':
                ports.setdefault(side['body'],[]).append((connection,role))
    for body in c['bodies']:
        model=body['model'];path=Path(model['path'])
        if body['name'] not in ports or path.suffix.lower() not in ('.step','.stp'):continue
        with session(path,model) as g:
            info=inventory(g,path)
            if model.get('interface_manifest'):
                info['interfaces']=resolve_interfaces(model['interface_manifest'],info)
            faces={f['id']:f for f in info['faces']}
            for connection,role in ports[body['name']]:
                ids=select_faces(info,connection[role]['selector'])
                curved=[(i,faces[i]['type']) for i in ids if faces[i]['type'].lower() in ('cylinder','cone','sphere','torus')]
                if curved:
                    raise ValueError(f"Connection {connection['name']} {role} body {body['name']} selects curved CAD faces {curved}; "
                        "current assembly interfaces require planar patches. Cylindrical bore contact and other curved contact are unsupported. "
                        "Retain the unresolved interface in the task plan or select an applicable external contact method; do not replace it with a plane or fuse the bodies.")


def source_signature(c):
    return digest([{'name':b['name'],'sha256':sha256(Path(b['model']['path'])),'placement':b.get('placement')} for b in c['bodies']])


def compile_interfaces(c,coords,body_data,fixed,node_start,element_start,tets=None):
    equations=[];springs=[];aux={};reports=[];dependent=set();dependencies={};occupied=set()
    node_id=node_start;element_id=element_start;contacts=[];contact_index=None
    for spec in c['connections']:
        tol=spec.get('position_tolerance_mm',1e-4);patch={}
        for role in ('master','slave'):
            side=spec[role];data=body_data[side['body']]
            faces=select_faces(data['local_geometry'],side['selector']);triangles=[t for f in faces for t in data['surfaces'][f]]
            if not triangles:raise ValueError('empty connection patch')
            nodes=sorted({n for t in triangles for n in t});points=np.array([coords[n] for n in nodes])
            center=points.mean(axis=0);singular=np.linalg.svd(points-center,compute_uv=False)
            if singular[-1]>max(singular[0],1.)*1e-9:raise ValueError('current assembly interfaces require planar patches')
            patch[role]={'triangles':triangles,'nodes':nodes,'points':points,'faces':faces,'center':center,
                         'projector':SurfaceProjector(coords,triangles,tol)}
            for face in faces:
                label=(side['body'],face)
                if label in occupied:raise ValueError('connection patches overlap; do not define duplicate interface energy/constraints')
                occupied.add(label)
        master,slave=patch['master'],patch['slave']
        if spec['type'] in ('frictionless_contact','frictional_contact'):
            from .contact import compile_contact,surface_index
            if tets is None:raise ValueError('contact requires actual volume connectivity')
            if contact_index is None:contact_index=surface_index(tets)
            contact=compile_contact(spec,patch,coords,tets,contact_index,bodies=c['bodies'],body_data=body_data)
            contacts.append(contact);reports.append({k:v for k,v in contact.items() if k not in ('surfaces','gap_samples')})
            continue
        # Both directions must cover the same footprint; equal bounding boxes
        # alone would not detect different holes. Every interpolation is checked
        # for partition of unity and exact position to preserve rigid motion.
        errors=[]
        for a,b in ((master,slave),(slave,master)):
            for point in a['points']:
                _,_,error=b['projector'].project(point);errors.append(error)
        scale=max(np.linalg.norm(np.ptp(slave['points'],axis=0)),1.)
        rigid_tolerance=scale*1e-8
        if max(errors)>rigid_tolerance:raise ValueError('connection planes are not coincident; offsets would violate rigid-motion/force-moment consistency')
        samples=0;area_total=0.
        def interpolation(point):
            ns,w,error=master['projector'].project(point)
            if abs(w.sum()-1)>1e-9 or np.linalg.norm(sum((coords[n]*v for n,v in zip(ns,w)),np.zeros(3))-point)>rigid_tolerance:
                raise ValueError('interface interpolation fails rigid translation/rotation reproduction')
            return ns,w
        # Positive diagonal scaling of local P2 dual test functions. This avoids
        # zero corner lumped-force weights and keeps the transfer operator local.
        reference_mass=sum((w*np.outer(tri_basis(r,s)[0],tri_basis(r,s)[0]) for r,s,w in quadrature()),np.zeros((6,6)))
        dual_transform=np.linalg.inv(reference_mass)/6.
        if spec['type']=='bonded':
            transfer={n:{} for n in slave['nodes']};diagonal={n:0. for n in slave['nodes']}
            for tri in slave['triangles']:
                p=np.array([coords[n] for n in tri]);area=np.linalg.norm(np.cross(p[1]-p[0],p[2]-p[0]))/2
                for n in tri:diagonal[n]+=area/6.
            for sn,ns,mn,nm,point,measure,_ in overlay_samples(master,slave,coords,spec.get('max_quadrature_points',30000)):
                dual=dual_transform@ns;samples+=1;area_total+=measure
                for i,n in enumerate(sn):
                    for j,k in enumerate(mn):transfer[n][k]=transfer[n].get(k,0.)+float(measure*dual[i]*nm[j])
            for n in slave['nodes']:
                if n in fixed:raise ValueError('bonded slave node is fixed; reverse the master/slave choice or revise overlapping supports')
                ns=list(transfer[n]);w=np.array([transfer[n][k]/diagonal[n] for k in ns])
                if abs(w.sum()-1)>1e-8 or np.linalg.norm(sum((coords[k]*v for k,v in zip(ns,w)),np.zeros(3))-coords[n])>rigid_tolerance:
                    raise ValueError('dual interface transfer failed rigid-motion reproduction')
                for dof in (1,2,3):
                    dep=(n,dof)
                    if dep in dependent:raise ValueError('a bonded dependent DOF is defined more than once')
                    dependent.add(dep);terms=[(n,dof,1.)]+[(k,dof,-float(v)) for k,v in zip(ns,w) if abs(v)>1e-14]
                    equations.append(terms);dependencies[dep]=[t[:2] for t in terms[1:]]
        else:
            normal=np.array(spec['normal']);basis_seed=np.eye(3)[np.argmin(np.abs(normal))]
            tangent=np.cross(normal,basis_seed);tangent/=np.linalg.norm(tangent)
            basis=[normal,tangent,np.cross(normal,tangent)]
            surface_normal=np.cross(slave['points'][1]-slave['points'][0],slave['points'][2]-slave['points'][0])
            # SVD handles arbitrary node ordering and collinear first nodes.
            surface_normal=np.linalg.svd(slave['points']-slave['center'])[2][-1]
            if abs(np.dot(normal,surface_normal))<1-1e-8:raise ValueError('declared interface normal is not normal to its plane')
            for tri,shape,ns,mw,point,measure,_ in overlay_samples(master,slave,coords,spec.get('max_quadrature_points',30000)):
                area_total+=measure;samples+=1
                for axis,direction in enumerate(basis):
                    node_id+=1;element_id+=1;aux[str(node_id)]=point.tolist()
                    terms=[(node_id,1,1.)]
                    for n,value in zip(tri,shape):terms.extend((int(n),d+1,-float(value*direction[d])) for d in range(3) if abs(value*direction[d])>1e-14)
                    for n,value in zip(ns,mw):terms.extend((int(n),d+1,float(value*direction[d])) for d in range(3) if abs(value*direction[d])>1e-14)
                    equations.append(terms)
                    stiffness=spec['normal_stiffness_n_mm3'] if axis==0 else spec['tangential_stiffness_n_mm3']
                    springs.append({'node':node_id,'element':element_id,'stiffness_n_mm':float(stiffness*measure),'connection':spec['name']})
        reports.append({'name':spec['name'],'type':spec['type'],'master_body':spec['master']['body'],'slave_body':spec['slave']['body'],
                        'max_projection_error_mm':max(errors),'rigid_motion_tolerance_mm':rigid_tolerance,
                        'quadrature_points':samples,'integrated_area_mm2':area_total if samples else None,
                        'calibration':spec.get('calibration'),'meaning':'Explicit ideal displacement bond or linear reversible interface; no joint/adhesive failure prediction'})
    active=set();done=set()
    def visit(dep):
        if dep in active:raise ValueError('bonded constraint dependency cycle; choose consistent master/slave surfaces')
        if dep in done:return
        active.add(dep)
        for target in dependencies.get(dep,[]):
            if target in dependencies:visit(target)
        active.remove(dep);done.add(dep)
    for dep in dependencies:visit(dep)
    return {'equations':equations,'springs':springs,'auxiliary_nodes':aux,'reports':reports,'contacts':contacts}


def check_body_overlap(c,body_data,coords):
    """Reject volume penetration; Boolean results never replace analysis bodies."""
    import trimesh
    from .geometry import session
    records=[];cached={}
    for i,a in enumerate(c['bodies']):
        for b in c['bodies'][i+1:]:
            da,db=body_data[a['name']],body_data[b['name']]
            pa=np.array([coords[n] for ts in da['surfaces'].values() for t in ts for n in t]);pb=np.array([coords[n] for ts in db['surfaces'].values() for t in ts for n in t])
            depth=np.minimum(pa.max(axis=0),pb.max(axis=0))-np.maximum(pa.min(axis=0),pb.min(axis=0))
            if depth.min()<=max(np.linalg.norm(np.ptp(pa,axis=0)),np.linalg.norm(np.ptp(pb,axis=0)),1.)*1e-9:
                records.append({'bodies':[a['name'],b['name']],'method':'bounding boxes disjoint/touching','overlap_volume_mm3':0.});continue
            if da.get('brep') and db.get('brep'):
                with session() as g:
                    shapes=[]
                    for body,data in ((a,da),(b,db)):
                        shape=g.model.occ.importShapes(data['brep']);placement=body.get('placement',{'translation_mm':[0,0,0],'rpy_rad':[0,0,0]})
                        matrix=np.eye(4);matrix[:3,:3]=rotation_rpy(placement['rpy_rad']);matrix[:3,3]=placement['translation_mm']
                        g.model.occ.affineTransform(shape,matrix.ravel().tolist());shapes.append(shape)
                    common,_=g.model.occ.intersect(shapes[0],shapes[1]);g.model.occ.synchronize()
                    volume=sum(g.model.occ.getMass(d,t) for d,t in common if d==3)
                method='exact OpenCASCADE intersection of isolated imported bodies'
            else:
                for body,data in ((a,da),(b,db)):
                    if body['name'] in cached:continue
                    triangles=[]
                    for ts in data['surfaces'].values():
                        for t in ts:
                            triangles.extend([[t[k] for k in f] for f in ((0,3,5),(3,1,4),(5,4,2),(3,4,5))])
                    ids=sorted({n for t in triangles for n in t});index={n:j for j,n in enumerate(ids)}
                    surface=trimesh.Trimesh(vertices=[coords[n] for n in ids],faces=[[index[n] for n in t] for t in triangles],process=False)
                    surface.fix_normals() # Orientation of analysis-derived display facets only; no geometry repair.
                    if not surface.is_volume:raise ValueError('cannot verify body penetration from closed analysis-derived surface')
                    cached[body['name']]=surface
                intersection=trimesh.boolean.intersection([cached[a['name']],cached[b['name']]],engine='manifold',check_volume=True)
                volume=float(intersection.volume) if intersection is not None else 0.
                method='Manifold intersection of analysis-derived facets; curved STEP boundaries are tessellated in mixed-format pairs'
            tolerance=max(min(da['local_geometry']['volume_mm3'],db['local_geometry']['volume_mm3'])*1e-9,1e-9)
            if not np.isfinite(volume) or volume>tolerance:raise ValueError(f"assembly bodies {a['name']} and {b['name']} penetrate by {volume} mm3; no implicit union/contact repair")
            records.append({'bodies':[a['name'],b['name']],'method':method,'overlap_volume_mm3':float(volume),'volume_tolerance_mm3':tolerance})
    return records


def make_assembly_mesh(c,h,out):
    if c['mesh'].get('local_refinements'):raise ValueError('local_refinements currently targets a single solid; analyze a source-bound component case separately')
    coords={};tets={};fixed=set();fixed_dofs={};forces={};fixed_forces={};materials={};element_material={};body_data={}
    surface_tri=[];surface_faces=[];faces=[];support_faces={};loads=[];body_reports=[];volume=0.;mass=0.;com_weight=np.zeros(3);mass_known=True
    node_id=0;element_id=0;face_id=0;force_scale=0.;element_sicn={};element_det={}
    for i,body in enumerate(c['bodies']):
        placement=body.get('placement',{'translation_mm':[0,0,0],'rpy_rad':[0,0,0]});rotation=rotation_rpy(placement['rpy_rad']);translation=np.array(placement['translation_mm'])
        directory=out/f'body-{i+1:02d}';directory.mkdir()
        local={'schema_version':'2.0','model':body['model'],'material':body['material'],'criteria':c['criteria'],'mesh':c['mesh'],'conditions':c['conditions'],
               'supports':[{k:v for k,v in s.items() if k not in ('body','service_displacement_mm')} for s in c['supports'] if s['body']==body['name']], 'loads':[]}
        if 'local_refinements' in body:local['mesh']=dict(c['mesh'],local_refinements=body['local_refinements'])
        for load in c['loads']:
            if load['body']!=body['name']:continue
            l=copy.deepcopy(load);l.pop('body');l['total_force_n']=(rotation.T@l['total_force_n']).tolist()
            if 'total_moment_n_mm' in l:l['total_moment_n_mm']=(rotation.T@l['total_moment_n_mm']).tolist()
            if 'application_point_mm' in l:l['application_point_mm']=(rotation.T@(np.array(l['application_point_mm'])-translation)).tolist()
            local['loads'].append(l)
        if c.get('gravity'):local['gravity']={'acceleration_m_s2':(rotation.T@c['gravity']['acceleration_m_s2']).tolist()}
        mesh=make_mesh(local,h*body.get('mesh_size_factor',1.),directory,allow_free_body=True,load_to_support_axes=rotation);xyz,elements,fix,f,meta=mesh
        data=np.load(directory/'mesh.npz');node_map={n:node_id+j+1 for j,n in enumerate(sorted(xyz))};element_map={e:element_id+j+1 for j,e in enumerate(sorted(elements))}
        quality_index={int(e):j for j,e in enumerate(data['element_ids'])}
        quality_sicn=data['element_min_sicn'];quality_det=data['element_min_det_jac']
        element_sicn.update({element_map[e]:float(quality_sicn[quality_index[e]]) for e in elements})
        element_det.update({element_map[e]:float(quality_det[quality_index[e]]) for e in elements})
        node_id+=len(xyz);element_id+=len(elements)
        if element_id>c['mesh'].get('max_elements',DEFAULT_STRUCTURAL_ELEMENTS):raise ValueError('combined body mesh exceeds max_elements')
        coords.update({node_map[n]:rotation@p+translation for n,p in xyz.items()})
        tets.update({element_map[e]:[node_map[n] for n in ns] for e,ns in elements.items()});fixed.update(node_map[n] for n in fix)
        for n,ds in meta.get('fixed_dofs',{str(n):[1,2,3] for n in fix}).items():
            fixed_dofs[str(node_map[int(n)])]=ds
        forces.update({node_map[n]:rotation@v for n,v in f.items()});fixed_forces.update({node_map[int(n)]:rotation@v for n,v in meta['fixed_nodal_forces'].items()})
        material_id=f'MAT{i:03d}';material=copy.deepcopy(body['material'])
        if 'orientation' in material or material.get('failure_criterion')=='max_stress':
            r=rotation@axes(material);material['orientation']={'axis_1':r[:,0].tolist(),'axis_2':r[:,1].tolist()}
        materials[material_id]=material;element_material.update({str(element_map[e]):material_id for e in elements})
        face_map={};surfaces={}
        for face in meta['geometry']['faces']:
            face_id+=1;fid=face['id'];face_map[fid]=face_id;mask=data['surface_face_ids']==fid
            triangles=[[node_map[int(n)] for n in tri] for tri in data['surface_tri6'][mask]];surfaces[fid]=triangles
            surface_tri.extend(triangles);surface_faces.extend([face_id]*len(triangles))
            points=np.array([coords[n] for t in triangles for n in t]);record=copy.deepcopy(face)
            record.update(id=face_id,body=body['name'],local_face_id=fid,centroid_mm=(rotation@face['centroid_mm']+translation).tolist(),
                          bbox_mm=np.r_[points.min(axis=0),points.max(axis=0)].tolist());faces.append(record)
        for name,fs in meta['support_faces'].items():support_faces[name]=[face_map[f] for f in fs]
        for load in meta['loads']:
            report=copy.deepcopy(load);report['body']=body['name'];report['face_ids']=[face_map[f] for f in load['face_ids']]
            report['centroid_mm']=(rotation@load['centroid_mm']+translation).tolist();report['total_force_n']=(rotation@load['total_force_n']).tolist()
            report['traction_mpa']=(rotation@load['traction_mpa']).tolist()
            report['total_moment_n_mm_about_patch_centroid']=(rotation@load['total_moment_n_mm_about_patch_centroid']).tolist()
            if report.get('distribution_diagnostic'):
                diagnostic=report['distribution_diagnostic']
                diagnostic.update(coordinate_frame='body_local_mm',body=body['name'],body_placement=placement)
            loads.append(report)
        v=meta['mesh_volume_mm3'];volume+=v;force_scale+=meta['load_force_scale_n']
        density=body['material'].get('density_kg_m3')
        if density is None:mass_known=False
        else:
            m=v*density*1e-9;mass+=m;com_weight+=m*(rotation@meta['geometry']['center_of_mass_mm']+translation)
        body_data[body['name']]={'local_geometry':meta['geometry'],'surfaces':surfaces,
                                'placement':placement,
                                'brep':str((directory/'geometry.brep').resolve()) if (directory/'geometry.brep').is_file() else None}
        body_reports.append({'name':body['name'],'material_id':material_id,'source_geometry':meta['geometry'],'directory':str(directory.resolve()),'node_count':len(xyz),'element_count':len(elements),'placement':placement})
    from .constraints import check_rigid_modes
    check_rigid_modes(coords,fixed_dofs)
    overlap=check_body_overlap(c,body_data,coords)
    connections=compile_interfaces(c,coords,body_data,fixed,node_id,element_id,tets)
    if not force_scale:force_scale=sum(b['preload_n'] for b in c.get('bolts',[]))
    from .bolts import compile_bolts
    compile_bolts(c,coords,body_data,connections,max([node_id,*map(int,connections['auxiliary_nodes'])]),max([element_id,*[s['element'] for s in connections['springs']]]))
    service_boundary={};prescribed={}
    for support in c['supports']:
        from .constraints import support_dofs
        data=body_data[support['body']];fs=select_faces(data['local_geometry'],support['selector'])
        for n in {n for f in fs for tri in data['surfaces'][f] for n in tri}:
            for dof in support_dofs(support):
                key=f'{n}:{dof}';value=support.get('service_displacement_mm',[0,0,0])[dof-1]
                if key in prescribed and prescribed[key]!=value:raise ValueError('conflicting prescribed fixture motion, including stationary supports')
                prescribed[key]=value
                if value:service_boundary[key]=value
    points=np.array(list(coords.values()));geometry={'geometry_sha256':source_signature(c),'units':'mm','solid_count':len(c['bodies']),
        'volume_mm3':volume,'bbox_mm':[points.min(axis=0).tolist(),points.max(axis=0).tolist()],'faces':faces,
        'center_of_mass_mm':(com_weight/mass).tolist() if mass_known and mass else None,'meaning':'Independent explicit bodies; volumes are summed, never fused'}
    meta={'geometry':geometry,'mesh_size_mm':h,'node_count':len(coords),'element_count':len(tets),'element_type':'C3D10',
        'materials':materials,'element_material':element_material,'body_reports':body_reports,'connection_data':connections,
        'body_overlap_check':overlap,'service_boundary':service_boundary,
        'support_faces':support_faces,'fixed_node_count':len(fixed),'fixed_dofs':fixed_dofs,'loads':loads,'mesh_volume_mm3':volume,'mass_kg':mass if mass_known else None,
        'applied_force_n':sum(forces.values(),np.zeros(3)).tolist(),'applied_moment_n_mm':sum((np.cross(coords[n],f) for n,f in forces.items()),np.zeros(3)).tolist(),
        'fixed_nodal_forces':{str(n):v.tolist() for n,v in fixed_forces.items()},'load_force_scale_n':force_scale}
    np.savez_compressed(out/'mesh.npz',node_ids=np.array(list(coords)),xyz=points,element_ids=np.array(list(tets)),connectivity=np.array(list(tets.values())),
                        surface_tri6=np.array(surface_tri),surface_face_ids=np.array(surface_faces),
                        element_min_sicn=np.array([element_sicn[e] for e in tets]),element_min_det_jac=np.array([element_det[e] for e in tets]))
    write_json(out/'mesh.json',meta)
    write_json(out/'load_distribution.json',{'coordinate_frame':'assembly_world_mm',
        'nodes':[{'id':int(n),'xyz_mm':coords[n].tolist(),'force_n':f.tolist()} for n,f in forces.items()],
        'loads':[load.get('distribution_diagnostic',{}) for load in loads],
        'body_evidence':[{'body':b['name'],'path':str(Path(b['directory'])/'load_distribution.json')} for b in body_reports]})
    return coords,tets,sorted(fixed),forces,meta


def connection_deck(data):
    lines=[]
    if data.get('contacts'):
        from .contact import deck
        lines+=deck(data['contacts'])
    if data['auxiliary_nodes']:
        lines+=['*NODE,NSET=INTERFACE_AUX']+[str(n)+','+','.join(f'{v:.12g}' for v in xyz) for n,xyz in data['auxiliary_nodes'].items()]
        lines+=['*BOUNDARY','INTERFACE_AUX,2,3']
    if data.get('bolts'):
        lines+=['*NSET,NSET=BOLT_STATE',','.join(str(b[k]) for b in data['bolts'] for k in ('stretch_node','adjustment_node'))]
    for terms in data['equations']:
        lines+=['*EQUATION',str(len(terms))]
        for i in range(0,len(terms),4):lines.append(','.join(f'{n},{dof},{value:.12e}' for n,dof,value in terms[i:i+4]))
    for i,spring in enumerate(data['springs']):
        name=f'ISPR{i}'
        lines += [f'*ELEMENT,TYPE=SPRING1,ELSET={name}',f"{spring['element']},{spring['node']}",
                  f'*SPRING,ELSET={name}','1',f"{spring['stiffness_n_mm']:.12e}"]
    return lines


def analyze_assembly(path,out,ccx=None,timeout=DEFAULT_NATIVE_TIMEOUT,preview=True,*,progress=None,cache=None,reuse_levels=None,predict_capacity=True):
    from .workflow import analyze
    c=load_assembly_case(path)
    return analyze(Path(path),Path(out),ccx,timeout,preview,prepared_case=c,mesh_factory=make_assembly_mesh,source_signature=lambda:source_signature(c),progress=progress,cache=cache,reuse_levels=reuse_levels,predict_capacity=predict_capacity)
