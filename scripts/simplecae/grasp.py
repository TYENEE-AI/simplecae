"""Declared two-finger vertical friction balance; not a contact solver."""
import numpy as np
from .case import keys,number,vector

def validate_grasp(case):
    g=case['grasp']
    keys(g,['payload_names','normal_load_names','additional_tangential_load_names','friction_coefficient','slip_safety_factor','conditions','model','pad_contacts','pad_wrench_mode'],
         ['payload_names','normal_load_names','friction_coefficient','slip_safety_factor','conditions'],'grasp')
    payloads={p['name']:p for p in case.get('payloads',[])};loads={p['name']:p for p in case.get('loads',[])}
    for field,source,count in [('payload_names',payloads,None),('normal_load_names',loads,2),('additional_tangential_load_names',loads,None)]:
        names=g.get(field,[])
        if not isinstance(names,list) or any(not isinstance(n,str) or n not in source for n in names) or len(set(names))!=len(names):
            raise ValueError(f'grasp.{field} must name unique existing entries')
        if count is not None and len(names)!=count:raise ValueError('grasp requires exactly two normal-force loads')
    if not g['payload_names']:raise ValueError('grasp needs its workpiece payload names')
    if set(g['normal_load_names'])&set(g.get('additional_tangential_load_names',[])):raise ValueError('normal forces cannot also be tangential loads')
    if any(loads[n].get('scalable',True) for n in g['normal_load_names']):raise ValueError('grasp normal-force commands must be fixed, not scaled with payload')
    contact_links={loads[n]['link'] for n in g['normal_load_names']}
    if len(contact_links)!=2:raise ValueError('grasp normal loads must act on two distinct contact links')
    if any(payloads[n]['link'] not in contact_links for n in g['payload_names']) or any(loads[n]['link'] not in contact_links for n in g.get('additional_tangential_load_names',[])):
        raise ValueError('grasp workpiece shares and tangential loads must belong to the two declared contact links')
    mu=number(g['friction_coefficient'],'grasp friction coefficient')
    if mu<0:raise ValueError('grasp friction coefficient must be >=0')
    if number(g['slip_safety_factor'],'grasp slip safety factor')<1:raise ValueError('grasp slip safety factor must be >=1')
    keys(g['conditions'],['friction_verified','force_verified','pad_contact_verified'],['friction_verified','force_verified'],'grasp.conditions')
    if any(type(v) is not bool for v in g['conditions'].values()):raise ValueError('grasp conditions must be booleans')
    if g.get('model','vertical_friction') not in ('vertical_friction','finite_pad_wrench'):raise ValueError('grasp.model must be vertical_friction or finite_pad_wrench')
    if g.get('model')=='finite_pad_wrench':
        pads=g.get('pad_contacts')
        if not isinstance(pads,list) or len(pads)!=2:raise ValueError('finite-pad grasp requires two explicit pad_contacts')
        names=[]
        for p in pads:
            keys(p,['normal_load_name','center_link_m','tangent_u_link','tangent_v_link','half_extents_m'],
                 ['normal_load_name','center_link_m','tangent_u_link','tangent_v_link','half_extents_m'],'pad contact')
            names.append(p['normal_load_name']);vector(p['center_link_m'],'pad center')
            u=np.array(vector(p['tangent_u_link'],'pad tangent'));v=np.array(vector(p['tangent_v_link'],'pad tangent'))
            if not np.allclose([u@u,v@v,u@v],[1,1,0],rtol=0,atol=1e-8):raise ValueError('pad tangent axes must be orthonormal')
            if not isinstance(p['half_extents_m'],list) or len(p['half_extents_m'])!=2:raise ValueError('pad half extents need two dimensions in m')
            for x in p['half_extents_m']:number(x,'pad half extent',True)
        if set(names)!=set(g['normal_load_names']) or len(set(names))!=2:raise ValueError('pad contacts must map bijectively to normal_load_names')
        if g.get('pad_wrench_mode','declared_per_pad') not in ('declared_per_pad','total_wrench'):raise ValueError('pad_wrench_mode must be declared_per_pad or total_wrench')
    elif any(k in g for k in ('pad_contacts','pad_wrench_mode')):raise ValueError('pad fields require grasp.model finite_pad_wrench')

