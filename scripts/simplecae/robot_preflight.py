"""Posed world-frame wrench preview; shares component transfer with the solver."""
from pathlib import Path
import html
import numpy as np
from .case import write_json


def world_load(item,kin,gravity,payload=False):
    t=kin['frames'][item['link']]
    if payload:
        point=t[:3,:3]@np.asarray(item['center_m'])+t[:3,3]
        f=item['mass_kg']*np.asarray(gravity);m=np.zeros(3)
    else:
        point=np.asarray(item['position_m']);f=np.asarray(item['force_n']);m=np.asarray(item.get('moment_n_m',[0,0,0]))
        if item.get('frame','link')=='link':f=t[:3,:3]@f;m=t[:3,:3]@m
        if item.get('position_frame',item.get('frame','link'))=='link':point=t[:3,:3]@point+t[:3,3]
    return {'name':item['name'],'link':item['link'],'category':'payload' if payload else 'external',
            'point_world_m':point.tolist(),'force_world_n':f.tolist(),'moment_world_n_m':m.tolist(),
            'scalable':item.get('scalable',True)}


def overlays(robot,c,kin,path_full,transfers=()):
    w=[world_load(p,kin,c['gravity_m_s2'],True) for p in c.get('payloads',[])]
    w += [world_load(p,kin,c['gravity_m_s2']) for p in c.get('loads',[])]
    for p in path_full.get('actuation_loads',[]):
        row=world_load(p,kin,c['gravity_m_s2']);row['category']='actuation';row['scalable']=None;w.append(row)
    for link,d in robot['links'].items():
        if not d['mass_kg']:continue
        t=kin['frames'][link]
        w.append({'name':'self-weight:'+link,'link':link,'category':'self_weight',
                  'point_world_m':(t[:3,:3]@d['com_m']+t[:3,3]).tolist(),
                  'force_world_n':(d['mass_kg']*np.asarray(c['gravity_m_s2'])).tolist(),
                  'moment_world_n_m':[0,0,0],'scalable':False})
    for item in transfers:
        for p in item['ports']:
            point=p.get('world_surface_centroid_m',p['world_point_m'])
            moment=p['world_moment_n_m_at_application']
            if 'moment_n_mm_about_surface_centroid' in p:
                moment=(np.asarray(item['world_from_component'])[:3,:3]@np.asarray(p['moment_n_mm_about_surface_centroid'])*.001).tolist()
            w.append({'name':item['link']+'/'+p['port']+(':variable' if p['scalable'] else ':fixed'),
                      'link':item['link'],'category':'component_transfer','point_world_m':point,
                      'force_world_n':p['world_force_n'],'moment_world_n_m':moment,
                      'scalable':p['scalable']})
    pads=[];g=c.get('grasp',{});loads={p['name']:p for p in c.get('loads',[])}
    for pad in g.get('pad_contacts',[]):
        load=loads[pad['normal_load_name']];t=kin['frames'][load['link']]
        row=world_load(load,kin,c['gravity_m_s2']);normal=np.asarray(row['force_world_n']);normal=normal/np.linalg.norm(normal)
        pads.append({'name':pad['normal_load_name'],'link':load['link'],
                     'center_world_m':(t[:3,:3]@np.asarray(pad['center_link_m'])+t[:3,3]).tolist(),
                     'normal_on_finger_world':normal.tolist(),
                     'tangent_u_world':(t[:3,:3]@pad['tangent_u_link']).tolist(),
                     'tangent_v_world':(t[:3,:3]@pad['tangent_v_link']).tolist(),
                     'half_extents_m':pad['half_extents_m'],'normal_force_n':float(np.linalg.norm(row['force_world_n']))})
    probes=[]
    for p in c.get('probes',[]):
        if p['type']=='point':
            t=kin['frames'][p['link']];probes.append({'name':p['name'],'point_world_m':(t[:3,:3]@p['point_m']+t[:3,3]).tolist(),'type':'point','direction_world':p.get('direction')})
    return {'wrenches':w,'pads':pads,'probes':probes,
            'units':{'geometry':'m','force':'N','moment':'N m','component_geometry':'mm','component_moment':'N mm'}}


