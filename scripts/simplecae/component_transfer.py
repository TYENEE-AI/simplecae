"""Same explicit component loads for preview and solve, in CAD mm coordinates."""
import numpy as np


def transfer_loads(robot,c,component,kin,full,fixed):
    from .robot import transform
    link=component['link'];lt=kin['frames'][link]
    frame=component.get('link_from_component',{'xyz_m':[0,0,0],'rpy_rad':[0,0,0]})
    world=lt@transform(frame['xyz_m'],frame['rpy_rad']);rotation=world[:3,:3];origin=world[:3,3]
    loads=[];transfers=[];used=set()
    def add(name,w,point,scalable,mandatory=False):
        if mandatory:
            if name not in component['ports']:raise ValueError(f'component {link} missing load port {name}')
            used.add(name)
        if np.linalg.norm(w)<1e-12:return
        if name not in component['ports']:raise ValueError(f'component {link} missing load port {name}')
        used.add(name);f=rotation.T@w[:3];m=rotation.T@w[3:]*1000;p=rotation.T@(point-origin)*1000
        loads.append({'name':name+(':payload' if scalable else ':fixed'),'selector':component['ports'][name],
                      'total_force_n':f.tolist(),'total_moment_n_mm':m.tolist(),
                      'application_point_mm':p.tolist(),'scalable':scalable})
        policy=component.get('port_load_policies',{}).get(name,{})
        loads[-1].update({k:policy[k] for k in ('distribution','allow_opposite_traction') if k in policy})
        transfers.append({'port':name,'force_n':f.tolist(),'moment_n_mm_at_application':m.tolist(),
                          'point_mm':p.tolist(),'scalable':scalable,
                          'world_point_m':point.tolist(),'world_force_n':w[:3].tolist(),
                          'world_moment_n_m_at_application':w[3:].tolist(), 'load_policy':policy})
    for name in robot['children'][link]:
        child=robot['joints'][name]['child'];point=kin['frames'][child][:3,3]
        if c.get('elastic_transfer') and name in component['ports']:used.add(name)
        add(name,fixed['subtree'][child],point,False)
        add(name,full['subtree'][child]-fixed['subtree'][child],point,True)
    for field in ('payloads','loads'):
        for item in c.get(field,[]):
            if item['link']!=link:continue
            if field=='payloads':
                point=lt[:3,:3]@np.array(item['center_m'])+lt[:3,3]
                w=np.r_[item['mass_kg']*np.asarray(c['gravity_m_s2']),np.zeros(3)]
            else:
                point=np.array(item['position_m']);f=np.array(item['force_n']);m=np.array(item.get('moment_n_m',[0,0,0]))
                if item.get('frame','link')=='link':f=lt[:3,:3]@f;m=lt[:3,:3]@m
                if item.get('position_frame',item.get('frame','link'))=='link':point=lt[:3,:3]@point+lt[:3,3]
                w=np.r_[f,m]
            add(item['name'],w,point,item.get('scalable',True))
    fixed_internal={p['name']:p for p in fixed.get('actuation_loads',[])}
    for port in full.get('actuation_loads',[]):
        if port['link']!=link:continue
        a=fixed_internal[port['name']];fw=np.r_[a['force_n'],a['moment_n_m']]
        vw=np.r_[port['force_n'],port['moment_n_m']]-fw;point=np.asarray(port['position_m'])
        if not np.allclose(point,a['position_m'],atol=1e-12,rtol=0):raise RuntimeError('fixed/full actuation attachment mismatch')
        add(port['name'],fw,point,False,mandatory=True);add(port['name'],vw,point,True,mandatory=True)
    if set(component['ports'])-used:raise ValueError(f'component {link} has unused ports; check explicit load mapping')
    return {'loads':loads,'ports':transfers,'world_from_component':world.tolist()}


def add_surface_centers(transfer,info,selectors):
    from .geometry import select_faces
    t=np.asarray(transfer['world_from_component']);rotation=t[:3,:3];origin=t[:3,3]
    transfer['selected_faces']={name:select_faces(info,selector) for name,selector in selectors.items()}
    for port in transfer['ports']:
        faces=[f for f in info['faces'] if f['id'] in transfer['selected_faces'][port['port']]]
        center=sum((np.asarray(f['centroid_mm'])*f['area_mm2'] for f in faces),np.zeros(3))/sum(f['area_mm2'] for f in faces)
        port['world_surface_centroid_m']=(rotation@(center*.001)+origin).tolist()
        port['moment_n_mm_about_surface_centroid']=(np.asarray(port['moment_n_mm_at_application'])+np.cross(np.asarray(port['point_mm'])-center,port['force_n'])).tolist()
    return transfer
