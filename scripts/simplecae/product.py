"""Local guided intake and real posed-robot display data."""
from .paths import resource_root
from pathlib import Path
import json
import html
import numpy as np
from .case import CONDITIONS, write_json


STYLE='body{font:16px system-ui;max-width:1080px;margin:36px auto;padding:0 20px;line-height:1.7;color:#1c3048}fieldset{border:1px solid #ccd6e2;border-radius:12px;padding:20px;margin:20px 0}label{display:block;margin:10px 0}input,select,textarea,button{font:inherit;padding:8px;border:1px solid #afbdd0;border-radius:7px}input[type=number]{width:160px}button{background:#194e89;color:white;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5fa;padding:20px}.note{background:#fff5dc;padding:15px;border-radius:10px}canvas{width:100%;height:460px;background:#f2f5fa;touch-action:none}'


def payload(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')


def omission_label(text):
    if text=='Propagation of component elastic deformation through the URDF chain':return '各部件弹性位移沿URDF连接链的耦合传递；独立部件FEM不会自动给出整机开口误差'
    if text.startswith('Component '):
        name,_,rest=text[len('Component '):].partition(': ')
        return '零件 '+name+'：'+omission_label(rest)
    labels={'Dynamics, acceleration, impact and control stability':'运动、加速、冲击及控制稳定性',
        'Joint/mount/ground strength and compliance':'关节、安装与地面的强度及柔度',
        'Joint strength, unmodeled joint compliance directions, mount/ground strength and compliance':'关节强度、未建模方向的关节柔度、安装与地面的强度及柔度',
        'Coupled continuum elasticity, section warping compatibility, unmodeled joint directions, backlash, control response, mount compliance and higher-order deformation of the robot':'完整连续体耦合、截面翘曲相容、未建模关节方向、齿隙、控制响应、安装柔度与高阶变形',
        'Detailed contact stress and friction calibration':'局部接触应力及实际摩擦参数校准',
        'Unspecified link FEM and material/manufacturing behavior':'未声明的零件有限元分析及材料、制造行为',
        'Buckling and stability (including local plate buckling)':'整体与局部屈曲稳定性',
        'Bolts, anchors, wall/substrate, welds, adhesive and mounting failure':'螺钉、锚固、墙体、焊缝、胶接及安装破坏',
        'Contact, separation, slip, bolt preload and unspecified joint compliance':'接触、分离、滑移、预紧及未建模的连接柔度',
        'Plastic redistribution, fracture and ultimate collapse':'塑性重分布、断裂与极限破坏',
        'Fatigue, impact, vibration and dynamic amplification':'疲劳、冲击、振动与动态放大',
        'Creep, sustained-load duration and temperature effects':'长期蠕变、使用时长与温度影响',
        'Unresolved infill details, layer damage, delamination and manufacturing defects':'未解析的填充细节、层间损伤、分层与制造缺陷',
        'Directional material properties unless explicitly calibrated':'未明确校准的方向性材料性能',
        'Material/manufacturing variability outside the declared calibration':'超出校准范围的材料与制造波动',
        'Residual stress and other unspecified non-scaling loads':'残余应力与其他未明确建模的固定作用',
        'Nonlinear buckling collapse and calibrated imperfection sensitivity':'非线性屈曲塌陷与初始缺陷敏感性'}
    return labels.get(text,text)


def prepare(model,out,settings=None):
    model=Path(model).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    settings={'path':str(model),**(settings or {})}
    if model.suffix.lower()=='.urdf':
        from .robot import read_urdf,ROBOT_CONDITIONS
        robot=read_urdf(model)
        independent=[{'name':n,'type':j['type'],'lower':j['lower'],'upper':j['upper']} for n,j in robot['joints'].items() if j['type']!='fixed' and not j['mimic']]
        data={'kind':'robot','model':{'path':str(model)},'joints':independent,'links':list(robot['links']),'conditions':list(ROBOT_CONDITIONS)}
    else:
        from .geometry import inspect
        info=inspect(model,out/'geometry.json',settings)
        data={'kind':'solid','model':settings,'geometry':info,'conditions':list(CONDITIONS)}
        from .support_presets import PRESETS
        data['support_presets']=PRESETS
        from .preflight import surface_data
        data['surface']=surface_data(settings)
    write_json(out/'intake.json',data)
    script=(resource_root()/'assets/guide.js').read_text(encoding='utf-8')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>SimpleCAE 使用条件向导</title><style>'+STYLE+'</style><h1>先说明怎么用，再判断是否合适</h1><p>这一步整理分析条件，不会自动推断材料、安装方式或额定承载。</p><div id="guide"></div><script id="intake" type="application/json">'+payload(data)+'</script><script>'+script+'</script></html>'
    if data['kind']=='solid':
        support_guide=(resource_root()/'assets/support-guide.js').read_text(encoding='utf-8')
        page=page.replace('</html>','<script>'+support_guide+'</script></html>')
        selector='<fieldset><legend>在三维模型上确认整面</legend><select id="preflight-mode"><option value="">只查看</option><option value="support">点选固定面</option><option value="load">点选加载面</option></select><canvas id="preflight-canvas"></canvas><p id="preflight-pick">拖动旋转，滚轮缩放；选择模式后点击可见的完整面。局部贴片需上游分区。</p><button type="button" id="preflight-reset">复位视角</button></fieldset>'
        picker=(resource_root()/'assets/preflight.js').read_text(encoding='utf-8')
        page=page.replace('<div id="guide"></div>',selector+'<div id="guide"></div>').replace('</html>','<script id="preflight-data" type="application/json">'+payload(data['surface'])+'</script><script>'+picker+'</script></html>')
    (out/'guide.html').write_text(page,encoding='utf-8')
    return {'guide':str(out/'guide.html'),'intake':str(out/'intake.json'),'meaning':'No solve yet; user or agent supplies physical facts, exports a case, then analyzes in a fresh directory.'}


def robot_visualization(robot,c,records):
    import trimesh
    from .robot import forward_kinematics,transform
    meshes=[];omissions=[];simplifications=[]
    for link,info in robot['links'].items():
        for visual in info.get('visuals',[]):
            shape=visual['shape'];p=visual['parameters']
            try:
                if shape=='mesh':
                    scene=trimesh.load_scene(p['path'],process=False,skip_materials=True)
                    parts=[]
                    for node in scene.graph.nodes_geometry:
                        t,g=scene.graph[node];m=scene.geometry[g].copy();m.apply_transform(t);parts.append(m)
                    if not parts:raise ValueError('empty visual scene')
                    m=trimesh.util.concatenate(parts);m.apply_scale(p['scale'])
                elif shape=='box':m=trimesh.creation.box(extents=p['size'])
                elif shape=='cylinder':m=trimesh.creation.cylinder(radius=p['radius'],height=p['length'],sections=32)
                else:m=trimesh.creation.icosphere(subdivisions=2,radius=p['radius'])
                from .display_mesh import simplify_display
                m,simplification=simplify_display(m)
                if simplification:simplifications.append(dict(simplification,link=link))
                m.apply_transform(visual['origin']);meshes.append((link,m))
            except Exception as exc:omissions.append({'link':link,'reason':str(exc)})
    base=transform(c.get('base_pose',{}).get('xyz_m',[0,0,0]),c.get('base_pose',{}).get('rpy_rad',[0,0,0]))
    poses=[]
    for spec,record in zip(c['poses'],records):
        kin=forward_kinematics(robot,spec['joints'],base);xyz=[];triangles=[];names=[]
        for link,m in meshes:
            vertices=trimesh.transform_points(m.vertices,kin['frames'][link]);offset=len(xyz)
            xyz.extend(vertices.tolist());triangles.extend((m.faces+offset).tolist());names.extend([link]*len(m.faces))
        markers=[]
        for n,t in kin['frames'].items():
            parent=robot['parents'].get(n);effort=record['actuator_efforts'].get(parent,{})
            markers.append({'xyz':t[:3,3].tolist(),'name':n,'utilization':effort.get('utilization'),'effort':effort.get('holding_effort'),'units':effort.get('units')})
        for p in c.get('payloads',[]):
            t=kin['frames'][p['link']];markers.append({'xyz':(t[:3,:3]@p['center_m']+t[:3,3]).tolist(),'name':p['name']+' '+str(p['mass_kg'])+' kg','payload':True})
        edges=[[kin['frames'][j['parent']][:3,3].tolist(),kin['frames'][j['child']][:3,3].tolist()] for j in robot['joints'].values()]
        poses.append({'name':record['name'],'xyz':xyz,'triangles':triangles,'triangle_links':names,'markers':markers,'edges':edges,
            'com':record['center_of_mass_world_m'],'contacts':c['base'].get('points_world_m',[]),'contact_feasible':(record.get('contact_equilibrium') or {}).get('feasible'),
            'status':record['status'],'efforts':record['actuator_efforts'],'wrench_overlays':record.get('wrench_overlays',{'wrenches':[],'pads':[],'probes':[]}),
            'reaction_pairs':(record.get('actuation_reaction_assessment') or {}).get('pairs',[])})
    return {'poses':poses,'display_omissions':omissions,'display_simplifications':simplifications,'meaning':'URDF visual geometry with explicitly recorded display approximations and declared pose; rigid positions in metres. Not FEM deformation or collision analysis.'}


def embed_robot_viewer(data):
    script=(resource_root()/'assets/robot-viewer.js').read_text(encoding='utf-8')
    controls='<style>.robot-overlay-controls{display:flex;flex-wrap:wrap;gap:8px 22px;padding:12px 18px}.robot-overlay-controls label{display:inline-flex;gap:5px;align-items:center;margin:4px 0}</style><fieldset class="robot-overlay-controls"><legend>载荷叠加</legend><label><input id="robot-wrenches" type="checkbox" checked>力与力矩</label> <label><input id="robot-transfers" type="checkbox">部件转移载荷</label> <label><input id="robot-self-weight" type="checkbox">各零件重力</label> <label><input id="robot-pads" type="checkbox" checked>有限软垫</label> <label><input id="robot-paths" type="checkbox" checked>驱动反力路径</label></fieldset>'
    if data.get('display_simplifications'):
        controls+='<p>高精度外形仅在本显示中简化：'+html.escape('; '.join(s['link']+f" 最大原顶点移动 {s['max_original_vertex_shift_m']*1000:.4g} mm" for s in data['display_simplifications']))+'。细小特征可能消失；有限元与源文件仍使用原几何。</p>'
    return '<section><h2>查看姿态与支撑</h2><label>使用姿态 <select id="robot-pose"></select></label><button id="robot-reset">重置机器人视角</button>'+controls+'<canvas id="robot-canvas"></canvas><p id="robot-legend"></p><p id="robot-pick">拖动旋转、滚轮缩放；点选关节或载荷标记查看帧、力与力矩。实体外形来自 URDF visual，不代表零件强度已经验证。</p></section><script id="robot-data" type="application/json">'+payload(data)+'</script><script>'+script+'</script>'