def assess_grasp(case,kin):
    if case['grasp'].get('model')=='finite_pad_wrench':return assess_finite_grasp(case,kin)
    g=case['grasp'];payloads={p['name']:p for p in case.get('payloads',[])};loads={p['name']:p for p in case.get('loads',[])}
    gravity=np.array(case['gravity_m_s2'],dtype=float);direction=gravity/np.linalg.norm(gravity)
    def force(load):
        f=np.array(load['force_n'],dtype=float)
        return kin['frames'][load['link']][:3,:3]@f if load.get('frame','link')=='link' else f
    normals=[force(loads[n]) for n in g['normal_load_names']];magnitudes=[float(np.linalg.norm(f)) for f in normals]
    if min(magnitudes)<=0:raise ValueError('grasp requires two nonzero normal-force commands')
    if not np.isclose(magnitudes[0],magnitudes[1],rtol=1e-8,atol=1e-10) or np.linalg.norm(normals[0]+normals[1])>max(magnitudes)*1e-8:
        raise ValueError('grasp model requires equal opposing normal forces; use a contact/wrench model for unequal or angled jaws')
    if abs(np.dot(normals[0]/magnitudes[0],direction))>1e-8:
        raise ValueError('grasp friction model requires closing normals perpendicular to gravity; this pose needs a different contact model')
    fixed=np.zeros(3);variable=np.zeros(3)
    for name in g['payload_names']:
        p=payloads[name];f=p['mass_kg']*gravity
        if p.get('scalable',True):variable+=f
        else:fixed+=f
    for name in g.get('additional_tangential_load_names',[]):
        load=loads[name];f=force(load)
        if np.linalg.norm(np.cross(f,direction))>max(np.linalg.norm(f),1)*1e-8 or np.dot(f,direction)<-1e-10:
            raise ValueError('grasp additional loads must act along gravity; torque, lateral load or load reversal requires a full contact-wrench analysis')
        if load.get('scalable',True):variable+=f
        else:fixed+=f
    available=g['friction_coefficient']*sum(magnitudes)
    sf=g['slip_safety_factor'];required=sf*float(np.linalg.norm(fixed+variable))
    utilization=required/available if available>0 else None
    scaling=(available/sf-float(np.linalg.norm(fixed)))/float(np.linalg.norm(variable)) if np.linalg.norm(variable)>0 else None
    return {'feasible':required<=available+1e-12,'utilization':utilization,'available_friction_n':available,'required_tangential_force_n':required,
            'reserve_n':available-required,'payload_scale_limit':max(0.,scaling) if scaling is not None else None,
            'friction_coefficient':g['friction_coefficient'],'normal_force_per_finger_n':magnitudes[0],'conditions':g['conditions'],
            'scope':'Declared equal opposing two-finger vertical friction balance; excludes contact pressure, pad compliance, object rotational wrench closure and friction calibration.'}

