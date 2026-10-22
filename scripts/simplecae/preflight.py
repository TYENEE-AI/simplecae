"""Lightweight selectable surface and declared-wrench preview, without a solve."""
from .paths import resource_root
from pathlib import Path
from .defaults import DEFAULT_PREVIEW_TRIANGLES
import json,html
import numpy as np
from .geometry import session,inventory,select_faces
from .case import write_json

def surface_data(model, max_triangles=DEFAULT_PREVIEW_TRIANGLES):
    path=Path(model['path'])
    with session(path,model) as g:
        info=inventory(g,path)
        if model.get('interface_manifest'):
            from .bridge import resolve_interfaces
            info['interfaces']=resolve_interfaces(model['interface_manifest'],info)
        if model.get('expected_bbox_mm') is not None and not np.allclose(info['bbox_mm'],model['expected_bbox_mm'],rtol=0,atol=1e-3):
            raise ValueError('preview dimensions differ from model.expected_bbox_mm; inspect units and the imported model')
        span=float(np.max(np.array(info['bbox_mm'][1])-info['bbox_mm'][0]))
        # Only the display tessellation is coarsened. CAD regions and solver
        # meshes never use this budget or a sampled subset of faces.
        element=g.model.mesh.getElementType('Triangle',1)
        attempts=[];scale=1.
        for attempt in range(3) if max_triangles>=12 else ():
            if attempt:g.model.mesh.clear()
            g.option.setNumber('Mesh.MeshSizeMax',span/16*scale)
            g.option.setNumber('Mesh.MeshSizeMin',span/100*scale)
            g.option.setNumber('Mesh.MeshSizeFromCurvature',12/scale)
            g.model.mesh.generate(2)
            count=len(g.model.mesh.getElementsByType(element)[0]);attempts.append(count)
            if count<=max_triangles:break
            scale*=max(1.5,(count/max_triangles)**.5*1.2)
        if not attempts or attempts[-1]>max_triangles:
            lo,hi=info['bbox_mm'];xyz=[[hi[i] if n>>i&1 else lo[i] for i in range(3)] for n in range(8)]
            quads=[(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)]
            triangles=[t for a,b,c,d in quads for t in ([a,b,c],[a,c,d])] if max_triangles>=12 else []
            return {'geometry':info,'xyz':xyz if triangles else [],'triangles':triangles,
                    'triangle_faces':[None]*len(triangles),'supports':[],'loads':[],
                    'picking_enabled':False,'tessellation':{'mode':'bounds_only' if triangles else 'inventory_only',
                    'budget':max_triangles,'attempt_triangle_counts':attempts,'triangle_count':len(triangles)}}
        ids,raw,_=g.model.mesh.getNodes();xyz=np.asarray(raw).reshape(-1,3)
        indices={int(n):i for i,n in enumerate(ids)};triangles=[];faces=[]
        element=g.model.mesh.getElementType('Triangle',1)
        for face in info['faces']:
            _,nodes=g.model.mesh.getElementsByType(element,face['id'])
            for tri in np.asarray(nodes).reshape(-1,3):
                triangles.append([indices[int(n)] for n in tri]);faces.append(face['id'])
        return {'geometry':info,'xyz':xyz.tolist(),'triangles':triangles,'triangle_faces':faces,'supports':[], 'loads':[],
                'picking_enabled':True,'tessellation':{'mode':'coarsened' if len(attempts)>1 else 'full',
                'budget':max_triangles,'attempt_triangle_counts':attempts,'triangle_count':len(triangles)}}


def display_notice(records):
    modes=[r['mode'] for r in records]
    if any(m in ('bounds_only','inventory_only') for m in modes):
        return '显示预算不足：部分模型仅显示包围盒或区域清单，已禁用面拾取和预览支承秩判断。下表仍来自完整 CAD 面；不影响求解几何或判据。'
    if 'coarsened' in modes:
        return '为适应显示预算已降低显示网格精度，完整 CAD 区域选择与求解网格未改变。'
    return '显示网格仅用于边界预览，不提供求解结论。'


