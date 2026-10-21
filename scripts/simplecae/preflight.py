"""Lightweight selectable surface and declared-wrench preview, without a solve."""
from .paths import resource_root
from pathlib import Path
import json,html
import numpy as np
from .geometry import session,inventory,select_faces
from .case import write_json

def surface_data(model):
    path=Path(model['path'])
    with session(path,model) as g:
        info=inventory(g,path)
        if model.get('interface_manifest'):
            from .bridge import resolve_interfaces
            info['interfaces']=resolve_interfaces(model['interface_manifest'],info)
        if model.get('expected_bbox_mm') is not None and not np.allclose(info['bbox_mm'],model['expected_bbox_mm'],rtol=0,atol=1e-3):
            raise ValueError('preview dimensions differ from model.expected_bbox_mm; inspect units and the imported model')
        span=float(np.max(np.array(info['bbox_mm'][1])-info['bbox_mm'][0]))
        g.option.setNumber('Mesh.MeshSizeMax',span/16);g.option.setNumber('Mesh.MeshSizeMin',span/100)
        g.option.setNumber('Mesh.MeshSizeFromCurvature',12);g.model.mesh.generate(2)
        ids,raw,_=g.model.mesh.getNodes();xyz=np.asarray(raw).reshape(-1,3)
        indices={int(n):i for i,n in enumerate(ids)};triangles=[];faces=[]
        element=g.model.mesh.getElementType('Triangle',1)
        for face in info['faces']:
            _,nodes=g.model.mesh.getElementsByType(element,face['id'])
            for tri in np.asarray(nodes).reshape(-1,3):
                triangles.append([indices[int(n)] for n in tri]);faces.append(face['id'])
        if len(triangles)>100000:raise ValueError('surface preview exceeds display budget; partition or simplify display geometry upstream')
        return {'geometry':info,'xyz':xyz.tolist(),'triangles':triangles,'triangle_faces':faces,'supports':[], 'loads':[]}


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

def preview_case(path,out):
    from .api import check_case
    from .sources import SourceGuard,source_paths
    from .product import STYLE,payload
    c=check_case(path)
    if c['schema_version']=='robot-1.0':
        from .robot_preflight import preview_robot
        return preview_robot(path,c,out)
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    guard=SourceGuard(source_paths(c)|{Path(path).resolve()})
    parts=c.get('bodies',[{'name':'body','model':c['model']}]) if 'model' in c else c['bodies']
    display={'xyz':[],'triangles':[],'triangle_faces':[],'supports':[],'loads':[]};table=[]
    for body in parts:
        data=surface_data(body['model']);info=data['geometry'];name=body['name']
        placement=body.get('placement',{})
        from .assembly import rotation_rpy
        rotation=rotation_rpy(placement.get('rpy_rad',[0,0,0]));translation=np.array(placement.get('translation_mm',[0,0,0]))
        xyz=np.array(data['xyz'])@rotation.T+translation;offset=len(display['xyz'])
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
        for load in c['loads']:
            if load.get('body',name)!=name:continue
            selected=select_faces(info,load['selector']);selected_faces=[f for f in info['faces'] if f['id'] in selected]
            center=sum((np.array(f['centroid_mm'])*f['area_mm2'] for f in selected_faces),np.zeros(3))/sum(f['area_mm2'] for f in selected_faces)
            center=rotation@center+translation
            point=np.array(load.get('application_point_mm',center.tolist()));force=np.array(load['total_force_n']);moment=np.array(load.get('total_moment_n_mm',[0,0,0]))
            shifted=moment+np.cross(point-center,force)
            row={'kind':'load','name':load['name'],'body':name,'faces':selected,'point_mm':point.tolist(),'centroid_mm':center.tolist(),
                 'force_n':force.tolist(),'moment_at_point_n_mm':moment.tolist(),'moment_about_surface_center_n_mm':shifted.tolist(),'scalable':load.get('scalable',True)}
            table.append(row);display['loads'].append(row)
    diagnostics=support_diagnostics(display,table)
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
        rows+='<tr><td>'+html.escape(row['name'])+'</td><td>'+html.escape(row['body'])+' / 面 '+html.escape(str(row['faces']))+'</td><td>'+html.escape(description)+'</td></tr>'
    script=(resource_root()/'assets/preflight.js').read_text(encoding='utf-8')
    page='<html lang="zh-CN"><meta charset="utf-8"><title>SimpleCAE 受力预览</title><style>'+STYLE+'</style><h1>先确认固定与受力</h1><p>蓝色为约束面，橙色为加载面。箭头位于声明的载荷表示点；关于面中心的等效力矩列在下表。本页没有求解强度或位移。</p><canvas id="preflight-canvas"></canvas><p id="preflight-pick"></p><button id="preflight-reset">复位视角</button><table><tr><th>区域</th><th>零件</th><th>约束 / 力与力矩</th></tr>'+rows+'</table><script id="preflight-data" type="application/json">'+payload(display)+'</script><script>'+script+'</script></html>'
    message=f"表面预览的共同刚体模式：已约束 {diagnostics['rank']}/6；剩余 {diagnostics['missing_modes']}，涉及 {', '.join(diagnostics['missing_components']) or '无'}。T为平移、R为转动；最终仍须体网格检查，装配还须检查各部件连接与独立机构运动。"
    page=page.replace('<canvas id="preflight-canvas">','<p role="status">'+html.escape(message)+'</p><canvas id="preflight-canvas">')
    if c.get('bolts'):
        rows=''.join('<li>'+html.escape(b['name'])+'：预紧 '+str(b['preload_n'])+' N；轴向刚度 '+str(b['axial_stiffness_n_mm'])+' N/mm；轴向许用拉力 '+str(b['allowable_tension_n'])+' N；世界轴 '+html.escape(str(b['axis']))+'</li>' for b in c['bolts'])
        page=page.replace('<canvas id="preflight-canvas">','<p>等效轴向螺栓：先力控预紧，随后锁定调整量，再施加使用载荷。未建模螺纹、扭矩换算或螺栓剪切／弯曲。</p><ul>'+rows+'</ul><canvas id="preflight-canvas">')
    (out/'preview.html').write_text(page,encoding='utf-8');return {'preview':str(out/'preview.html'),'meaning':'Geometry/load preview only; no numerical verdict.'}
