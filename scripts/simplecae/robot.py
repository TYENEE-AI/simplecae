"""URDF SI-frame kinematics, static wrench propagation and ground equilibrium.

Rigid statics does not establish link strength. Optional component FEM uses
explicit support/load ports and the same declared gravity/payload contract.
"""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from pathlib import Path
import json
import copy
import html
import re
import hashlib
import numpy as np
from scipy.optimize import linprog
from defusedxml import ElementTree as ET
from .case import keys,number,vector,selector,sha256,write_json,load_case

ROBOT_CONDITIONS=('inertials_verified','actuator_ratings_verified','mount_verified','poses_verified')


def xml_vector(text,default=(0,0,0)):
    values=[float(v) for v in text.split()] if text is not None else list(default)
    return np.array(vector(values,'URDF vector'))


def rotation_rpy(rpy):
    r,p,y=rpy; cr,sr=np.cos(r),np.sin(r);cp,sp=np.cos(p),np.sin(p);cy,sy=np.cos(y),np.sin(y)
    return np.array([[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr],
                     [sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr],[-sp,cp*sr,cp*cr]])


def transform(xyz=(0,0,0),rpy=(0,0,0)):
    t=np.eye(4);t[:3,:3]=rotation_rpy(rpy);t[:3,3]=xyz
    return t


def origin(element):
    e=element.find('origin')
    return transform(xml_vector(e.get('xyz')) if e is not None else [0,0,0],
                     xml_vector(e.get('rpy')) if e is not None else [0,0,0])


def rotation_axis(axis,angle):
    x,y,z=axis; skew=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
    return np.eye(3)+np.sin(angle)*skew+(1-np.cos(angle))*(skew@skew)