def support_diagnostics(display,regions):
    from .constraints import rigid_diagnostics
    fixed={}
    for region in regions:
        if region['kind']!='support':continue
        selected={region['body']+':'+str(face) for face in region['faces']}
        for triangle,face in zip(display['triangles'],display['triangle_faces']):
            if face not in selected:continue
            for node in triangle:fixed.setdefault(node,set()).update(region['dofs'])
    result=rigid_diagnostics({n:np.asarray(p) for n,p in enumerate(display['xyz'])},fixed)
    result['evidence']='Surface preview nodes only; actual volume mesh and assembly connections still require independent checks.'
    return result

def preview_case(path,out,max_triangles=DEFAULT_PREVIEW_TRIANGLES):
    if type(max_triangles) is not int or max_triangles<12:raise ValueError('preview triangle budget must be an integer >=12')
    from .api import check_case
    from .sources import SourceGuard,source_paths
    from .product import STYLE,payload
    c=check_case(path)
    if c['schema_version']=='robot-1.0':
        from .robot_preflight import preview_robot
        return preview_robot(path,c,out)
    if c['schema_version']=='thermal-solid-1.0':
        return preview_thermal(path,c,out,max_triangles=max_triangles)
    if c['schema_version'] not in ('1.0','2.0','assembly-1.0','modal-solid-1.0'):
        raise ValueError('Surface preview supports solid/assembly structure, robot, modal and solid thermal cases; '
                         'this calculation has no supported CAD boundary preview')
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    guard=SourceGuard(source_paths(c)|{Path(path).resolve()})
    parts=c.get('bodies',[{'name':'body','model':c['model']}]) if 'model' in c else c['bodies']
    display={'xyz':[],'triangles':[],'triangle_faces':[],'supports':[],'loads':[],'picking_enabled':True};table=[];tessellations=[]
    for body in parts:
        data=surface_data(body['model'],max_triangles//len(parts));info=data['geometry'];name=body['name']
        tessellations.append(dict(data['tessellation'],body=name))
        display['picking_enabled'] &= data['picking_enabled']
        placement=body.get('placement',{})
        from .assembly import rotation_rpy
        rotation=rotation_rpy(placement.get('rpy_rad',[0,0,0]));translation=np.array(placement.get('translation_mm',[0,0,0]))
        xyz=np.array(data['xyz']).reshape(-1,3)@rotation.T+translation;offset=len(display['xyz'])
        display['xyz']+=xyz.tolist();display['triangles']+=[[n+offset for n in t] for t in data['triangles']]
        display['triangle_faces']+=[f'{name}:{f}' for f in data['triangle_faces']]
        for support in c['supports']:
            if support.get('body',name)!=name:continue
            if c.get('reference_only'):
                if support['geometry_sha256']!=info['geometry_sha256']:raise ValueError('reference point belongs to a different source hash')
                table.append({'kind':'reference','name':support['name'],'body':name,'faces':[],'point_mm':support['point_mm'],'dofs':support['dofs']})
                continue
            selected=select_faces(info,support['selector']);display['supports'] += [f'{name}:{f}' for f in selected]
            table.append({'kind':'support','name':support['name'],'body':name,'faces':selected,'dofs':support.get('dofs',[1,2,3]),
                          'service_displacement_mm':support.get('service_displacement_mm',[0,0,0])})
        for load in c.get('loads',[]):
            if load.get('body',name)!=name:continue
            selected=select_faces(info,load['selector']);selected_faces=[f for f in info['faces'] if f['id'] in selected]
            center=sum((np.array(f['centroid_mm'])*f['area_mm2'] for f in selected_faces),np.zeros(3))/sum(f['area_mm2'] for f in selected_faces)
            center=rotation@center+translation
            point=np.array(load.get('application_point_mm',center.tolist()));force=np.array(load['total_force_n']);moment=np.array(load.get('total_moment_n_mm',[0,0,0]))
            shifted=moment+np.cross(point-center,force)
            row={'kind':'load','name':load['name'],'body':name,'faces':selected,'point_mm':point.tolist(),'centroid_mm':center.tolist(),
                 'force_n':force.tolist(),'moment_at_point_n_mm':moment.tolist(),'moment_about_surface_center_n_mm':shifted.tolist(),'scalable':load.get('scalable',True)}
            bounds=np.array([f['bbox_mm'] for f in selected_faces])
            size=float(np.linalg.norm(bounds[:,3:].max(axis=0)-bounds[:,:3].min(axis=0)))
            row['warnings']=['remote_application_point'] if np.linalg.norm(point-center)>.5*size else []
            row['distribution']=load.get('distribution','consistent')
            table.append(row);display['loads'].append(row)
    diagnostics=support_diagnostics(display,table) if display['picking_enabled'] else {
        'available':False,'rank':None,'missing_modes':None,'missing_components':[],
        'evidence':'Display fallback is not surface evidence; actual mesh must verify support rank.'}
    display['tessellations']=tessellations
    if c.get('reference_only'):
        from .constraints import rigid_diagnostics
        diagnostics=rigid_diagnostics({i:np.array(s['point_mm']) for i,s in enumerate(c['supports'])},{i:set(s['dofs']) for i,s in enumerate(c['supports'])})
        diagnostics['evidence']='Numerical reference points only; source hash/rank preview. Actual material inclusion, self-balanced wrench and equation forces are checked during native analysis.'
    guard.check();write_json(out/'preview.json',{'case':c,'display':display,'regions':table,'support_diagnostics':diagnostics,'scope':'Declared geometry, support components and equivalent force/couple; no stress or displacement solve.'})
    rows=''
    for row in table:
        if row['kind']=='reference':
            description='仅去除刚体运动的数值参考点 '+str(row['point_mm'])+' mm；不代表物理固定、接触或反力。原生求解还须验证材料内插与自平衡。'
        elif row['kind']=='support':
            description='限制位移：'+', '.join('XYZ'[d-1] for d in row['dofs'])+'；其他位移分量允许运动。'
            if any(row['service_displacement_mm']):description+='预紧及锁定阶段为零；使用阶段规定夹具位移 '+str(row['service_displacement_mm'])+' mm（世界坐标）。'
        else:
            description=('固定载荷' if not row['scalable'] else '可缩放载荷')+'；表示点 '+str(row['point_mm'])+' mm；合力 '+str(row['force_n'])+' N；关于面中心的等效力矩 '+str(row['moment_about_surface_center_n_mm'])+' N·mm。'
            if row['warnings']:description+=' 作用点远离载荷面中心，等效分配可能产生反向力；求解前会检查并保存节点力。'
        rows+='<tr><td>'+html.escape(row['name'])+'</td><td>'+html.escape(row['body'])+' / 面 '+html.escape(str(row['faces']))+'</td><td>'+html.escape(description)+'</td></tr>'
    script=(resource_root()/'assets/preflight.js').read_text(encoding='utf-8')
    page='<html lang="zh-CN"><meta charset="utf-8"><title>SimpleCAE 受力预览</title><style>'+STYLE+'</style><h1>先确认固定与受力</h1><p>蓝色为约束面，橙色为加载面。箭头位于声明的载荷表示点；关于面中心的等效力矩列在下表。本页没有求解强度或位移。</p><canvas id="preflight-canvas"></canvas><p id="preflight-pick"></p><button id="preflight-reset">复位视角</button><table><tr><th>区域</th><th>零件</th><th>约束 / 力与力矩</th></tr>'+rows+'</table><script id="preflight-data" type="application/json">'+payload(display)+'</script><script>'+script+'</script></html>'
    message=f"表面预览的共同刚体模式：已约束 {diagnostics['rank']}/6；剩余 {diagnostics['missing_modes']}，涉及 {', '.join(diagnostics['missing_components']) or '无'}。T为平移、R为转动；最终仍须体网格检查，装配还须检查各部件连接与独立机构运动。"
    page=page.replace('<canvas id="preflight-canvas">','<p role="status">'+html.escape(message)+'</p><canvas id="preflight-canvas">')
    if not display['picking_enabled']:page=page.replace(html.escape(message),'显示降级后不计算表面预览的支承秩。')
    page=page.replace('<canvas id="preflight-canvas">','<p>'+display_notice(tessellations)+'</p><canvas id="preflight-canvas">')
    if c.get('bolts'):
        rows=''.join('<li>'+html.escape(b['name'])+'：预紧 '+str(b['preload_n'])+' N；轴向刚度 '+str(b['axial_stiffness_n_mm'])+' N/mm；轴向许用拉力 '+str(b['allowable_tension_n'])+' N；世界轴 '+html.escape(str(b['axis']))+'</li>' for b in c['bolts'])
        page=page.replace('<canvas id="preflight-canvas">','<p>等效轴向螺栓：先力控预紧，随后锁定调整量，再施加使用载荷。未建模螺纹、扭矩换算或螺栓剪切／弯曲。</p><ul>'+rows+'</ul><canvas id="preflight-canvas">')
    (out/'preview.html').write_text(page,encoding='utf-8');return {'preview':str(out/'preview.html'),'meaning':'Geometry/load preview only; no numerical verdict.'}


def preview_thermal(path, case, out, max_triangles=DEFAULT_PREVIEW_TRIANGLES):
    """Inspect actual heat-boundary faces without requiring mechanical supports."""
    from .sources import SourceGuard, source_paths
    from .product import STYLE, payload
    guard = SourceGuard(source_paths(case) | {Path(path).resolve()})
    data = surface_data(case['model'],max_triangles)
    info = data['geometry']
    regions, occupied = [], set()
    for boundary in case['boundaries']:
        faces = select_faces(info, boundary['selector'])
        if occupied.intersection(faces):
            raise ValueError('Thermal boundary faces overlap; use one explicit boundary per face')
        occupied.update(faces)
        area = sum(f['area_mm2'] for f in info['faces'] if f['id'] in faces)
        row = dict(boundary, faces=faces, area_mm2=area)
        if boundary['type'] == 'heat_power':
            row['prescribed_power_w'] = boundary['total_heat_w']
        elif boundary['type'] == 'heat_flux':
            row['prescribed_power_w'] = boundary['flux_w_m2']*area*1e-6
        regions.append(row)
    unassigned = sorted({f['id'] for f in info['faces']}-occupied)
    diagnostics = {'temperature_reference_declared': any(b['type'] in ('temperature','convection') for b in regions),
                   'unassigned_insulated_face_ids': unassigned,
                   'volumetric_heat_w': case.get('volumetric_heat_w_m3',0)*info['volume_mm3']*1e-9}
    if case['mode'] == 'steady' and not diagnostics['temperature_reference_declared']:
        raise ValueError('Steady conduction requires a temperature reference or convection heat path')
    data['boundaries'] = regions
    scope = 'Declared thermal boundaries and CAD areas only; no temperature, heat balance, local flux or product verdict.'
    guard.check()
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=False)
    write_json(out/'preview.json', {'case':case, 'display':data, 'regions':regions,
                                    'thermal_diagnostics':diagnostics, 'scope':scope})
    units = {'temperature_c':'°C','total_heat_w':'W','flux_w_m2':'W/m²',
             'ambient_temperature_c':'°C','coefficient_w_m2k':'W/(m² K)'}
    rows = ''
    for r in regions:
        values = '; '.join(f'{k}={r[k]} {unit}' for k,unit in units.items() if k in r)
        rows += '<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in (
            r['name'],r['type'],r['faces'],f"{r['area_mm2']:.6g} mm²",values,r['basis']))+'</tr>'
    script = (resource_root()/'assets/preflight.js').read_text(encoding='utf-8')
    page = '<html lang="zh-CN"><meta charset="utf-8"><title>SimpleCAE 热边界预览</title><style>'+STYLE+'</style>'
    page += '<h1>先确认热输入与散热边界</h1><p>蓝色：规定温度；绿色：对流；橙色：热输入。未指定表面按绝热处理。本页不求解温度，也不验证换热系数。</p>'
    page += '<p role="status">'+display_notice([data['tessellation']])+'</p>'
    page += '<canvas id="preflight-canvas"></canvas><p id="preflight-pick"></p><button id="preflight-reset">复位视角</button>'
    page += '<table><tr><th>区域</th><th>边界类型</th><th>完整面</th><th>面积</th><th>声明值</th><th>依据</th></tr>'+rows+'</table>'
    page += '<p>未指定的绝热面：'+html.escape(str(unassigned))+'；体热源总功率：'+str(diagnostics['volumetric_heat_w'])+' W。</p>'
    page += '<script id="preflight-data" type="application/json">'+payload(data)+'</script><script>'+script+'</script></html>'
    (out/'preview.html').write_text(page,encoding='utf-8')
    return {'preview':str(out/'preview.html'),'meaning':scope}
