"""Relative measurements across explicitly analyzed components, not rigid-link guesses."""
from pathlib import Path
import json
import numpy as np
from .probes import records_from_vectors,convergence

def required_points(case):
    required={p['name'] for p in case.get('probes',[]) if p.get('max_displacement_mm') or p.get('convergence_required')}
    for p in case.get('probes',[]):
        if p['type']=='relative' and p['name'] in required:required.update([p['from_probe'],p['to_probe']])
    return required

def component_specs(case,component,world_from_component):
    from .robot import transform
    frame=component.get('link_from_component',{'xyz_m':[0,0,0],'rpy_rad':[0,0,0]})
    t=transform(frame['xyz_m'],frame['rpy_rad']);required=required_points(case);answer=[]
    for p in case.get('probes',[]):
        if p['type']=='relative' or p['link']!=component['link']:continue
        q={'name':'robot-probe:'+p['name'],'type':p['type'],'convergence_required':p['name'] in required}
        if p['type']=='point':q['point_mm']=(t[:3,:3].T@(np.array(p['point_m'])-t[:3,3])*1000).tolist()
        else:q['selector']=p['component_selector']
        for key in ('max_displacement_mm','absolute_convergence_tolerance_mm'):
            if key in p:q[key]=p[key]
        if 'direction' in p:q['direction']=(world_from_component[:3,:3].T@p['direction']).tolist()
        answer.append(q)
    return answer

def affine_displacement_limit(fixed,variable,allowable,direction=None):
    a=np.asarray(fixed,dtype=float);b=np.asarray(variable,dtype=float)
    if direction is not None:
        a=np.dot(a,direction);b=np.dot(b,direction)
        if abs(a)>allowable+1e-12:return None,False
        if abs(b)<1e-14:return None,True
        roots=sorted([(-allowable-a)/b,(allowable-a)/b]);return max(0.,roots[1]),True
    aa=float(a@a);bb=float(b@b);ab=float(a@b)
    if np.sqrt(aa)>allowable+1e-12:return None,False
    if bb<1e-28:return None,True
    disc=ab*ab-bb*(aa-allowable**2)
    if disc<0 and abs(disc)>1e-12:raise ValueError('probe affine displacement has no valid limit')
    return max(0.,(-ab+np.sqrt(max(disc,0)))/bb),True