def resolve_asset(uri,urdf_path,package_roots):
    if uri.startswith('package://'):
        parts=uri[len('package://'):].split('/',1)
        if len(parts)!=2 or parts[0] not in package_roots:
            raise ValueError(f'URDF package URI needs a declared package root: {uri}')
        base=Path(package_roots[parts[0]]).resolve(); path=(base/parts[1]).resolve()
        if not path.is_relative_to(base): raise ValueError('package asset escapes its package root')
    elif '://' in uri:
        raise ValueError('URDF mesh URI must be relative/local or use a declared package root')
    else:
        path=Path(uri);path=(urdf_path.parent/path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_file(): raise ValueError(f'URDF mesh asset does not exist: {path}')
    return path


def read_urdf(path,package_roots=None,massless_links=()):
    path=Path(path).resolve(); text=path.read_text(encoding='utf-8-sig')
    if '$(' in text or '${' in text: raise ValueError('expand xacro before URDF analysis')
    root=ET.fromstring(text)
    if root.tag!='robot': raise ValueError('URDF root must be robot; for MJCF use simplecae import-mjcf MODEL.xml --out out/cae/mjcf and review its handoff.json before analysis')
    links={};assets=[];joints={};parents={};children={}
    for e in root.findall('link'):
        name=e.get('name')
        if not name or name in links: raise ValueError('URDF links need unique nonempty names')
        inertial=e.find('inertial')
        if inertial is None:
            if name not in massless_links: raise ValueError(f'link {name} has no inertial; declare massless explicitly or supply mass/COM/inertia')
            mass=0.;com=np.zeros(3);inertia=np.zeros((3,3))
        else:
            mass_e=inertial.find('mass');i=inertial.find('inertia')
            if mass_e is None or i is None: raise ValueError(f'incomplete inertial for {name}')
            mass=number(float(mass_e.get('value')),'URDF mass')
            if mass<0: raise ValueError('URDF mass cannot be negative')
            inertial_frame=origin(inertial)
            com=inertial_frame[:3,3]
            values={k:number(float(i.get(k)),'URDF inertia') for k in ('ixx','iyy','izz','ixy','ixz','iyz')}
            inertia=np.array([[values['ixx'],values['ixy'],values['ixz']],[values['ixy'],values['iyy'],values['iyz']],[values['ixz'],values['iyz'],values['izz']]])
            principal=np.linalg.eigvalsh(inertia)
            if (mass>0 and principal[0]<=0) or principal[0]<-1e-12 or principal[-1]>principal[:2].sum()+1e-10:
                raise ValueError(f'nonphysical inertia tensor for {name}')
            if mass==0 and (name not in massless_links or np.linalg.norm(inertia)>1e-12):
                raise ValueError('zero-mass link must be explicitly massless with zero inertia')
            # URDF tensors are about the COM in the inertial-origin axes.
            # Store about the same COM, expressed in link axes (no translation).
            inertia=inertial_frame[:3,:3]@inertia@inertial_frame[:3,:3].T
        links[name]={'mass_kg':mass,'com_m':com,'inertia_kg_m2':inertia,'visuals':[]};children[name]=[]
        for kind in ('visual','collision'):
            for visual in e.findall(kind):
                geom=visual.find('geometry')
                if geom is None or len(geom)!=1: raise ValueError(f'{kind} geometry must contain one shape')
                item=geom[0]
                if item.tag=='mesh':
                    asset=resolve_asset(item.get('filename',''),path,package_roots or {})
                    scale=xml_vector(item.get('scale'),(1,1,1))
                    if np.any(scale<=0): raise ValueError('URDF mesh scale must be positive')
                    assets.append({'link':name,'kind':kind,'path':str(asset),'sha256':sha256(asset),'scale':scale.tolist(),'origin':origin(visual).tolist()})
                elif item.tag=='box':
                    if np.any(xml_vector(item.get('size'))<=0): raise ValueError('URDF box size must be positive')
                elif item.tag in ('cylinder','sphere'):
                    number(float(item.get('radius')),'URDF radius',True)
                    if item.tag=='cylinder': number(float(item.get('length')),'URDF length',True)
                else: raise ValueError(f'unsupported URDF geometry {item.tag}')
                if kind=='visual':
                    parameters=({'path':str(asset),'scale':scale.tolist()} if item.tag=='mesh' else
                                {'size':xml_vector(item.get('size')).tolist()} if item.tag=='box' else
                                {'radius':float(item.get('radius')),'length':float(item.get('length','0'))})
                    links[name]['visuals'].append({'shape':item.tag,'parameters':parameters,'origin':origin(visual).tolist()})
    if not links or set(massless_links)-set(links): raise ValueError('empty robot or unknown massless link')
    for e in root.findall('joint'):
        name=e.get('name');kind=e.get('type')
        if not name or name in joints: raise ValueError('URDF joints need unique nonempty names')
        if kind not in ('fixed','revolute','continuous','prismatic'): raise ValueError(f'unsupported joint type {kind}; explicit fixed-base scalar-joint poses are required')
        p=e.find('parent');c=e.find('child')
        if p is None or c is None: raise ValueError('joint needs parent and child')
        parent=p.get('link');child=c.get('link')
        if parent not in links or child not in links or parent==child or child in parents:
            raise ValueError('joint references invalid links or child has multiple parents')
        axis_e=e.find('axis');axis=xml_vector(axis_e.get('xyz') if axis_e is not None else None,(1,0,0))
        if np.linalg.norm(axis)<1e-12: raise ValueError('joint axis must be nonzero')
        axis=axis/np.linalg.norm(axis)
        lim=e.find('limit');effort=None;lower=None;upper=None
        if kind!='fixed' and lim is not None:
            if lim.get('effort') is not None: effort=number(float(lim.get('effort')),'effort limit',True)
            if lim.get('lower') is not None: lower=number(float(lim.get('lower')),'lower limit')
            if lim.get('upper') is not None: upper=number(float(lim.get('upper')),'upper limit')
        if kind in ('revolute','prismatic') and (lower is None or upper is None or upper<lower):
            raise ValueError('bounded joints require ordered lower and upper limits')
        mimic_e=e.find('mimic');mimic=None
        if mimic_e is not None:
            if kind=='fixed': raise ValueError('fixed joint cannot mimic')
            mimic={'joint':mimic_e.get('joint'),'multiplier':number(float(mimic_e.get('multiplier','1')),'mimic multiplier'),
                   'offset':number(float(mimic_e.get('offset','0')),'mimic offset')}
        joints[name]={'name':name,'type':kind,'parent':parent,'child':child,'origin':origin(e),'axis':axis,
                      'effort_limit':effort,'lower':lower,'upper':upper,'mimic':mimic}
        parents[child]=name;children[parent].append(name)
    roots=set(links)-set(parents)
    if len(roots)!=1: raise ValueError('URDF must have one connected tree root')
    base=next(iter(roots));visited=set();active=set()
    def visit(link):
        if link in active: raise ValueError('URDF joint cycle')
        active.add(link);visited.add(link)
        for j in children[link]: visit(joints[j]['child'])
        active.remove(link)
    visit(base)
    if visited!=set(links): raise ValueError('URDF contains disconnected links or a cycle')
    for j in joints.values():
        if j['mimic']:
            target=joints.get(j['mimic']['joint'])
            if target is None or target['type']=='fixed' or (j['type']=='prismatic')!=(target['type']=='prismatic'):
                raise ValueError('mimic target is missing or has incompatible coordinates')
    return {'name':root.get('name','robot'),'path':str(path),'sha256':sha256(path),'links':links,'joints':joints,
            'handoff_warnings':(['URDF references 3MF visuals. For component FEM provide <link_name>.step for each analyzed link, then use robot-link-models; retain visual scale but never rescale native STEP by 0.001.'] if any(Path(a['path']).suffix.lower()=='.3mf' for a in assets) else []),
            'root':base,'children':children,'parents':parents,'assets':assets}


def forward_kinematics(robot,positions,base_pose=None):
    if set(positions)-set(robot['joints']): raise ValueError('pose contains unknown joints')
    q={};drivers={};resolving=set()
    def position(name):
        if name in q:return q[name]
        if name in resolving: raise ValueError('mimic joint cycle')
        resolving.add(name);j=robot['joints'][name]
        if j['type']=='fixed':
            value=0.;driver=None;coefficient=0.
            if name in positions: raise ValueError('do not assign a fixed joint position')
        elif j['mimic']:
            if name in positions: raise ValueError('mimic positions are derived; set their independent driver')
            m=j['mimic'];value=m['multiplier']*position(m['joint'])+m['offset']
            driver,coef=drivers[m['joint']];coefficient=coef*m['multiplier']
        else:
            if name not in positions:raise ValueError(f'pose must explicitly specify {name}')
            value=number(positions[name],'joint position');driver=name;coefficient=1.
        if j['type'] in ('revolute','prismatic') and not j['lower']-1e-10<=value<=j['upper']+1e-10:
            raise ValueError(f'joint {name} pose lies outside its URDF limits')
        q[name]=value;drivers[name]=(driver,coefficient);resolving.remove(name);return value
    for name in robot['joints']:position(name)
    frames={robot['root']:base_pose if base_pose is not None else np.eye(4)};joint_frames={};axes={}
    def walk(parent):
        for name in robot['children'][parent]:
            j=robot['joints'][name];t=frames[parent]@j['origin'];joint_frames[name]=t
            axes[name]=t[:3,:3]@j['axis'];motion=np.eye(4)
            if j['type'] in ('revolute','continuous'):motion[:3,:3]=rotation_axis(j['axis'],q[name])
            elif j['type']=='prismatic':motion[:3,3]=j['axis']*q[name]
            frames[j['child']]=t@motion;walk(j['child'])
    walk(robot['root'])
    return {'frames':frames,'joint_frames':joint_frames,'axes':axes,'positions':q,'drivers':drivers}


def static_wrenches(robot,kin,gravity,payloads=(),loads=()):
    frames=kin['frames'];external={};mass_points=[]
    for link,data in robot['links'].items():
        t=frames[link];point=t[:3,:3]@data['com_m']+t[:3,3];f=data['mass_kg']*np.asarray(gravity)
        external[link]=np.r_[f,np.cross(point-t[:3,3],f)]
        if data['mass_kg']:mass_points.append((data['mass_kg'],point))
    for payload in payloads:
        link=payload['link'];t=frames[link];point=t[:3,:3]@np.array(payload['center_m'])+t[:3,3]
        f=payload['mass_kg']*np.asarray(gravity);external[link]+=np.r_[f,np.cross(point-t[:3,3],f)]
        if payload['mass_kg']:mass_points.append((payload['mass_kg'],point))
    for load in loads:
        link=load['link'];t=frames[link];f=np.array(load['force_n']);m=np.array(load.get('moment_n_m',[0,0,0]));point=np.array(load['position_m'])
        if load.get('frame','link')=='link':f=t[:3,:3]@f;m=t[:3,:3]@m
        if load.get('position_frame',load.get('frame','link'))=='link':point=t[:3,:3]@point+t[:3,3]
        external[link]+=np.r_[f,m+np.cross(point-t[:3,3],f)]
    subtree={}
    def collect(link):
        w=external[link].copy()
        for name in robot['children'][link]:
            child=robot['joints'][name]['child'];child_w=collect(child)
            w[:3]+=child_w[:3];w[3:]+=child_w[3:]+np.cross(frames[child][:3,3]-frames[link][:3,3],child_w[:3])
        subtree[link]=w;return w
    total=collect(robot['root']);efforts={};actuators={};joint_wrenches={}
    for name,j in robot['joints'].items():
        w=subtree[j['child']].copy();w[3:]+=np.cross(frames[j['child']][:3,3]-kin['joint_frames'][name][:3,3],w[:3])
        joint_wrenches[name]=w
        if j['type']!='fixed':
            efforts[name]=-float(kin['axes'][name]@(w[:3] if j['type']=='prismatic' else w[3:]))
            driver,coefficient=kin['drivers'][name]
            actuators[driver]=actuators.get(driver,0.)+coefficient*efforts[name]
    world_wrench=total.copy();world_wrench[3:]+=np.cross(frames[robot['root']][:3,3],world_wrench[:3])
    mass=sum(m for m,p in mass_points)
    return {'external':external,'subtree':subtree,'joint_wrenches':joint_wrenches,'joint_efforts':efforts,
            'actuator_efforts':actuators,'world_external_wrench':world_wrench,
            'mass_kg':mass,'center_of_mass_world_m':sum((m*p for m,p in mass_points),np.zeros(3))/mass if mass else None}


def contact_equilibrium(points,friction,wrench,variable_wrench=None):
    points=np.asarray(points,dtype=float);n=len(points)
    if points.ndim!=2 or points.shape[1]!=3 or n<3 or not np.all(np.isfinite(points)) or np.linalg.matrix_rank(points[:,:2]-points[0,:2])<2:
        raise ValueError('contacts need at least three noncollinear finite support points')
    if np.ptp(points[:,2])>1e-8:raise ValueError('current contact model requires one horizontal ground plane')
    number(friction,'friction coefficient',True)
    a=np.zeros((6,3*n));b=[]
    for i,p in enumerate(points):
        a[:3,3*i:3*i+3]=np.eye(3)
        x,y,z=p;a[3:,3*i:3*i+3]=[[0,-z,y],[z,0,-x],[-y,x,0]]
        for sx,sy in ((1,1),(1,-1),(-1,1),(-1,-1)):
            row=np.zeros(3*n);row[3*i:3*i+3]=[sx,sy,-friction];b.append(row)
    bounds=[bound for _ in range(n) for bound in [(None,None),(None,None),(0,None)]]
    objective=np.zeros(3*n)
    if variable_wrench is not None:
        a=np.c_[a,variable_wrench];b=np.c_[b,np.zeros(4*n)];bounds.append((0,None));objective=np.r_[objective,-1.]
    solution=linprog(objective,A_ub=np.asarray(b),b_ub=np.zeros(4*n),A_eq=a,b_eq=-np.asarray(wrench),bounds=bounds,method='highs')
    if solution.status==3 and variable_wrench is not None:return {'feasible':True,'payload_scale_limit':None,'unbounded':True,'meaning':'declared ideal point-contact equilibrium only'}
    if solution.status==2:return {'feasible':False,'payload_scale_limit':None,'solver_status':solution.status,'message':solution.message}
    if not solution.success:raise RuntimeError(f'contact LP numerical failure: {solution.status} {solution.message}')
    residual=np.linalg.norm(a@solution.x+np.asarray(wrench))/max(np.linalg.norm(wrench),1.)
    if residual>1e-7:raise RuntimeError('contact solution failed independent equilibrium residual')
    return {'feasible':True,'contact_forces_n':solution.x[:3*n].reshape(n,3).tolist(),
            'payload_scale_limit':float(solution.x[-1]) if variable_wrench is not None else None,
            'relative_equilibrium_residual':float(residual),'friction_model':'conservative diamond |fx|+|fy| <= mu*fz; fz>=0',
            'meaning':'ideal static point contacts; no dynamic balance, ground/foot strength or compliance'}


def load_robot_case(path):
    path=Path(path).resolve();c=json.loads(path.read_text(encoding='utf-8-sig'))
    keys(c,['schema_version','model','poses','gravity_m_s2','payloads','loads','base','base_pose','massless_links','conditions',
            'effort_safety_factor','effort_limits','components','required_components','provenance','notes','grasp','probes','actuation_reactions','elastic_transfer'],
         ['schema_version','model','poses','gravity_m_s2','base','conditions'],'robot case')
    if c['schema_version']!='robot-1.0':raise ValueError('robot schema_version must be robot-1.0')
    keys(c['model'],['path','package_roots'],['path'],'robot model')
    urdf=(path.parent/c['model']['path']).resolve();c['model']['path']=str(urdf)
    if not urdf.is_file() or urdf.suffix.lower()!='.urdf':raise ValueError('robot model must reference URDF; translate MJCF with simplecae import-mjcf MODEL.xml --out out/cae/mjcf, then review frames and explicit inertials')
    packages=c['model'].get('package_roots',{})
    if not isinstance(packages,dict):raise ValueError('package_roots must be an object')
    c['model']['package_roots']={n:str((path.parent/p).resolve()) for n,p in packages.items()}
    vector(c['gravity_m_s2'],'gravity')
    if not any(c['gravity_m_s2']):raise ValueError('robot gravity must be nonzero')
    if number(c.get('effort_safety_factor',1.5),'effort safety factor')<1:raise ValueError('effort safety factor must be >=1')
    if not isinstance(c.get('massless_links',[]),list) or any(not isinstance(n,str) for n in c.get('massless_links',[])):
        raise ValueError('massless_links must be a list of link names')
    keys(c['conditions'],ROBOT_CONDITIONS,ROBOT_CONDITIONS,'robot conditions')
    if any(type(v) is not bool for v in c['conditions'].values()):raise ValueError('robot conditions must be booleans')
    if not isinstance(c['poses'],list) or not c['poses']:raise ValueError('robot case requires explicit poses')
    names=[]
    for pose in c['poses']:
        keys(pose,['name','joints'],['name','joints'],'robot pose')
        if not isinstance(pose['name'],str) or not pose['name'] or not isinstance(pose['joints'],dict):raise ValueError('pose needs a name and joint coordinate object')
        names.append(pose['name'])
        for value in pose['joints'].values():number(value,'joint position')
    if len(set(names))!=len(names):raise ValueError('pose names must be unique')
    if 'base_pose' in c:
        keys(c['base_pose'],['xyz_m','rpy_rad'],['xyz_m','rpy_rad'],'base_pose')
        vector(c['base_pose']['xyz_m'],'base position');vector(c['base_pose']['rpy_rad'],'base rotation')
    base=c['base'];keys(base,['type','points_world_m','friction_coefficient'],['type'],'base')
    if base['type'] not in ('fixed','contacts'):raise ValueError('base type must be fixed or contacts')
    if base['type']=='contacts':
        if not isinstance(base.get('points_world_m'),list):raise ValueError('contacts need points_world_m')
        for p in base['points_world_m']:vector(p,'contact point')
        number(base.get('friction_coefficient'),'friction coefficient',True)
    elif set(base)!= {'type'}:raise ValueError('fixed base has no contact options')
    for field in ('payloads','loads'):
        if not isinstance(c.get(field,[]),list):raise ValueError(f'{field} must be a list')
        names=[]
        for item in c.get(field,[]):
            allowed=['name','link','mass_kg','center_m','scalable'] if field=='payloads' else ['name','link','force_n','moment_n_m','position_m','frame','position_frame','scalable']
            required=['name','link','mass_kg','center_m'] if field=='payloads' else ['name','link','force_n','position_m']
            keys(item,allowed,required,field)
            if any(not isinstance(item[k],str) or not item[k] for k in ('name','link')):raise ValueError('load/payload names and links must be nonempty strings')
            names.append(item['name'])
            if 'scalable' in item and type(item['scalable']) is not bool:raise ValueError('scalable must be boolean')
            if field=='payloads':number(item['mass_kg'],'payload mass',True);vector(item['center_m'],'payload center')
            else:
                vector(item['force_n'],'force');vector(item.get('moment_n_m',[0,0,0]),'moment');vector(item['position_m'],'position')
                if item.get('frame','link') not in ('link','world'):raise ValueError('load frame must be link/world')
                if item.get('position_frame',item.get('frame','link')) not in ('link','world'):raise ValueError('load position_frame must be link/world')
                if not any(item['force_n']) and not any(item.get('moment_n_m',[])):raise ValueError('external wrench must be nonzero')
        if len(names)!=len(set(names)):raise ValueError(f'{field} names must be unique')
    if len({p['name'] for field in ('payloads','loads') for p in c.get(field,[])})!=sum(len(c.get(f,[])) for f in ('payloads','loads')):
        raise ValueError('payload and load names must be distinct')
    for component in c.get('components',[]):
        keys(component,['link','case_path','ports','port_load_policies','mass_relative_tolerance','com_tolerance_mm','link_from_component'],['link','case_path','ports'],'component')
        component['case_path']=str((path.parent/component['case_path']).resolve())
        if not Path(component['case_path']).is_file():raise ValueError('component case does not exist')
        if not isinstance(component['ports'],dict):raise ValueError('component ports must be an object')
        for p in component['ports'].values():selector(p)
        policies=component.get('port_load_policies',{})
        if not isinstance(policies,dict) or set(policies)-set(component['ports']):raise ValueError('port_load_policies must name existing component ports')
        from .loads import validate_distribution
        for policy in policies.values():
            keys(policy,['distribution','allow_opposite_traction','reference'],['reference'],'port load policy')
            validate_distribution(policy)
            if not isinstance(policy['reference'],str) or not policy['reference'].strip():raise ValueError('port load policy needs a physical load-path reference')
        if not 0<number(component.get('mass_relative_tolerance',.02),'component mass tolerance')<1:raise ValueError('component mass tolerance must be in (0,1)')
        if 'com_tolerance_mm' in component:number(component['com_tolerance_mm'],'COM tolerance',True)
        if 'link_from_component' in component:
            keys(component['link_from_component'],['xyz_m','rpy_rad'],['xyz_m','rpy_rad'],'component frame')
            vector(component['link_from_component']['xyz_m'],'component position');vector(component['link_from_component']['rpy_rad'],'component rotation')
    if not isinstance(c.get('required_components',[]),list):raise ValueError('required_components must be a link-name list')
    if not isinstance(c.get('effort_limits',{}),dict):raise ValueError('effort_limits must be an object')
    for limit in c.get('effort_limits',{}).values():number(limit,'motor effort limit',True)
    if 'grasp' in c:
        from .grasp import validate_grasp
        validate_grasp(c)
    if 'probes' in c:
        from .probes import validate_probes
        validate_probes(c)
    from .actuation import validate_reactions
    validate_reactions(c)
    from .elastic_transfer import validate as validate_elastic
    validate_elastic(c)
    return c


def analyze_robot(path,out,ccx=None,timeout=DEFAULT_NATIVE_TIMEOUT,preview=True,*,progress=None,cache=None,reuse_levels=None,predict_capacity=True):
    from .progress import emit
    from . import __version__
    if not isinstance(predict_capacity,bool):raise ValueError('predict_capacity must be a boolean')
    if not predict_capacity and (cache is not None or reuse_levels is not None):raise ValueError('capacity-disabled caching is not qualified; use a fresh solve without cache/reuse-levels')
    path=Path(path).resolve();out=Path(out).resolve();c=load_robot_case(path);out.mkdir(parents=True,exist_ok=False)
    result={'schema_version':'robot-result-1.0','toolkit_version':__version__,'analysis':'urdf_static','case':c,'analysis_options':{'predict_capacity':predict_capacity},
            'source_case_sha256':sha256(path),'source_urdf_sha256':sha256(Path(c['model']['path'])),'poses':[],
            'whole_installation_status':'not_assessed','not_assessed':['Dynamics, acceleration, impact and control stability','Joint/mount/ground strength and compliance','Detailed contact stress and friction calibration','Unspecified link FEM and material/manufacturing behavior']}
    try:
        from .signals import robot_contract
        from .sources import SourceGuard,source_paths
        guard=SourceGuard(source_paths(c)|{path})
        component_sources={component['case_path']:sha256(Path(component['case_path'])) for component in c.get('components',[])}
        component_models={}
        for component in c.get('components',[]):
            template=load_case(Path(component['case_path']));model=template['model']['path']
            component_models[model]=sha256(Path(model))
        robot=read_urdf(c['model']['path'],c['model']['package_roots'],c.get('massless_links',[]))
        from .elastic_transfer import validate as validate_elastic
        validate_elastic(c,robot)
        guard.add([a['path'] for a in robot['assets']])
        if any(guard.hashes[a['path']]!=a['sha256'] for a in robot['assets']):
            raise RuntimeError('URDF mesh asset changed while reading the robot')
        result['source_files_sha256']=guard.hashes
        result['task_contract']=copy.deepcopy(robot_contract(c,robot))
        result['assets']=robot['assets'];links=robot['links'];joints=robot['joints']
        result['handoff_warnings']=robot.get('handoff_warnings',[])
        if any(p['link'] not in links for f in ('payloads','loads') for p in c.get(f,[])):raise ValueError('load/payload references unknown link')
        component_names=[p['link'] for p in c.get('components',[])]
        if len(set(component_names))!=len(component_names) or set(component_names)-set(links):raise ValueError('components must reference unique known links')
        if set(c.get('required_components',[]))-set(component_names):raise ValueError('required component FEM is missing')
        if any(p['type']!='relative' and p['link'] not in component_names for p in c.get('probes',[])):
            raise ValueError('robot task-point probes require explicit FEM for each referenced link; a rigid URDF does not provide deformation')
        if set(c.get('effort_limits',{}))-set(joints):raise ValueError('effort override names an unknown joint')
        for j in c.get('effort_limits',{}):
            if joints[j]['type']=='fixed' or joints[j]['mimic']:raise ValueError('motor effort overrides apply to independent moving joints')
        base_pose=transform(**{'xyz':c['base_pose']['xyz_m'],'rpy':c['base_pose']['rpy_rad']}) if c.get('base_pose') else np.eye(4)
        limits=[];all_status=[];conditions=all(c['conditions'].values())
        for i,pose in enumerate(c['poses']):
            emit(progress,'pose',pose=pose['name'],index=i+1,poses=len(c['poses']))
            guard.check()
            directory=out/f'pose-{i+1:02d}';directory.mkdir()
            kin=forward_kinematics(robot,pose['joints'],base_pose)
            full=static_wrenches(robot,kin,c['gravity_m_s2'],c.get('payloads',[]),c.get('loads',[]))
            fixed=static_wrenches(robot,kin,c['gravity_m_s2'],[p for p in c.get('payloads',[]) if not p.get('scalable',True)],
                                  [p for p in c.get('loads',[]) if not p.get('scalable',True)])
            from .actuation import closed_statics,reaction_summary
            path_full=closed_statics(robot,c,kin,full)
            path_fixed=closed_statics(robot,c,kin,fixed,fixed=True)
            reactions=reaction_summary(path_full)
            effort_results={};upper=float('inf');fixed_ok=True;known_efforts=True
            for name,value in full['actuator_efforts'].items():
                rated=c.get('effort_limits',{}).get(name,joints[name]['effort_limit'])
                allowed=rated/c.get('effort_safety_factor',1.5) if rated else None
                effort_results[name]={'holding_effort':value,'units':'N' if joints[name]['type']=='prismatic' else 'N m',
                                      'declared_limit':rated,'allowable':allowed,'utilization':abs(value)/allowed if allowed else None,
                                      'includes_mimic_virtual_work':True}
                if allowed is None:known_efforts=False;continue
                f=fixed['actuator_efforts'][name];v=value-f
                if abs(f)>allowed+1e-12:fixed_ok=False
                if abs(v)>1e-12:upper=min(upper,max(0.,(allowed-np.sign(v)*f)/abs(v)))
            contact=None;contact_limit=None
            if c['base']['type']=='contacts':
                args=(c['base']['points_world_m'],c['base']['friction_coefficient'])
                contact=contact_equilibrium(*args,full['world_external_wrench'])
                contact_limit=contact_equilibrium(*args,fixed['world_external_wrench'],full['world_external_wrench']-fixed['world_external_wrench'])
                if not contact_equilibrium(*args,fixed['world_external_wrench'])['feasible']:fixed_ok=False
                if contact_limit['feasible'] and contact_limit.get('payload_scale_limit') is not None:upper=min(upper,contact_limit['payload_scale_limit'])
            fem=[]
            for component in c.get('components',[]):
                guard.check()
                fem.append(component_analysis(robot,c,component,kin,path_full,path_fixed,directory,ccx,timeout,preview,progress=progress,cache=cache,reuse_levels=reuse_levels,predict_capacity=predict_capacity))
                guard.check()
                for omission in fem[-1].get('assessment',{}).get('not_assessed',[]):
                    scoped=f"Component {component['link']}: {omission}"
                    if scoped not in result['not_assessed']:result['not_assessed'].append(scoped)
                limit=fem[-1]['assessment']['conditional_body_limit'] if fem[-1].get('assessment') else None
                if limit and limit['available']:upper=min(upper,limit['load_pattern_scale_factor'])
            grasp=None
            if c.get('grasp'):
                from .grasp import assess_grasp
                grasp=assess_grasp(c,kin)
                if grasp['payload_scale_limit'] is not None:upper=min(upper,grasp['payload_scale_limit'])
            task_probes=None
            if c.get('probes') and not any(f['status']=='invalid' for f in fem):
                from .robot_probes import measure
                task_probes=measure(c,kin,fem,robot=robot)
                if not predict_capacity:
                    task_probes['payload_scale_limit']=None
                    task_probes['conditional_limit_eligible']=False
                if task_probes['payload_scale_limit'] is not None:upper=min(upper,task_probes['payload_scale_limit'])
                fixed_ok=fixed_ok and task_probes['fixed_loads_alone_pass']
            failed=any((e['utilization'] or 0)>1 for e in effort_results.values()) or (contact is not None and not contact['feasible']) or any(f['status']=='fail_under_stated_model' for f in fem) or (grasp is not None and not grasp['feasible']) or (task_probes is not None and task_probes['status']=='fail_under_stated_model')
            unresolved=not known_efforts or any(f['status'] in ('invalid','indeterminate') for f in fem) or (task_probes is not None and task_probes['status']=='indeterminate')
            status='invalid' if any(f['status']=='invalid' for f in fem) else 'indeterminate' if unresolved else 'fail_under_stated_model' if failed else 'pass_under_stated_model'
            capacity_ok=predict_capacity and conditions and fixed_ok and known_efforts and all(f.get('assessment',{}).get('conditional_body_limit',{}).get('available',False) for f in fem)
            if grasp is not None:capacity_ok=capacity_ok and all(grasp['conditions'].values())
            if grasp is not None and grasp.get('model')=='finite_pad_wrench' and fem:
                capacity_ok=capacity_ok and grasp['declared_component_load_pattern_checked']
            if task_probes is not None:capacity_ok=capacity_ok and task_probes['conditional_limit_eligible']
            if reactions['declared']:capacity_ok=capacity_ok and reactions['declared_paths_verified']
            if c.get('elastic_transfer'):capacity_ok=False
            if contact_limit is not None and not contact_limit['feasible']:capacity_ok=False
            finite_limit=float(upper) if np.isfinite(upper) and capacity_ok else None
            limits.append(finite_limit);all_status.append(status)
            record={'name':pose['name'],'status':status,'joint_positions':kin['positions'],
                    'link_frames_world':{n:t.tolist() for n,t in kin['frames'].items()},
                    'link_centers_of_mass_world_m':{n:(kin['frames'][n][:3,:3]@d['com_m']+kin['frames'][n][:3,3]).tolist() for n,d in links.items()},
                    'joint_origins_world_m':{n:t[:3,3].tolist() for n,t in kin['joint_frames'].items()},
                    'joint_axes_world':{n:v.tolist() for n,v in kin['axes'].items()},'actuator_efforts':effort_results,
                    'joint_local_holding_efforts':full['joint_efforts'],
                    'subtree_external_wrenches_world':{n:v.tolist() for n,v in full['subtree'].items()},
                    'joint_support_wrenches_world':{n:v.tolist() for n,v in path_full['joint_wrenches'].items()},
                    'subtree_supported_wrenches_world':{n:v.tolist() for n,v in path_full['subtree'].items()},
                    'actuation_reaction_assessment':reactions,
                    'world_external_wrench':full['world_external_wrench'].tolist(),'mass_kg':full['mass_kg'],
                    'center_of_mass_world_m':full['center_of_mass_world_m'].tolist() if full['center_of_mass_world_m'] is not None else None,
                    'contact_equilibrium':contact,'contact_payload_limit':contact_limit,'grasp_assessment':grasp,'components':fem,'task_probe_assessment':task_probes,
                    'conditional_payload_scale_limit':finite_limit,'fixed_loads_alone_pass':fixed_ok}
            from .robot_preflight import overlays
            record['wrench_overlays']=overlays(robot,c,kin,path_full,[f['robot_load_transfer'] for f in fem if f['status']!='invalid'])
            write_json(directory/'statics.json',record);result['poses'].append(record)
        order={'invalid':3,'indeterminate':2,'fail_under_stated_model':1,'pass_under_stated_model':0}
        result['status']=max(all_status,key=order.get)
        if result['status']=='invalid':
            errors=[pose['name']+'/'+f['robot_load_transfer']['link']+': '+f.get('error','invalid component evidence') for pose in result['poses'] for f in pose['components'] if f['status']=='invalid']
            result['error']='Component FEM failed: '+'; '.join(errors)
        result['coverage']={'rigid_statics_links':list(links),'component_fem_links':component_names,
                            'links_without_fem':[n for n in links if n not in component_names and links[n]['mass_kg']>0]}
        if c.get('elastic_transfer'):
            result['coverage']['first_order_chain_displacement_available']=all((p.get('task_probe_assessment') or {}).get('status') in ('pass_under_stated_model','fail_under_stated_model') for p in result['poses'])
        unrouted=sorted(set(n for p in result['poses'] for n in p['actuation_reaction_assessment']['unrouted_actuators']))
        result['coverage']['unrouted_actuators']=unrouted
        if component_names and not c.get('elastic_transfer'):result['not_assessed'].append('Propagation of component elastic deformation through the URDF chain')
        if c.get('elastic_transfer'):
            result['not_assessed'].append('Coupled continuum elasticity, section warping compatibility, unmodeled joint directions, backlash, control response, mount compliance and higher-order deformation of the robot')
            if not c['elastic_transfer'].get('joint_compliance'):result['not_assessed'].append('Joint flexibility')
            else:
                result['not_assessed'].remove('Joint/mount/ground strength and compliance')
                result['not_assessed'].append('Joint strength, unmodeled joint compliance directions, mount/ground strength and compliance')
        if unrouted:result['not_assessed'].append('Actuator reaction path not explicitly routed: '+', '.join(unrouted))
        result['conditional_payload_limit']={'available':all(v is not None for v in limits),'scale_factor':min(limits) if all(v is not None for v in limits) else None,
                  'meaning':'Declared pose envelope, actuator limits, ideal ground equilibrium, requested grip friction balance and specified component FEM only; not an overall robot rating.',
                  'conditions':c['conditions'],'component_scope':component_names,
                  'withheld_reasons':(['First-order section transfer qualifies requested loads only; recompute requested load levels.'] if c.get('elastic_transfer') else [])
                      + (['Capacity prediction was not requested.'] if not predict_capacity else [])}
        if sha256(Path(c['model']['path']))!=result['source_urdf_sha256'] or any(sha256(Path(a['path']))!=a['sha256'] for a in robot['assets']):
            raise RuntimeError('URDF or mesh assets changed during analysis')
        if any(sha256(Path(p))!=h for p,h in {**component_sources,**component_models}.items()):
            raise RuntimeError('robot component template or FEM source model changed during the pose envelope')
        result['component_sources_sha256']={**component_sources,**component_models}
        if preview:
            from .product import robot_visualization
            result['visualization']=robot_visualization(robot,c,result['poses'])
        guard.check()
    except Exception as exc:
        result['status']='invalid';result['error']=f'{type(exc).__name__}: {exc}';result.pop('conditional_payload_limit',None)
    from .signals import attach_signal
    attach_signal(result,out)
    write_json(out/'result.json',result)
    render_robot_report(result,out)
    return result


def component_analysis(robot,c,component,kin,full,fixed,directory,ccx,timeout,preview,*,progress=None,cache=None,reuse_levels=None,predict_capacity=True):
    from .geometry import inspect
    from .workflow import analyze
    link=component['link'];case=load_case(Path(component['case_path']))
    if case.get('load_cases'):raise ValueError('robot component template must have one load case; robot poses form the envelope')
    case['schema_version']='2.0';case['loads']=[]
    link_rotation=kin['frames'][link][:3,:3];link_origin=kin['frames'][link][:3,3]
    local_frame=component.get('link_from_component',{'xyz_m':[0,0,0],'rpy_rad':[0,0,0]})
    link_from_component=transform(local_frame['xyz_m'],local_frame['rpy_rad'])
    world_from_component=kin['frames'][link]@link_from_component
    rotation=world_from_component[:3,:3];component_origin=world_from_component[:3,3]
    from .robot_probes import component_specs
    task_points=component_specs(c,component,world_from_component)
    if task_points:case['probes']=case.get('probes',[])+task_points
    file_id=re.sub('[^a-zA-Z0-9_-]','_',link)[:48]+'-'+hashlib.sha256(link.encode()).hexdigest()[:8]
    density=case['material'].get('density_kg_m3')
    if density is None:raise ValueError('component FEM needs density to check URDF/CAD mass consistency')
    info=inspect(Path(case['model']['path']),directory/f'component-{file_id}-geometry.json',case['model'])
    mass=info['volume_mm3']*density*1e-9;declared=robot['links'][link]['mass_kg']
    if declared<=0 or abs(mass-declared)/declared>component.get('mass_relative_tolerance',.02):
        raise ValueError(f'component {link} mesh/material mass {mass} kg disagrees with URDF {declared} kg')
    geometry_com=link_from_component[:3,:3]@(np.array(info['center_of_mass_mm'])*.001)+link_from_component[:3,3]
    com_error=float(np.linalg.norm(geometry_com-robot['links'][link]['com_m'])*1000.)
    com_tolerance=component.get('com_tolerance_mm',max(np.linalg.norm(np.array(info['bbox_mm'][1])-info['bbox_mm'][0])*.001,.001))
    if com_error>com_tolerance:raise ValueError(f'component {link} geometry COM differs from URDF by {com_error} mm; check the declared component frame')
    gravity=rotation.T@np.array(c['gravity_m_s2']);case['gravity']={'acceleration_m_s2':gravity.tolist()}
    from .component_transfer import transfer_loads,add_surface_centers
    transfer=transfer_loads(robot,c,component,kin,full,fixed)
    add_surface_centers(transfer,info,component['ports'])
    case['loads']=transfer['loads'];transfers=transfer['ports']
    if case.get('buckling',{}).get('enabled') and not any(l.get('scalable',True) for l in case['loads']):
        raise ValueError('component buckling needs a scalable load pattern')
    case.setdefault('provenance',{})['source_file']=robot['path']
    case_path=directory/f'component-{file_id}.case.json';write_json(case_path,case)
    # Existing task-point/section transfer measures full and fixed responses.
    # Keep those auxiliary fields and all screens even without issuing capacity.
    result=analyze(case_path,directory/f'component-{file_id}',ccx,timeout,preview,progress=progress,cache=cache,reuse_levels=reuse_levels,predict_capacity=predict_capacity,require_fixed_response=bool(c.get('probes')))
    result['robot_load_transfer']={'link':link,'directory_name':f'component-{file_id}',
        'mass_check':{'urdf_kg':declared,'cad_density_kg':mass},'com_error_mm':com_error,'world_from_component':world_from_component.tolist(),'ports':transfers,
        'selected_faces':transfer['selected_faces'],
        'assumption':'Declared component frame and ideal fixed upstream interface; downstream subtree and explicit drive/reaction wrenches applied through declared ports.'}
    write_json(directory/f'component-{file_id}'/'result.json',result)
    return result


def render_robot_report(result,out):
    labels={'invalid':'计算无效','indeterminate':'尚不能判断','fail_under_stated_model':'给定模型下不满足要求','pass_under_stated_model':'给定模型下满足已评估要求'}
    body=f"<h1>SimpleCAE 机器人静力分析</h1><p><b>{labels[result['status']]}</b>。姿态、驱动力与已声明的零件强度按本次条件评估；整体机器人额定承载未评估。</p>"
    if any(f.get('case',{}).get('material',{}).get('calibration',{}).get('kind')=='mathematical_reference' for p in result.get('poses',[]) for f in p.get('components',[])):
        body+='<p><b>包含数学参考材料的数值算例。</b>成立条件用于定义计算参考，不能视为物理验证或产品验收。</p>'
    if result.get('error'):body+='<p>'+html.escape(result['error'])+'</p>'
    limit=result.get('conditional_payload_limit',{})
    if limit.get('available'):
        body+=f"<p>各声明姿态共同的可增加载荷倍数：<b>{limit['scale_factor']:.5g}</b>。固定自重保持不变。此限制只覆盖声明的驱动能力、支点模型和零件分析，不是整机额定承载。</p>"
    elif result.get('case',{}).get('elastic_transfer'):
        body+='<p><b>本模式只评估当前声明载荷，未输出自动整链承重倍率。</b> 增加或改变载荷时请重新求解；一阶转角与截面模型需要保持适用。</p>'
    else:
        body+='<p><b>未给出载荷预测。</b> 请核对额定值、质量、姿态、安装条件及零件分析的有效性。</p>'
    condition_labels={'inertials_verified':'质量与质心已核对','actuator_ratings_verified':'持续保持力矩/力额定值已核对','mount_verified':'底座或地面支撑已核对','poses_verified':'声明姿态覆盖使用要求'}
    facts=result.get('case',{}).get('conditions',{})
    unresolved=[condition_labels.get(n,n) for n,v in facts.items() if v is not True]
    body+='<p>成立条件：'+str(sum(v is True for v in facts.values()))+'/'+str(len(facts))+'已确认；未确认：'+html.escape('、'.join(unresolved) or '无（仍需检查未评估项）')+'。</p>'
    body+='<details><summary>展开全部成立条件</summary><ul>'+''.join('<li>'+html.escape(condition_labels.get(n,n))+'：'+('已确认' if v else '未确认')+'</li>' for n,v in facts.items())+'</ul></details>'
    if result.get('visualization'):
        from .product import embed_robot_viewer
        from .product import STYLE
        viewer='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Robot pose viewer</title><style>'+STYLE+'</style>'+embed_robot_viewer(result['visualization'])+'</html>'
        (Path(out)/'robot-viewer.html').write_text(viewer,encoding='utf-8')
        body+='<iframe title="Robot poses and declared loads" src="robot-viewer.html" loading="lazy" style="width:100%;height:850px;border:0"></iframe><a href="robot-viewer.html">单独打开姿态与载荷视图</a>'
    for i,pose in enumerate(result['poses']):
        body+='<h2>'+html.escape(pose['name'])+'</h2><table><tr><th>驱动关节</th><th>保持力矩/力</th><th>允许值</th><th>利用率</th></tr>'
        for name,e in pose['actuator_efforts'].items():
            u=f"{e['utilization']*100:.1f}%" if e['utilization'] is not None else '缺少额定值'
            allowed=f"{e['allowable']:.5g} {e['units']}" if e['allowable'] is not None else '未提供'
            body+=f"<tr><td>{html.escape(name)}</td><td>{e['holding_effort']:.5g} {e['units']}</td><td>{allowed}</td><td>{u}</td></tr>"
        body+='</table>'
        if pose.get('grasp_assessment'):
            grasp=pose['grasp_assessment']
            if grasp.get('model')=='finite_pad_wrench':
                body+='<p><b>有限软垫的力与力矩平衡：'+('满足声明模型' if grasp['feasible'] else '不满足，可能滑移或转动')+'</b>。使用有限法向力与保守摩擦锥；不代表接触压强、软垫柔度或摩擦实测已验证。'+('已同时检查声明的每侧载荷分配。' if grasp['declared_component_load_pattern_checked'] else '仅检查工件总力/矩，优化接触分配未转移至部件FEM。')+'</p>'
            else:body+=f"<p><b>夹持摩擦：{'满足声明条件' if grasp['feasible'] else '不满足，物体可能滑落'}</b>；可用摩擦力 {grasp['available_friction_n']:.5g} N，含声明裕量的切向需求 {grasp['required_tangential_force_n']:.5g} N。夹紧力与摩擦参数须核实；此项不是局部接触或物体扭转闭合分析。</p>"
        if pose['contact_equilibrium'] is not None:body+='<p>声明的地面支点：'+('可满足静力平衡' if pose['contact_equilibrium']['feasible'] else '无法满足静力平衡，可能倾覆或滑移')+'</p>'
        if pose.get('task_probe_assessment'):
            measurement=pose['task_probe_assessment'];rows=''
            from .report import probe_limit_label
            for p in measurement['probes']:
                rows+='<tr><td>'+html.escape(p['name'])+'</td><td>'+html.escape(p['type'])+'</td><td>'+f"{p['value_mm']:.6g}"+'</td><td>'+html.escape(str(p.get('signed_projection_mm','向量长度')))+'</td><td>'+html.escape(probe_limit_label(p['allowable_displacement_mm']))+'</td></tr>'
            scope='已沿声明的URDF树传递父截面的平移和转角。采用一阶截面模型、显式刚体link和理想锁定关节；尚未实现连续体耦合、截面翘曲相容和关节／安装柔度，不给出自动整链载荷倍率。' if measurement.get('elastic_transfer') else '这里只合成被测link的独立本体位移场；其他部件的变形不会自动沿URDF树传递，未建模的软垫、关节、传感器、导轨与安装柔度也未包含。'
            if measurement.get('displacement_contributions'):
                scope='已合成连杆截面平移／转角与显式关节弹簧变形，沿实际姿态的杆臂传递到测点。一阶开链近似，不包含完整连续体耦合，不给出自动整链载荷倍率。'
            body+='<h3>任务测点与相对变形</h3><p>'+html.escape(labels[measurement['status']])+'。point 为材料点插值，surface_average 为所选材料面的面积平均，relative 为两读数之差。'+scope+'</p><table><tr><th>测点</th><th>方式</th><th>判定量 mm</th><th>带符号方向值 mm</th><th>允许值 mm</th></tr>'+rows+'</table>'
            if measurement.get('elastic_transfer'):
                e=measurement['elastic_transfer']
                lock_label='显式刚性关节锁定条件' if e.get('joint_compliance') else '关节锁定条件'
                body+='<p>转角与截面翘曲筛查：'+('通过' if e['rotation_and_warping_screens_passed'] else '未通过')+'；'+lock_label+'：'+('已声明核实' if e['joints_locked_verified'] else '未核实')+'。截面读数与分级网格证据见 result.json。</p>'
                if e.get('joint_compliance'):
                    body+='<p><b>已加入等效关节柔度。</b> 上表判定量包含连杆与关节变形；仅限声明关节轴向的一阶弹簧。其他方向、间隙、控制响应和安装柔度未评估。</p><table><tr><th>关节</th><th>外载广义力</th><th>弹性偏移</th><th>刚度来源已核实</th></tr>'
                    for j in e['joint_compliance']['full']:
                        body+=f"<tr><td>{html.escape(j['joint'])}</td><td>{j['external_generalized_effort']:.6g} {j['effort_units']}</td><td>{j['deflection']:.6g} {j['deflection_units']}</td><td>{'是' if j['verified'] else '否'}</td></tr>"
                    body+='</table><table><tr><th>测点</th><th>连杆贡献向量 mm</th><th>关节贡献向量 mm</th><th>总向量 mm</th></tr>'
                    for name,v in measurement['displacement_contributions']['full'].items():
                        body+='<tr><td>'+html.escape(name)+'</td>'+''.join('<td>'+html.escape(', '.join(f'{x:.6g}' for x in v[k]))+'</td>' for k in ('link_vector_mm','joint_vector_mm','total_vector_mm'))+'</tr>'
                    body+='</table>'
        if pose.get('actuation_reaction_assessment'):
            from .actuation_report import path_table
            body+=path_table(pose['actuation_reaction_assessment'])
        for j,component in enumerate(pose['components']):
            link=component['robot_load_transfer']['link']
            name=component['robot_load_transfer']['directory_name']
            body+=f'<p>零件 {html.escape(link)}：<a href="pose-{i+1:02d}/{html.escape(name)}/report.html">应力、变形与网格检查</a></p>'
    coverage=result.get('coverage',{})
    body+='<h2>覆盖范围</h2><p>已做零件有限元分析：'+html.escape(', '.join(coverage.get('component_fem_links',[])) or '无')+'。尚未做零件有限元分析：'+html.escape(', '.join(coverage.get('links_without_fem',[])) or '无')+'。</p>'
    from .product import omission_label
    body+='<h2>未评估项</h2><ul>'+''.join('<li>'+html.escape(omission_label(v))+'</li>' for v in result['not_assessed'])+'</ul>'
    body+='<p><a href="result.json">完整计算结果与来源 result.json</a> · <a href="signal.json">Agent评估信号 signal.json</a></p>'
    from .product import STYLE
    document='<html lang="zh-CN"><meta charset="utf-8"><title>SimpleCAE robot</title><style>'+STYLE+'table{border-collapse:collapse;width:100%}td,th{border:1px solid #cbd5df;padding:12px}</style>'+body+'</html>'
    (Path(out)/'report.html').write_text(document,encoding='utf-8')
