"""First-order rigid-section transfer on a statically determinate URDF tree.

This is a reduced link model, not a coupled continuum/joint/contact solution.
Parent section translation AND rotation move downstream links at their actual
posed lever arms. Section warping is measured and never silently transferred.
"""
from pathlib import Path
import numpy as np
from .case import keys,number


def validate(case,robot=None):
    if 'elastic_transfer' not in case:return
    spec=case['elastic_transfer']
    fields=['rigid_links','joints_locked_verified','max_rotation_rad','max_section_warping_mm','reference']
    keys(spec,fields+['joint_compliance','rigid_joints'],fields,'elastic_transfer')
    from .joint_compliance import validate as validate_joints
    validate_joints(case,robot)
    if not isinstance(spec['rigid_links'],list) or any(not isinstance(n,str) or not n for n in spec['rigid_links']) or len(set(spec['rigid_links']))!=len(spec['rigid_links']):raise ValueError('rigid_links needs unique explicit link names')
    if type(spec['joints_locked_verified']) is not bool:raise ValueError('joints_locked_verified must be boolean')
    if not 0<number(spec['max_rotation_rad'],'section rotation limit',True)<=.05:raise ValueError('first-order section rotation limit must be <= 0.05 rad')
    number(spec['max_section_warping_mm'],'section warping limit',True)
    if not isinstance(spec['reference'],str) or not spec['reference'].strip():raise ValueError('elastic transfer needs an assumption/calibration reference')
    if case['base']['type']!='fixed' or case.get('actuation_reactions'):raise ValueError('elastic transfer supports fixed-base tree load paths only; closed actuation loops/contact bases need a coupled model')
    if not case.get('probes'):raise ValueError('elastic transfer needs explicit task probes')
    if robot is None:return
    fem={c['link']:c for c in case.get('components',[])};rigid=set(spec['rigid_links'])
    if rigid&set(fem) or rigid|set(fem)!=set(robot['links']):raise ValueError('every URDF link must be explicitly FEM or rigid, with no overlap or unknown link')
    from .case import load_case
    for link,component in fem.items():
        template=load_case(Path(component['case_path']));supports=template['supports']
        if template.get('reference_only') or len(supports)!=1 or sorted(supports[0].get('dofs',[1,2,3]))!=[1,2,3]:raise ValueError('section transfer requires exactly one fully clamped upstream material surface per FEM link')
        missing=set(robot['children'][link])-set(component['ports'])
        if missing:raise ValueError('elastic transfer needs each downstream joint section port, even for a zero wrench: '+','.join(sorted(missing)))


def fit_section(points,displacements,weights):
    """Area-weighted infinitesimal rigid fit u=t+theta cross (x-centroid)."""
    p=np.asarray(points);u=np.asarray(displacements);w=np.asarray(weights)
    if p.ndim!=2 or p.shape!=u.shape or p.shape[1]!=3 or len(w)!=len(p) or not np.all(np.isfinite(np.r_[p.ravel(),u.ravel(),w])) or np.any(w<=0):raise ValueError('section samples must be finite with positive area weights')
    area=w.sum();center=np.sum(p*w[:,None],axis=0)/area;mean=np.sum(u*w[:,None],axis=0)/area;r=p-center
    gram=sum((a*((v@v)*np.eye(3)-np.outer(v,v)) for a,v in zip(w,r)),np.zeros((3,3)))
    if np.linalg.cond(gram)>1e12:raise ValueError('section cannot resolve all three rotation components')
    theta=np.linalg.solve(gram,np.sum(np.cross(r,u-mean)*w[:,None],axis=0))
    residual=u-mean-np.cross(theta,r)
    return {'center_mm':center.tolist(),'translation_mm':mean.tolist(),'rotation_rad':theta.tolist(),
            'warping_rms_mm':float(np.sqrt(np.sum(w*np.sum(residual**2,axis=1))/area)),'area_mm2':float(area)}


def sample_section(level,selector,fixed=False):
    from .geometry import select_faces
    from .assembly import quadrature,tri_basis
    directory=Path(level['directory']);mesh=np.load(directory/'mesh.npz');coords=dict(zip(map(int,mesh['node_ids']),mesh['xyz']))
    if fixed:
        if not level['mesh'].get('fixed_nodal_forces'):return None
        from .solver import parse_dat
        fields=parse_dat(directory/'fixed.dat')['displacements']
    else:
        data=np.load(directory/'fields.npz');fields=dict(zip(map(int,data['node_ids']),data['displacements']))
    faces=select_faces(level['mesh']['geometry'],selector);triangles=mesh['surface_tri6'][np.isin(mesh['surface_face_ids'],faces)]
    points=[];values=[];weights=[]
    for nodes in triangles:
        xyz=np.array([coords[int(n)] for n in nodes]);u=np.array([fields[int(n)] for n in nodes])
        for r,s,w in quadrature():
            basis,dr,ds=tri_basis(r,s);measure=np.linalg.norm(np.cross(dr@xyz,ds@xyz))*w/2
            points.append(basis@xyz);values.append(basis@u);weights.append(measure)
    if not points:raise ValueError('empty elastic transfer section')
    points_array=np.array(points);singular=np.linalg.svd(points_array-points_array.mean(axis=0),compute_uv=False)
    if singular[-1]>max(singular[0],1.)*1e-8:raise ValueError('elastic transfer currently requires planar material section ports')
    answer=fit_section(points,values,weights);answer['face_ids']=faces;return answer


