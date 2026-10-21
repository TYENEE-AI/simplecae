"""STEP interface measurements against explicit, source-bound references."""
from pathlib import Path
import html,json
import numpy as np
from .case import keys,number,vector,selector,sha256,write_json


def cylinder_axis(g,face):
    if g.model.getType(2,face).lower()!='cylinder':raise ValueError(f'face {face} is not an analytic cylinder; no axis inferred from a triangulated or arbitrary face')
    lo,hi=map(np.asarray,g.model.getParametrizationBounds(2,face));parameters=lo+(hi-lo)*np.array([.2113248654,.5,.7886751346])[:,None]
    samples=[[u,v] for u in parameters[:,0] for v in parameters[:,1]]
    derivatives=np.asarray(g.model.getDerivative(2,face,np.asarray(samples).ravel().tolist())).reshape(-1,2,3)
    axes=[]
    for coordinate in range(2):
        vectors=derivatives[:,coordinate];length=np.linalg.norm(vectors,axis=1)
        if np.any(length<1e-12):continue
        directions=vectors/length[:,None]
        if np.max(np.linalg.norm(np.cross(directions,directions[0]),axis=1))<1e-9:axes.append((coordinate,directions[0]))
    if len(axes)!=1:raise ValueError('cylindrical parameter axes are ambiguous; inspect the original analytic face')
    axial,axis=axes[0];circumferential=1-axial;coords=np.tile((lo+hi)*.5,(3,1));coords[:,circumferential]=parameters[:,circumferential]
    points=np.asarray(g.model.getValue(2,face,coords.ravel().tolist())).reshape(3,3)
    a,b,c=points;u=(b-a)/np.linalg.norm(b-a);v=np.cross(axis,u);v=v/np.linalg.norm(v)
    xy=np.column_stack(((points[1:]-a)@u,(points[1:]-a)@v))
    if abs(np.linalg.det(2*xy))<1e-12:raise ValueError('cylinder arc is too small to locate an axis reliably')
    center_xy=np.linalg.solve(2*xy,np.sum(xy*xy,axis=1));center=a+center_xy[0]*u+center_xy[1]*v
    radius=float(np.linalg.norm(center-a))
    if not np.allclose(np.linalg.norm(points-center,axis=1),radius,rtol=1e-8,atol=1e-8):raise ValueError('cylinder axis independent radial check failed')
    return {'face_id':face,'direction':axis.tolist(),'point_mm':center.tolist(),'radius_mm':radius,'method':'analytic cylinder parameter derivatives and independent circumferential circle fit'}


def load_interface_case(path):
    path=Path(path).resolve();c=json.loads(path.read_text(encoding='utf-8-sig'))
    from .schemas import check_contract
    check_contract(c,'interface')
    keys(c,['schema_version','model','provenance','frame','checks','notes'],['schema_version','model','provenance','checks'],'interface check')
    if c['schema_version']!='simplecae-interface-1.0':raise ValueError('unsupported interface check version')
    model=c['model'];model['path']=str((path.parent/model['path']).resolve())
    if Path(model['path']).suffix.lower() not in ('.step','.stp') or not Path(model['path']).is_file():raise ValueError('interface metrology currently requires an existing STEP/STP solid')
    if model.get('units','mm')!='mm':raise ValueError('STEP carries its own units and is imported into mm; do not rescale it as a mesh')
    if model.get('interface_manifest'):model['interface_manifest']=str((path.parent/model['interface_manifest']).resolve())
    provenance=c['provenance'];doc=provenance['reference_document'];doc['path']=str((path.parent/doc['path']).resolve())
    if not Path(doc['path']).is_file() or sha256(Path(doc['path']))!=doc['sha256'].lower():raise ValueError('interface reference document is missing or changed')
    if 'frame' in c:
        vector(c['frame']['xyz_mm'],'interface frame position');vector(c['frame']['rpy_rad'],'interface frame rotation')
    names=set()
    for check in c['checks']:
        if check['name'] in names:raise ValueError('interface check names must be unique')
        names.add(check['name'])
        if check['type']=='extent':
            number(check['expected_mm'],'expected extent',True);number(check['tolerance_mm'],'extent tolerance')
        else:
            selector(check['selector']);axis=np.asarray(vector(check['expected_axis'],'reference cylinder axis'))
            if not np.isclose(np.linalg.norm(axis),1,atol=1e-7,rtol=0):raise ValueError('reference cylinder axis must be unit length')
            vector(check['expected_point_mm'],'reference axis point')
            if ('expected_radius_mm' in check)!=('radius_tolerance_mm' in check):raise ValueError('radius check requires both reference radius and tolerance')
    return c