def assess_finite_grasp(case,kin):
    from .contact_wrench import finite_pad_wrench
    g=case['grasp'];loads={p['name']:p for p in case.get('loads',[])};payloads={p['name']:p for p in case.get('payloads',[])}
    frames=kin['frames'];centers=[]
    def load_world(load):
        t=frames[load['link']];force=np.array(load['force_n'],dtype=float);moment=np.array(load.get('moment_n_m',[0,0,0]),dtype=float)
        if load.get('frame','link')=='link':force=t[:3,:3]@force;moment=t[:3,:3]@moment
        point=np.array(load['position_m'],dtype=float)
        if load.get('position_frame',load.get('frame','link'))=='link':point=t[:3,:3]@point+t[:3,3]
        return force,moment,point
    for spec in g['pad_contacts']:
        load=loads[spec['normal_load_name']];t=frames[load['link']]
        centers.append(t[:3,:3]@spec['center_link_m']+t[:3,3])
    reference=np.mean(centers,axis=0);pads=[];normal_w=[];fixed_pad=[];variable_pad=[];link_to_pad={}
    for i,spec in enumerate(g['pad_contacts']):
        load=loads[spec['normal_load_name']];t=frames[load['link']];force,moment,point=load_world(load);normal=float(np.linalg.norm(force))
        if normal<=0:raise ValueError('finite-pad grasp requires nonzero normal-force commands')
        pads.append({'name':load['name'],'center_world_m':centers[i].tolist(),'inward_normal_world':(-force/normal).tolist(),
            'tangent_u_world':(t[:3,:3]@spec['tangent_u_link']).tolist(),'tangent_v_world':(t[:3,:3]@spec['tangent_v_link']).tolist(),
            'half_extents_m':spec['half_extents_m'],'normal_force_n':normal,'friction_coefficient':g['friction_coefficient']})
        normal_w.append(np.r_[force,moment+np.cross(point-reference,force)]);fixed_pad.append(np.zeros(6));variable_pad.append(np.zeros(6));link_to_pad[load['link']]=i
    for name in g['payload_names']:
        p=payloads[name];t=frames[p['link']];point=t[:3,:3]@p['center_m']+t[:3,3];force=p['mass_kg']*np.array(case['gravity_m_s2'])
        w=np.r_[force,np.cross(point-reference,force)];(variable_pad if p.get('scalable',True) else fixed_pad)[link_to_pad[p['link']]]+=w
    for name in g.get('additional_tangential_load_names',[]):
        load=loads[name];force,moment,point=load_world(load);w=np.r_[force,moment+np.cross(point-reference,force)]
        (variable_pad if load.get('scalable',True) else fixed_pad)[link_to_pad[load['link']]]+=w
    sf=g['slip_safety_factor'];fixed=sf*sum(fixed_pad,np.zeros(6));variable=sf*sum(variable_pad,np.zeros(6))
    declared=g.get('pad_wrench_mode','declared_per_pad')=='declared_per_pad'
    pf=[(-n-sf*f).tolist() for n,f in zip(normal_w,fixed_pad)];pv=[(-sf*v).tolist() for v in variable_pad]
    refargs={'declared_pad_fixed':[(np.array(a)+b).tolist() for a,b in zip(pf,pv)]} if declared else {}
    reference_result=finite_pad_wrench(pads,(fixed+variable).tolist(),reference_world_m=reference.tolist(),**refargs)
    limitargs={'declared_pad_fixed':pf,'declared_pad_variable':pv} if declared else {}
    limit=finite_pad_wrench(pads,fixed.tolist(),variable.tolist(),reference_world_m=reference.tolist(),**limitargs)
    scaling=limit.get('payload_scale_limit');utilization=1/scaling if scaling is not None and scaling>0 else None
    conditions=dict(g['conditions']);conditions.setdefault('pad_contact_verified',False)
    return {'model':'finite_pad_wrench','feasible':reference_result['feasible'],'utilization':utilization,
        'available_friction_n':sum(p['normal_force_n']*p['friction_coefficient'] for p in pads),
        'required_tangential_force_n':float(np.linalg.norm((fixed+variable)[:3])),
        'external_wrench_at_reference':(fixed+variable).tolist(),'normal_force_per_finger_n':[p['normal_force_n'] for p in pads],
        'friction_coefficient':g['friction_coefficient'],'payload_scale_limit':scaling,'conditions':conditions,
        'reference_contact_solution':reference_result,'limiting_contact_solution':limit,
        'declared_component_load_pattern_checked':declared,'scope':reference_result['scope'],
        'meaning':'Finite-pad force and moment feasibility. Declared-per-pad mode also checks the supplied load shares; total-wrench mode does not transfer an optimized contact distribution to component FEM.'}