def propagate(robot,kin,components,frames,joint_motions=None):
    """Return ancestor-induced motion at each link origin, in world mm/rad."""
    states={robot['root']:(np.zeros(3),np.zeros(3))}
    def walk(parent):
        translation,rotation=states[parent];origin=kin['frames'][parent][:3,3]*1000
        for name in robot['children'][parent]:
            child=robot['joints'][name]['child'];point=kin['frames'][child][:3,3]*1000
            t=translation+np.cross(rotation,point-origin);theta=rotation.copy()
            if parent in components:
                section=frames[(parent,name)];transform=np.array(components[parent]['robot_load_transfer']['world_from_component'])
                r=transform[:3,:3];local=r.T@(point-transform[:3,3]*1000)
                angular=np.array(section['rotation_rad']);u=np.array(section['translation_mm'])+np.cross(angular,local-section['center_mm'])
                t=t+r@u;theta=theta+r@angular
            if joint_motions and name in joint_motions:
                jt,jr=joint_motions[name];t=t+jt;theta=theta+jr
            states[child]=(t,theta)
            walk(child)
    walk(robot['root']);return states


def prepare(case,robot,kin,components,n):
    validate(case,robot);bylink={c['robot_load_transfer']['link']:c for c in components}
    specs={c['link']:c for c in case['components']};series=[];diagnostics=[];gates=True
    from .joint_compliance import enabled,solve
    joint_stages={};joint_only={};joint_gates=True
    if enabled(case):
        for fixed in (False,True):
            stage='fixed' if fixed else 'full'
            motion,records,ok=solve(case,robot,kin,fixed)
            joint_stages[stage]=(motion,records);joint_gates=joint_gates and ok
            joint_only[stage]=propagate(robot,kin,{}, {},motion)
            if any(r['deflection_units']=='m' for r in records):
                # Many individually small slides must not accumulate into an
                # arbitrarily changed posed load path. This is a heuristic screen.
                span=records[0]['linear_screen_span_mm']
                joint_gates=joint_gates and all(np.linalg.norm(v[0])<=.01*span for v in joint_only[stage].values())
        gates=gates and joint_gates
    for index in range(n):
        states=[];details=[]
        for fixed in (False,True):
            frames={}
            for link,component in bylink.items():
                level=component['levels'][-n+index]
                for joint in robot['children'][link]:
                    fit=sample_section(level,specs[link]['ports'][joint],fixed)
                    if fit is None:fit={'center_mm':[0,0,0],'translation_mm':[0,0,0],'rotation_rad':[0,0,0],'warping_rms_mm':0.}
                    frames[(link,joint)]=fit
                    gates=gates and np.linalg.norm(fit['rotation_rad'])<=case['elastic_transfer']['max_rotation_rad'] and fit['warping_rms_mm']<=case['elastic_transfer']['max_section_warping_mm']
                    details.append(dict(fit,link=link,joint=joint,stage='fixed' if fixed else 'full'))
            propagated=propagate(robot,kin,bylink,frames,joint_stages['fixed' if fixed else 'full'][0] if joint_stages else None);states.append(propagated)
            gates=gates and all(np.linalg.norm(v[1])<=case['elastic_transfer']['max_rotation_rad'] for v in propagated.values())
        series.append(states);diagnostics.append(details)
    evidence={'model':'first_order_section_frames','section_frames_by_level':diagnostics,
                   'rotation_and_warping_screens_passed':bool(gates),'joints_locked_verified':case['elastic_transfer']['joints_locked_verified'],
                   'scope':'Fully clamped link FEM with area-fitted parent section translation/rotation, explicit rigid links and ideal locked joints; first-order tree transfer, not coupled continuum elasticity. Joint, mount and contact compliance omitted.'}
    if joint_stages:
        evidence['model']='first_order_link_and_joint_compliance'
        evidence['joint_compliance']={stage:values[1] for stage,values in joint_stages.items()}
        evidence['joint_compliance']['small_response_passed']=bool(joint_gates)
        evidence['joint_only_link_frames']={stage:{link:{'translation_mm':v[0].tolist(),'rotation_rad':v[1].tolist()} for link,v in states.items()} for stage,states in joint_only.items()}
        evidence['scope']='Fixed-pose first-order link section transfer plus independent scalar joint springs. Other joint directions and declared rigid joints/links are ideal rigid. No coupled continuum, backlash, control dynamics, mount compliance or deformed-load redistribution.'
    return series,evidence


def add_ancestor_motion(vectors,metadata,kin,states):
    for name,vector in vectors.items():
        p=metadata[name];translation,rotation=states[p['link']]
        vectors[name]=vector+translation+np.cross(rotation,np.array(p['point_world_m'])*1000-kin['frames'][p['link']][:3,3]*1000)