def measure_interface(path,out):
    from .geometry import session,inventory,select_faces
    from .sources import SourceGuard,source_paths
    from .product import STYLE
    path=Path(path).resolve();c=load_interface_case(path);out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    guard=SourceGuard(source_paths(c)|{path,Path(c['provenance']['reference_document']['path'])})
    record={'schema_version':'simplecae-interface-result-1.0','case':c,'checks':[],
            'reference_values_independently_extracted':False,'source_files_sha256':guard.hashes,
            'whole_product_rating_available':False,'scope':'Declared source-bound interface dimensions and analytic cylinder axes only; no automatic supplier authenticity, fit/clearance, tolerance stack or strength certification.'}
    try:
        with session(Path(c['model']['path']),c['model']) as g:
            interfaces=None
            if c['model'].get('interface_manifest'):
                from .bridge import resolve_interfaces
                interfaces=resolve_interfaces(c['model']['interface_manifest'],inventory(g,Path(c['model']['path'])))
            if c.get('frame'):
                # Generic affineTransform converts analytic cylinders to splines
                # in OCC, even for a rigid matrix. Preserve actual analytic types.
                frame=c['frame'];entities=g.model.getEntities(3)
                for axis,angle in zip(np.eye(3),frame['rpy_rad']):
                    if angle:g.model.occ.rotate(entities,0,0,0,*axis,float(angle))
                g.model.occ.translate(entities,*frame['xyz_mm']);g.model.occ.synchronize()
            info=inventory(g,Path(c['model']['path']))
            if interfaces is not None:info['interfaces']=interfaces
            guard.check_mesh(c,{'geometry':info});record['geometry']=info
            for check in c['checks']:
                if check['type']=='extent':
                    axis='xyz'.index(check['axis']);actual=info['bbox_mm'][1][axis]-info['bbox_mm'][0][axis];delta=actual-check['expected_mm']
                    row={'name':check['name'],'type':'extent','axis':check['axis'],'actual_mm':actual,'expected_mm':check['expected_mm'],'difference_mm':delta,
                         'tolerance_mm':check['tolerance_mm'],'matches':abs(delta)<=check['tolerance_mm']}
                else:
                    faces=select_faces(info,check['selector']);actuals=[cylinder_axis(g,face) for face in faces];values=[]
                    for actual in actuals:
                        axis=np.asarray(actual['direction']);expected=np.asarray(check['expected_axis']);angle=float(np.degrees(np.arccos(np.clip(abs(axis@expected),0,1))))
                        distance=float(np.linalg.norm(np.cross(np.asarray(actual['point_mm'])-check['expected_point_mm'],expected)))
                        radius_ok='expected_radius_mm' not in check or abs(actual['radius_mm']-check['expected_radius_mm'])<=check['radius_tolerance_mm']
                        values.append(dict(actual,axis_angle_deg=angle,axis_line_distance_mm=distance,
                                           radius_difference_mm=actual['radius_mm']-check['expected_radius_mm'] if 'expected_radius_mm' in check else None,
                                           matches=angle<=check['angle_tolerance_deg'] and distance<=check['axis_distance_tolerance_mm'] and radius_ok))
                    row={'name':check['name'],'type':'cylinder_axis','actuals':values,'reference':check,'matches':all(v['matches'] for v in values)}
                record['checks'].append(row)
        guard.check();record['status']='matches_declared_reference' if all(r['matches'] for r in record['checks']) else 'mismatch'
    except Exception as exc:record['status']='invalid';record['error']=f'{type(exc).__name__}: {exc}'
    write_json(out/'interface-result.json',record)
    rows=''
    for row in record['checks']:
        if row['type']=='extent':detail=f"实际 {row['actual_mm']:.6g} mm；参考 {row['expected_mm']:.6g} mm；差值 {row['difference_mm']:.6g} mm；容许差 {row['tolerance_mm']:.6g} mm"
        else:detail='；'.join(f"面 {v['face_id']}：轴线差 {v['axis_line_distance_mm']:.6g} mm，方向差 {v['axis_angle_deg']:.6g}°，半径 {v['radius_mm']:.6g} mm" for v in row['actuals'])
        rows+='<tr><td>'+html.escape(row['name'])+'</td><td>'+('匹配声明参考' if row['matches'] else '存在差异')+'</td><td>'+html.escape(detail)+'</td></tr>'
    labels={'matches_declared_reference':'已检查尺寸匹配声明参考','mismatch':'存在接口差异','invalid':'检查无效，需修正输入或几何'}
    body='<h1>采购件与设计接口核对</h1><p><b>'+labels[record['status']]+'</b>。几何来源分类：'+html.escape(c['provenance']['classification'])+'；型号 '+html.escape(c['provenance']['part_number'])+'。来源分类和参考数值是声明内容，尚未自动核实厂家真实性或从文档自动提取。</p><p>长度单位 mm。显式 frame 为模型到检查坐标的刚性变换；没有缩放，也没有修改源CAD。匹配只覆盖下列检查，不能证明完整装配公差、碰撞、采购真伪或强度。</p><table><tr><th>检查</th><th>结果</th><th>实际与参考</th></tr>'+rows+'</table>'
    if record.get('error'):body+='<p>'+html.escape(record['error'])+'</p>'
    body+='<details><summary>完整来源与几何记录</summary><pre>'+html.escape(json.dumps(record,ensure_ascii=False,indent=2))+'</pre></details>'
    (out/'interface.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>SimpleCAE interface check</title><style>'+STYLE+'table{width:100%;border-collapse:collapse}td,th{border:1px solid #cbd5df;padding:10px}</style>'+body+'</html>',encoding='utf-8')
    return {'status':record['status'],'interface':str(out/'interface.html'),'data':str(out/'interface-result.json'),'meaning':record['scope']}