def compile_gripper_task(task,source):
    """Turn explicit application facts into a robot case; never infer geometry."""
    from pathlib import Path
    keys(task,['schema_version','task_id','model_path','package_roots','massless_links','poses','contacts','payload_mass_kg','normal_force_per_finger_n','friction_coefficient',
               'acceleration_along_gravity_m_s2','slip_safety_factor','gravity_m_s2','components','required_components',
               'conditions','grasp_conditions','effort_safety_factor','additional_robot_loads','workpiece_load_names','notes','grasp_model','pad_wrench_mode','probes','actuation_reactions'],
         ['task_id','model_path','poses','contacts','payload_mass_kg','normal_force_per_finger_n','friction_coefficient','slip_safety_factor'],'gripper task')
    if task.get('schema_version','gripper-task-1.0')!='gripper-task-1.0':raise ValueError('unsupported gripper task schema_version')
    for field in ('task_id','model_path'):
        if not isinstance(task[field],str) or not task[field].strip():raise ValueError(f'gripper task {field} must be a nonempty string')
    mass=number(task['payload_mass_kg'],'payload mass',True);normal=number(task['normal_force_per_finger_n'],'normal force per finger',True)
    acceleration=number(task.get('acceleration_along_gravity_m_s2',0),'acceleration along gravity')
    if acceleration<0:raise ValueError('use nonnegative worst-case acceleration along gravity for this task model')
    gravity=np.array(vector(task.get('gravity_m_s2',[0,0,-9.80665]),'gravity'))
    if np.linalg.norm(gravity)==0:raise ValueError('gravity must be nonzero')
    contacts=task['contacts']
    if not isinstance(contacts,list) or len(contacts)!=2:raise ValueError('exactly two contact links/points/normals are required')
    payloads=[];loads=[];normal_names=[];extra_names=[];pads=[]
    for i,contact in enumerate(contacts):
        keys(contact,['link','position_m','normal_link','pad'],['link','position_m','normal_link'],'contact')
        point=vector(contact['position_m'],'contact position');axis=np.array(vector(contact['normal_link'],'contact normal'))
        if not np.isclose(np.linalg.norm(axis),1,rtol=0,atol=1e-8):raise ValueError('normal_link must be a unit vector in the contact link frame')
        payloads.append({'name':f'workpiece_share_{i}','link':contact['link'],'mass_kg':mass/2,'center_m':point,'scalable':True})
        name=f'normal_{i}';normal_names.append(name)
        if contact.get('pad'):
            pads.append(dict(contact['pad'],normal_load_name=name))
        loads.append({'name':name,'link':contact['link'],'force_n':(normal*axis).tolist(),'position_m':point,'frame':'link','scalable':False})
        if acceleration:
            name=f'workpiece_acceleration_{i}';extra_names.append(name)
            # World direction is known explicitly; avoid assuming link axes match it.
            loads.append({'name':name,'link':contact['link'],'force_n':(mass/2*acceleration*gravity/np.linalg.norm(gravity)).tolist(),
                          'position_m':point,'frame':'world','position_frame':'link','scalable':True})
    parent=Path(source).resolve().parent
    components=task.get('components',[])
    from copy import deepcopy
    components=deepcopy(components)
    names=task.get('workpiece_load_names',[])
    if not isinstance(names,list) or any(not isinstance(n,str) or not n for n in names):raise ValueError('workpiece_load_names must be a list of nonempty load names')
    extra_names+=names
    for c in components:c['case_path']=str((parent/c['case_path']).resolve())
    c={'schema_version':'robot-1.0','model':{'path':str((parent/task['model_path']).resolve())},'poses':task['poses'],'gravity_m_s2':gravity.tolist(),
       'payloads':payloads,'loads':loads+task.get('additional_robot_loads',[]),'base':{'type':'fixed'},'components':components,'required_components':task.get('required_components',[]),
       'effort_safety_factor':task.get('effort_safety_factor',1.5),'conditions':task.get('conditions',dict.fromkeys(('inertials_verified','actuator_ratings_verified','mount_verified','poses_verified'),False)),
       'grasp':{'payload_names':[p['name'] for p in payloads],'normal_load_names':normal_names,'additional_tangential_load_names':extra_names,
                'friction_coefficient':task['friction_coefficient'],'slip_safety_factor':task['slip_safety_factor'],
                'conditions':task.get('grasp_conditions',{'friction_verified':False,'force_verified':False})},
       'provenance':{'task_id':task['task_id'],'generator':'simplecae_gripper_task','source_file':str(Path(source).resolve())},
       'notes':task.get('notes','Explicit two-finger grip task; application facts are declared, not measured by CAD or the solver.')}
    packages=task.get('package_roots',{})
    if not isinstance(packages,dict) or any(not isinstance(n,str) or not n or not isinstance(p,str) or not p for n,p in packages.items()):raise ValueError('package_roots must map package names to paths')
    if packages:c['model']['package_roots']={n:str((parent/p).resolve()) for n,p in packages.items()}
    if 'massless_links' in task:c['massless_links']=deepcopy(task['massless_links'])
    validate_grasp(c)
    if task.get('grasp_model'):
        c['grasp']['model']=task['grasp_model']
        if task['grasp_model']=='finite_pad_wrench':
            c['grasp']['pad_contacts']=pads;c['grasp']['pad_wrench_mode']=task.get('pad_wrench_mode','declared_per_pad')
        elif pads:raise ValueError('contact pad geometry requires grasp_model finite_pad_wrench')
        validate_grasp(c)
    elif pads or 'pad_wrench_mode' in task:raise ValueError('explicit grasp_model finite_pad_wrench is needed for pad geometry/options')
    if task.get('probes'):
        from .probes import validate_probes
        c['probes']=deepcopy(task['probes']);validate_probes(c)
    if 'actuation_reactions' in task:
        from .actuation import validate_reactions
        c['actuation_reactions']=deepcopy(task['actuation_reactions']);validate_reactions(c)
    return c