def preview_robot(path,c,out):
    from .robot import read_urdf,forward_kinematics,static_wrenches,transform
    from .actuation import closed_statics,reaction_summary
    from .component_transfer import transfer_loads,add_surface_centers
    from .sources import SourceGuard,source_paths
    from .geometry import inspect,select_faces
    from .case import load_case
    from .product import robot_visualization,embed_robot_viewer,STYLE
    from .actuation_report import path_table
    guard=SourceGuard(source_paths(c)|{Path(path).resolve()})
    robot=read_urdf(c['model']['path'],c['model']['package_roots'],c.get('massless_links',[]))
    guard.add([a['path'] for a in robot['assets']])
    if any(guard.hashes[a['path']]!=a['sha256'] for a in robot['assets']):raise RuntimeError('URDF asset changed while reading preview')
    component_names=[p['link'] for p in c.get('components',[])]
    if len(set(component_names))!=len(component_names) or set(component_names)-set(robot['links']):raise ValueError('components must name unique known links')
    if set(c.get('required_components',[]))-set(component_names):raise ValueError('required component FEM is missing')
    if any(p['link'] not in robot['links'] for field in ('loads','payloads') for p in c.get(field,[])):raise ValueError('load/payload references unknown link')
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    regions={};geometries={}
    for component in c.get('components',[]):
        template=load_case(Path(component['case_path']));model=template['model']
        info=inspect(Path(model['path']),out/(component['link'].encode().hex()[:80]+'.geometry.json'),model)
        geometries[component['link']]=info
        regions[component['link']]={n:select_faces(info,s) for n,s in component['ports'].items()}
    base=transform(c.get('base_pose',{}).get('xyz_m',[0,0,0]),c.get('base_pose',{}).get('rpy_rad',[0,0,0]))
    records=[]
    for pose in c['poses']:
        guard.check();kin=forward_kinematics(robot,pose['joints'],base)
        full=static_wrenches(robot,kin,c['gravity_m_s2'],c.get('payloads',[]),c.get('loads',[]))
        fixed=static_wrenches(robot,kin,c['gravity_m_s2'],[p for p in c.get('payloads',[]) if not p.get('scalable',True)],
                              [p for p in c.get('loads',[]) if not p.get('scalable',True)])
        sf=closed_statics(robot,c,kin,full);sx=closed_statics(robot,c,kin,fixed,fixed=True);transfers=[]
        for component in c.get('components',[]):
            t=transfer_loads(robot,c,component,kin,sf,sx);t['link']=component['link']
            add_surface_centers(t,geometries[t['link']],component['ports'])
            transfers.append(t)
        efforts={n:{'holding_effort':v,'units':'N' if robot['joints'][n]['type']=='prismatic' else 'N m','utilization':None} for n,v in full['actuator_efforts'].items()}
        records.append({'name':pose['name'],'status':'preview_only','actuator_efforts':efforts,
                        'center_of_mass_world_m':full['center_of_mass_world_m'].tolist() if full['center_of_mass_world_m'] is not None else None,
                        'joint_positions':kin['positions'],'link_frames_world':{n:t.tolist() for n,t in kin['frames'].items()},
                        'actuation_reaction_assessment':reaction_summary(sf),'component_ports':transfers,
                        'joint_support_wrenches_world':{n:w.tolist() for n,w in sf['joint_wrenches'].items()},
                        'world_external_wrench':full['world_external_wrench'].tolist(),
                        'wrench_overlays':overlays(robot,c,kin,sf,transfers)})
    visualization=robot_visualization(robot,c,records);guard.check()
    data={'schema_version':'simplecae-robot-preview-1.0','case':c,'source_files_sha256':guard.hashes,'poses':records,'display':visualization,
          'scope':'Geometry and declared rigid-static load path only. No FE solve, stress, displacement, convergence, contact LP verdict or product load rating. Point-in-material check awaits meshing.'}
    write_json(out/'preview.json',data)
    body='<h1>机器人求解前：核对姿态与载荷路径</h1><p>按实际 URDF visual 显示全部声明姿态。世界几何单位 m；STEP 与部件接口单位 mm；力矩从 N·m 转入部件时乘1000。箭头长度分别按最大力、最大力矩归一化，仅用于展示方向。</p><p><b>本页仅预览。</b> 尚未计算强度、刚度、接触平衡或额定承载。三维外形的加载箭头不代表接触区域已实测；面积平均测点的面定义在部件表中。</p>'
    body+=embed_robot_viewer(visualization)
    if c.get('elastic_transfer',{}).get('joint_compliance'):
        body+='<h2>声明的等效关节柔度</h2><p>仅指定轴向为线性弹簧，其他方向理想刚性；预览尚未求解连杆变形或判定末端精度。刚度必须匹配当前保持／制动／通电状态。</p><table><tr><th>关节</th><th>刚度（键名含单位）</th><th>来源与适用状态</th><th>已核实</th></tr>'
        for name,s in c['elastic_transfer']['joint_compliance'].items():
            k=next(k for k in s if k.endswith('_stiffness_n_m_rad') or k.endswith('_stiffness_n_m'))
            body+='<tr><td>'+html.escape(name)+'</td><td>'+html.escape(k+': '+str(s[k]))+'</td><td>'+html.escape(s['reference'])+'</td><td>'+('是' if s['verified'] else '否')+'</td></tr>'
        body+='</table>'
    for record in records:
        body+='<h2>'+html.escape(record['name'])+'</h2>'+path_table(record['actuation_reaction_assessment'])
        rows=''
        for t in record['component_ports']:
            for port in t['ports']:
                def vec(v):return '['+', '.join(f'{x:.6g}' if abs(x)>1e-12 else '0' for x in v)+']'
                rows+='<tr><td>'+html.escape(t['link']+'/'+port['port'])+('：可缩放' if port['scalable'] else '：固定')+'</td><td>'+html.escape(str(t['selected_faces'][port['port']]))+'</td><td>'+vec(port['point_mm'])+'</td><td>'+vec(port['force_n'])+'</td><td>'+vec(port['moment_n_mm_about_surface_centroid'])+'</td></tr>'
        body+='<h3>部件端口：CAD坐标下的等效载荷</h3><table><tr><th>端口</th><th>材料面</th><th>表示点 mm</th><th>合力 N</th><th>关于面中心力矩 N·mm</th></tr>'+rows+'</table>'
    body+='<details><summary>完整帧、载荷与来源</summary><pre>'+html.escape(__import__('json').dumps(data,ensure_ascii=False,indent=2))+'</pre></details>'
    (out/'preview.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SimpleCAE robot load preview</title><style>'+STYLE+'table{width:100%;border-collapse:collapse}td,th{border:1px solid #cbd5df;padding:8px;font-size:14px;overflow-wrap:anywhere}</style>'+body+'</html>',encoding='utf-8')
    return {'preview':str(out/'preview.html'),'data':str(out/'preview.json'),'meaning':data['scope']}