def measure(case,kin,components,*,robot=None):
    specs=case.get('probes',[])
    if not specs:return None
    bylink={c['robot_load_transfer']['link']:c for c in components};point_specs=[p for p in specs if p['type']!='relative']
    if any(p['link'] not in bylink for p in point_specs):raise ValueError('robot task points need explicit component FEM; rigid URDF geometry does not provide elastic displacement')
    n=min(len(bylink[p['link']]['levels']) for p in point_specs)
    elastic=None;elastic_series=None
    if case.get('elastic_transfer'):
        if robot is None:raise ValueError('elastic transfer requires the actual URDF tree')
        n=min(len(c['levels']) for c in components)
        from .elastic_transfer import prepare,add_ancestor_motion
        elastic_series,elastic=prepare(case,robot,kin,components,n)
    series=[];fixed_series=[];point_metadata={}
    for index in range(n):
        full_vectors={};fixed_vectors={}
        for p in point_specs:
            component=bylink[p['link']];level=component['levels'][-n+index];name='robot-probe:'+p['name']
            sampled=next((q for q in level['results'].get('probes',[]) if q['name']==name),None)
            if sampled is None:raise ValueError('component task-point field is missing: '+p['name'])
            rotation=np.array(component['robot_load_transfer']['world_from_component'])[:3,:3]
            full_vectors[p['name']]=rotation@sampled['displacement_vector_mm']
            if level['mesh'].get('fixed_nodal_forces'):
                f=json.loads((Path(level['directory'])/'fixed-results.json').read_text(encoding='utf-8'))
                fs=next((q for q in f['results'].get('probes',[]) if q['name']==name),None)
                if fs is None:raise ValueError('fixed-load task-point field is missing: '+p['name'])
                fixed_vectors[p['name']]=rotation@fs['displacement_vector_mm']
            else:fixed_vectors[p['name']]=np.zeros(3)
            transform=np.array(component['robot_load_transfer']['world_from_component'])
            world=transform[:3,:3]@np.array(sampled.get('point_mm',[0,0,0]))*.001+transform[:3,3] if p['type']=='surface_average' else kin['frames'][p['link']][:3,:3]@p['point_m']+kin['frames'][p['link']][:3,3]
            point_metadata[p['name']]={'name':p['name'],'type':p['type'],'link':p['link'],'point_world_m':world.tolist(),'point_mm':(world*1000).tolist(),
                'element':sampled.get('element'),'method':sampled.get('method','C3D10 component displacement')+' rotated to world axes'}
            if 'point_meaning' in sampled:point_metadata[p['name']]['point_meaning']=sampled['point_meaning']
        if elastic_series is not None:
            add_ancestor_motion(full_vectors,point_metadata,kin,elastic_series[index][0])
            add_ancestor_motion(fixed_vectors,point_metadata,kin,elastic_series[index][1])
        series.append(records_from_vectors(specs,full_vectors,point_metadata))
        fixed_series.append(records_from_vectors(specs,fixed_vectors,point_metadata))
    tolerance=min(c['case']['mesh'].get('displacement_relative_tolerance',.05) for c in bylink.values())
    pairs=[convergence(a,b,tolerance) for a,b in zip(series,series[1:])]
    required=required_points(case);mesh_ok=len(pairs)>=2 and all(p[name]['converged'] for p in pairs[-2:] for name in required)
    if elastic:
        # Check the transmitted frames themselves, even if a relative measurement
        # cancels common ancestor motion. Convert rotation to displacement at the
        # robot's declared span so translation and angle both enter this check.
        origins=np.array([t[:3,3]*1000 for t in kin['frames'].values()]);span=max(np.linalg.norm(np.ptp(origins,axis=0)),1.)
        frame_pairs=[]
        for previous,current in zip(elastic_series,elastic_series[1:]):
            ok=True
            for a,b in zip(previous,current):
                for link in a:
                    old=np.r_[a[link][0],a[link][1]*span];new=np.r_[b[link][0],b[link][1]*span]
                    ok=ok and np.linalg.norm(new-old)<=max(np.linalg.norm(new)*tolerance,1e-8)
            frame_pairs.append(bool(ok))
        elastic['frame_mesh_comparisons']=frame_pairs
        mesh_ok=mesh_ok and len(frame_pairs)>=2 and all(frame_pairs[-2:]) and elastic['rotation_and_warping_screens_passed']
    final={p['name']:p for p in series[-1]};fixed={p['name']:p for p in fixed_series[-1]};limits=[];fixed_ok=True
    criteria={};all_values_pass=True
    for spec in specs:
        p=final[spec['name']]
        if p['utilization'] is None:continue
        probe_ok=len(pairs)>=2 and all(pair[p['name']]['converged'] for pair in pairs[-2:]) and (not elastic or mesh_ok)
        state='indeterminate' if not probe_ok else 'fail_under_stated_model' if p['utilization']>1 else 'pass_under_stated_model'
        criteria['probe:'+p['name']]={'status':state,'utilization':p['utilization'],'mesh_converged':probe_ok,'physical_verification_separate':True}
        all_values_pass=all_values_pass and p['utilization']<=1
        a=np.array(fixed[p['name']]['displacement_vector_mm']);b=np.array(p['displacement_vector_mm'])-a
        limit,ok=affine_displacement_limit(a,b,spec['max_displacement_mm'],spec.get('direction'));fixed_ok=fixed_ok and ok
        if limit is not None:limits.append(limit)
    status='indeterminate' if not mesh_ok else 'pass_under_stated_model' if all_values_pass else 'fail_under_stated_model'
    upper=min(limits) if limits and fixed_ok and mesh_ok else None
    # The limiting mixed fixed+variable measurement needs its own convergence,
    # just as a standalone component's limiting response does.
    if upper is not None:
        predicted=[]
        for full,fixed_level in zip(series,fixed_series):
            fixed_map={p['name']:p for p in fixed_level};vectors={}
            for p in full:
                if p['type']!='relative':
                    a=np.array(fixed_map[p['name']]['displacement_vector_mm']);vectors[p['name']]=a+upper*(np.array(p['displacement_vector_mm'])-a)
            predicted.append(records_from_vectors(specs,vectors,point_metadata))
        predicted_pairs=[convergence(a,b,tolerance) for a,b in zip(predicted,predicted[1:])]
        if any(not p[name]['converged'] for p in predicted_pairs[-2:] for name in required):upper=None
    if elastic:upper=None
    contributions=None
    if elastic and elastic.get('joint_only_link_frames'):
        contributions={}
        for stage,records in [('full',series[-1]),('fixed',fixed_series[-1])]:
            vectors={p['name']:np.zeros(3) for p in point_specs}
            states={link:(np.array(v['translation_mm']),np.array(v['rotation_rad'])) for link,v in elastic['joint_only_link_frames'][stage].items()}
            from .elastic_transfer import add_ancestor_motion
            add_ancestor_motion(vectors,point_metadata,kin,states)
            joint_records=records_from_vectors(specs,vectors,point_metadata)
            total={p['name']:np.array(p['displacement_vector_mm']) for p in records}
            contributions[stage]={p['name']:{'joint_vector_mm':p['displacement_vector_mm'],
                                            'link_vector_mm':(total[p['name']]-p['displacement_vector_mm']).tolist(),
                                            'total_vector_mm':total[p['name']].tolist()} for p in joint_records}
    return {'status':status,'probes':series[-1],'fixed_load_probes':fixed_series[-1],'criterion_assessments':criteria,'mesh_comparisons':pairs,
            'measurement_scope':elastic['model'] if elastic else 'independent_component_fields','whole_robot_displacement_available':False,
            'elastic_transfer':elastic,
            'displacement_contributions':contributions,
            'fixed_loads_alone_pass':fixed_ok,'payload_scale_limit':upper,
            'conditional_limit_eligible':not elastic and fixed_ok and mesh_ok and (not limits or upper is not None),
            'scope':elastic['scope'] if elastic else 'Difference of independent measured-link component elastic fields at a fixed declared pose. Deformation of other components is not automatically propagated along the URDF chain; omitted pad, joint, mount, sensor and transmission compliance remains unassessed.'}
