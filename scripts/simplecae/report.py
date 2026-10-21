"""Portable HTML report and PNG of actual computed fields."""
from __future__ import annotations
import html
import json
from pathlib import Path
import numpy as np


def plot_fields(mesh, fields, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    data = np.load(path.parent / "mesh.npz")
    coords, tets, fixed, _, meta = mesh
    owners = {}
    for e, ns in tets.items():
        for face in ((0,1,2),(0,1,3),(0,2,3),(1,2,3)):
            owners[tuple(sorted(ns[i] for i in face))] = e
    stress = {}
    context=fields.get('_strength_context')
    directional=context and (len(context['materials'])>1 or any(m.get('failure_criterion')=='max_stress' for m in context['materials'].values()))
    if directional:
        from .materials import strength_values
        values,_=strength_values(list(fields['stresses'].values()),list(fields['stresses']),context)
        if values is not None:
            for (e,_),value in zip(fields['stresses'],values):stress[e]=max(stress.get(e,0.),float(value))
        else:directional=False
    for (e, _), s in fields["stresses"].items():
        vm = float(np.sqrt(.5*((s[0]-s[1])**2+(s[1]-s[2])**2+(s[2]-s[0])**2)+3*np.sum(s[3:]**2)))
        if not directional:stress[e] = max(stress.get(e, 0.), vm)
    facets, values, displaced, faces = [], [], [], []
    span = float(np.max(np.ptp(np.array(list(coords.values())), axis=0)))
    umax = max(np.linalg.norm(u) for u in fields["displacements"].values())
    scale = max(1., .08*span/max(umax, 1e-30))
    for tri, fid in zip(data["surface_tri6"], data["surface_face_ids"]):
        owner = owners[tuple(sorted(map(int, tri[:3])))]
        for ids in ((0,3,5),(3,1,4),(5,4,2),(3,4,5)):
            ns = [int(tri[i]) for i in ids]
            facets.append([coords[n] for n in ns])
            displaced.append([coords[n]+scale*fields["displacements"][n] for n in ns])
            values.append(stress[owner])
            faces.append(int(fid))
    fig = plt.figure(figsize=(15, 5), layout="constrained")
    fixed_faces = {f for fs in meta["support_faces"].values() for f in fs}
    load_faces = {f for l in meta["loads"] for f in l["face_ids"]}
    colors = ["#2677b8" if f in fixed_faces else "#dd7824" if f in load_faces else "#c6ced8" for f in faces]
    norm = Normalize(0, max(max(values),1 if directional else 0.))
    for i, (verts, facecolor, title) in enumerate([
        (facets, colors, "Boundary conditions\nBlue: prescribed support / orange: traction"),
        (facets, plt.colormaps["viridis"](norm(values)), "Material strength utilization\n1.0 = declared allowable; element peak" if directional else "von Mises stress (MPa)\nAdjacent element peak integration-point values"),
        (displaced, "#679eb0", f"Computed displacement\nDisplay scale x{scale:.1f}"),
    ]):
        ax = fig.add_subplot(1, 3, i+1, projection="3d",computed_zorder=False)
        ax.add_collection3d(Poly3DCollection(verts, facecolors=facecolor, linewidths=0))
        points = np.array(verts).reshape((-1, 3))
        lo, hi = points.min(axis=0), points.max(axis=0)
        for setter, a, b in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), lo, hi):
            setter(a, b)
        ax.set_box_aspect(np.maximum(hi-lo, 1e-5))
        ax.set(xlabel="X (mm)", ylabel="Y (mm)", zlabel="Z (mm)", title=title)
        ax.view_init(25, -125 if i==0 else -55)
        ax.set_axis_off()
        if i == 0:
            for load in meta["loads"]:
                direction = np.array(load["total_force_n"], dtype=float)
                if np.linalg.norm(direction)==0:
                    continue
                direction /= np.linalg.norm(direction)
                origin=np.array(load['centroid_mm'])-direction*.15*span
                ax.quiver(*origin, *direction, length=.15*span, color="#aa3e16", linewidth=2, arrow_length_ratio=.3,zorder=10)
        if i == 1:
            fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap="viridis"), ax=ax, shrink=.55)
    fig.savefig(path, dpi=140)
    plt.close(fig)


def probe_limit_label(value):
    return '只读数／未设置判据' if value is None else f'{value:.6g}'


def render_report(result, out: Path):
    def esc(v):
        return html.escape(str(v))
    a = result.get("assessment")
    if a:
        limit = a["conditional_body_limit"]
        statuses = {"invalid":"计算无效", "indeterminate":"尚不能判断", "fail_under_stated_model":"在给定模型条件下不满足要求", "pass_under_stated_model":"在给定模型条件下满足要求"}
        labels = {"material_verified":"材料参数和失效判据已核实", "dimensions_verified":"模型尺寸已核实",
                  "supports_represent_actual_mounting":"固定方式能代表实际安装", "load_pattern_verified":"载荷位置、方向和分布已核实", "self_weight_negligible":"本次评估可忽略零件自重",'connection_parameters_verified':'连接模型与柔度参数已核实'}
        summary = f"<p>声明的结构模型与判据：<b>{esc(statuses[a['status']])}</b>。整体安装与产品验收：<b>未评估</b>。</p>"
        materials=[result['case'].get('material',{})]+[b.get('material',{}) for b in result['case'].get('bodies',[])]
        if any(m.get('calibration',{}).get('kind')=='mathematical_reference' for m in materials):
            summary='<p><b>数值标准算例：</b>材料与成立条件是数学定义，用于核对计算方法；确认项不代表实物材料、安装或产品已验证。</p>'+summary
        if result.get('analysis') in ('frictionless_contact_assembly','staged_contact_assembly'):
            stage_text='本工况分两个阶段：先施加固定载荷，再保持固定载荷并施加使用载荷；两个阶段分别检查。' if result.get('preload_assessment') else '本工况没有固定预加载，只有一个使用载荷阶段。'
            if result['case'].get('bolts'):stage_text='本工况分三阶段：力控预紧 → 锁定调整量并移除广义预紧外力 → 保持锁定并施加使用载荷。三个阶段分别检查；外载变化后螺栓轴力可以改变。'
            scope='显式等效轴向螺栓只检查轴向拉力及锁定状态，许用拉力须包含用户选择的安全裕量。' if result['case'].get('bolts') else '这里的压紧力是外加力，不代表锁定螺栓预紧。'
            summary+='<p><b>平面接触／实际载荷求解</b>：只承压、可张开，采用显式法向罚刚度；明确指定摩擦参数时使用库仑定律。'+stage_text+scope+'接触变化时不输出线性承重倍率。</p>'
            if result.get('preload_assessment'):
                pre=result['preload_assessment'];values=[]
                for label,key in [('强度','strength_utilization'),('变形','stiffness_utilization')]:
                    if pre.get(key) is not None:values.append(label+f" {100*pre[key]:.1f}%")
                summary+='<p>预加载阶段：<b>'+esc(statuses[pre['status']])+'</b>；'+esc('，'.join(values))+' 的输入允许值。最终使用阶段通过不能覆盖预加载阶段的失败。</p>'
            contacts=result['levels'][-1]['results'].get('contact',[])
            rows=''.join('<tr><td>'+esc(p['name'])+'</td><td>'+esc(p.get('minimum_gap_mm','无完整输出'))+'</td><td>'+esc(p.get('peak_pressure_mpa','无完整输出'))+'</td><td>'+esc(p.get('peak_shear_mpa','未建模'))+'</td><td>'+esc(p.get('peak_tangential_displacement_mm','未建模'))+'</td></tr>' for p in contacts)
            summary+='<table><tr><th>接触面</th><th>最小间隙 mm（负值为罚穿透）</th><th>峰值压强 MPa</th><th>峰值剪应力 MPa</th><th>材料点相对切向位移 mm</th></tr>'+rows+'</table><p>相对切向位移包含弹性柔度，按任务输入的允许值判定，不是累计不可逆滑移。接近库仑上限的样本数不是滑动面积比例。压强读数不等于接触许用强度已验证。</p>'
            if result['case'].get('bolts'):
                rows=''
                for label,key in [('预紧','fixed-results.json'),('锁定','locked-results.json'),('使用',None)]:
                    data=json.loads((Path(result['levels'][-1]['directory'])/key).read_text(encoding='utf-8'))['results'] if key else result['levels'][-1]['results']
                    for b in data.get('bolts',[]):rows+='<tr><td>'+label+'</td><td>'+esc(b['name'])+'</td><td>'+esc(b['force_n'])+'</td><td>'+esc(b['adjustment_mm'])+'</td><td>'+esc(b['utilization'])+'</td></tr>'
                summary+='<table><tr><th>阶段</th><th>等效螺栓</th><th>轴力 N</th><th>调整量 mm（锁定后不变）</th><th>轴向拉力利用率</th></tr>'+rows+'</table><p>不包含螺纹、局部承压、螺栓剪切／弯曲、扭矩到预紧换算及预紧散差；仍不能据此给整个产品额定承重。</p>'
                locked=result['stage_assessments']['locked']
                summary+='<p>锁定阶段：<b>'+esc(statuses[locked['status']])+'</b>。最终使用阶段通过不能覆盖预紧或锁定阶段的失败。</p>'
            motions=[s for s in result['case']['supports'] if any(s.get('service_displacement_mm',[0,0,0]))]
            if motions:summary+='<p>使用阶段规定夹具位移（世界坐标，预紧／锁定时为零）：'+esc('; '.join(s['name']+': '+str(s['service_displacement_mm'])+' mm' for s in motions))+'。</p>'
            if result.get('stage_assessments',{}).get('service'):
                summary+='<p>使用阶段单独结论：<b>'+esc(statuses[result['stage_assessments']['service']['status']])+'</b>；页面顶部为所有阶段的较差结论。判定仅覆盖各阶段终点，不包含加载过程中的中间峰值。</p>'
        if limit["available"]:
            summary += f"<p>在已列出的条件下，仅可缩放载荷同时乘以 <b>{limit['load_pattern_scale_factor']:.4g}</b>，固定载荷和已建模自重保持不变，此时先达到本体"
            summary += {"strength":"强度", "stiffness":"变形", "elastic_buckling_screening":"理想弹性屈曲筛查"}.get(limit["governing_limit"],limit["governing_limit"]) + "限制。"
            if limit["vertical_payload_mass_equivalent_kg"] is not None:
                summary += f"对应竖直载荷质量等效为 <b>{limit['vertical_payload_mass_equivalent_kg']:.4g} kg</b>。"
            summary += "此数值只对应已评估的本体判据，不是整个装置的额定承重或极限破坏载荷。</p>"
        else:
            summary += "<p><b>本次未提供承重预测。</b> 下方列出了尚未满足的验证或使用条件。</p>"
        from .materials import primary_material
        material = primary_material(result['case'])
        registry=result['levels'][-1]['mesh'].get('materials')
        if registry:
            rows=''.join(f"<tr><td>{esc(name)}</td><td>{esc(m['name'])}</td><td>{esc(m.get('elastic_model','isotropic'))}</td><td>{esc(m.get('failure_criterion','not_specified'))}</td><td>{esc(m['source'])}</td></tr>" for name,m in registry.items())
            summary+='<p>这是明确连接的多实体结构，各实体使用自己的材料参数；下方本体限制不包含连接失效。</p><table><tr><th>材料编号</th><th>材料</th><th>弹性模型</th><th>强度判据</th><th>来源</th></tr>'+rows+'</table>'
        if a.get("buckling"):
            b=a["buckling"]
            summary += f"<p>弹性屈曲载荷系数：<b>{esc(b['lowest_positive_load_factor'])}</b>；网格收敛：{'通过' if b['mesh_converged'] else '未通过'}。这是理想模型的失稳筛查，尚未考虑初始缺陷、非线性塌陷和接触变化。</p>"
        if material.get('elastic_model','isotropic')=='orthotropic':
            summary += f"<p>材料模型：{esc(material['name'])}；方向性弹性常数与材料轴已明确输入。强度使用材料轴上的拉伸、压缩、剪切独立允许值；图中的 von Mises 数值仅作应力描述。参数来源：{esc(material['source'])}</p>"
        elif not registry:
            summary += f"<p>材料模型：{esc(material['name'])}；弹性模量 {material['youngs_modulus_mpa']:.6g} MPa；泊松比 {material['poisson_ratio']:.4g}。参数来源：{esc(material['source'])}</p>"
        ratios=[]
        for title,key in [('强度','strength_utilization'),('变形','stiffness_utilization')]:
            value=a.get(key);ratios.append(title+'：'+(f'{100*value:.1f}% 的输入允许值' if value is not None else '缺少评价依据'))
        summary+='<p>'+('最终使用阶段：' if result.get('preload_assessment') else '')+'<b>'+esc('；'.join(ratios))+'</b>。超过 100% 表示超出要求；实际适用性取决于下方成立条件。</p>'
        region_rows=[]
        for stage,stage_assessment in result.get('stage_assessments',{'service':a}).items():
            comparisons=stage_assessment.get('verification',{}).get('stress_region_mesh_comparisons',[])
            for region in stage_assessment.get('stress_regions',[]):
                name=region['name']
                ok=len(comparisons)>=2 and all(p.get(name,{}).get('converged') is True for p in comparisons[-2:])
                region_rows.append('<tr><td>'+esc(stage+'/'+name)+'</td><td>'+esc(f"{region['max_von_mises_mpa']:.6g}")+'</td><td>'+esc(str(region['peak']['element_centroid_mm']))+'</td><td>'+('已收敛' if ok else '证据不足')+'</td></tr>')
        if region_rows:
            summary+='<h2>局部应力区域</h2><p>保留所有选中单元的原始积分点峰值，不代替整体检查。坐标为单元中心，非精确高斯点位置；预紧、锁定和工作阶段分别检查。</p><table><tr><th>阶段 / 区域</th><th>峰值 MPa</th><th>位置 mm</th><th>两次相邻网格比较</th></tr>'+''.join(region_rows)+'</table>'
        if a.get('criterion_assessments'):
            criterion_rows=''.join('<tr><td>'+esc(name)+'</td><td>'+esc(statuses[e['status']])+'</td><td>'+('已收敛' if e['mesh_converged'] else '未收敛')+'</td></tr>' for name,e in a['criterion_assessments'].items())
            summary+='<h2>各判据的证据状态</h2><p>已收敛的失败不会被其他未收敛项隐藏；总体证据不足时仍不能排名或预测承重。</p><table><tr><th>判据</th><th>模型结论</th><th>相关网格证据</th></tr>'+criterion_rows+'</table>'
        if result['levels'][-1]['results'].get('probes'):
            probe_rows=''.join('<tr><td>'+esc(p['name'])+'</td><td>'+esc(p.get('point_mm') or [p.get('from_point_mm'),p.get('to_point_mm')])+'</td><td>'+f"{p['value_mm']:.6g}"+'</td><td>'+esc(p.get('signed_projection_mm','向量长度'))+'</td><td>'+esc(probe_limit_label(p['allowable_displacement_mm']))+'</td></tr>' for p in result['levels'][-1]['results']['probes'])
            summary+='<h2>功能测点与相对变形</h2><p>使用实际C3D10二次位移场插值，没有吸附到最近节点。相对值只包含本次建模的弹性变形，不包含未建模软垫、接头或安装柔度；方向投影以绝对值判定，保留带符号读数。</p><table><tr><th>名称</th><th>位置 / 起止点 mm</th><th>判定量 mm</th><th>带符号方向值 mm</th><th>允许值 mm</th></tr>'+probe_rows+'</table>'
        load_rows = "".join(f"<tr><td>{esc(load['name'])}</td><td>{'可缩放' if load.get('scalable',True) else '固定不变'}</td><td>{esc(load['total_force_n'])}</td><td>{esc(load.get('total_moment_n_mm_about_patch_centroid',[0,0,0]))}</td><td>{load['area_mm2']:.6g}</td><td>{esc(load['face_ids'])}</td></tr>" for load in result["levels"][-1]["mesh"]["loads"])
        summary += "<table><tr><th>载荷区域</th><th>缩放方式</th><th>总力 [X,Y,Z] N</th><th>关于区域质心的总力矩 N·mm</th><th>面积 mm²</th><th>完整面编号</th></tr>" + load_rows + "</table>"
        if result['case'].get('gravity'):
            summary += f"<p>自重：固定不变；重力加速度 {esc(result['case']['gravity']['acceleration_m_s2'])} m/s²。</p>"
        if limit["withheld_reasons"]:
            explanations = []
            for s in limit["withheld_reasons"]:
                if s.startswith("condition not verified:"):
                    explanations.append("尚未核实：" + labels.get(s.split(": ",1)[1], s))
                elif "mesh comparisons" in s:
                    explanations.append("连续两次网格细化比较尚未同时满足位移和峰值应力的收敛要求；应力峰值可能受奇异性影响。")
                elif "equilibrium" in s:
                    explanations.append("力或力矩平衡检查未通过。")
                elif "predicted limiting load" in s or "small-displacement" in s:
                    explanations.append("参考载荷或预测限制载荷超过小变形/小应变筛查范围，需要进一步分析。")
                elif "failure criterion" in s:
                    explanations.append("需补齐适用的强度判据、允许值与明确的强度安全系数。")
                elif 'calibration' in s:
                    explanations.append("需记录方向性强度数据的校准来源及其适用制造、使用条件。")
                elif "allowable displacement" in s:
                    explanations.append("需指定可接受的最大变形。")
                else:
                    explanations.append(s)
            summary += "<ul>" + "".join(f"<li>{esc(s)}</li>" for s in explanations) + "</ul>"
        rows = "".join(f"<tr><td>{l['mesh_size_mm']}</td><td>{l['mesh']['element_count']}</td><td>{l['results']['max_displacement_mm']:.6g}</td><td>{l['results']['max_von_mises_mpa']:.6g}</td><td>{l['results']['force_balance_relative_error']:.3g}</td></tr>" for l in result["levels"])
        summary += "<table><tr><th>网格 mm</th><th>单元</th><th>位移 mm</th><th>峰值应力 MPa</th><th>力平衡相对误差</th></tr>" + rows + "</table>"
        png = result.get("preview_relative_path")
        if result["levels"]:
            try:
                from .viewer import embed_viewer
                viewer='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>SimpleCAE field viewer</title><style>body{font:16px system-ui;margin:12px}.viewer-controls{display:flex;gap:14px;flex-wrap:wrap}</style>'+embed_viewer(Path(result["levels"][-1]["directory"]))+'</html>'
                (out/'fields-viewer.html').write_text(viewer,encoding='utf-8')
                summary += '<iframe title="Computed stress and displacement fields" src="fields-viewer.html" loading="lazy" style="width:100%;height:720px;border:0"></iframe><a href="fields-viewer.html">单独打开场结果交互视图</a>'
            except Exception as exc:
                summary += f"<p>交互预览未生成：{esc(exc)}。静态计算与下方图片仍可查看。</p>"
        if result['case'].get('reference_only'):
            summary += '<p>本工况仅使用6个数值参考方程去除刚体运动。全局位移和动画位置依赖参考系；功能判定使用两点/表面间的一阶长度变化。参考反力不是实际安装或执行器反力。</p>'
        if png:
            summary += f'<img src="{esc(png)}" alt="Computed boundary, stress and displacement fields">'
        summary += "<h2>成立条件</h2><ul>" + "".join(f"<li>{esc(labels[k])}：{'自重已单独建模并保持不变' if k=='self_weight_negligible' and result['case'].get('gravity') else ('已确认' if v else '未确认')}</li>" for k, v in a["conditions"].items()) + "</ul>"
        omissions = ["整体和局部屈曲稳定性", "螺钉、锚固、墙体、焊缝、胶接及安装破坏", "接触、分离、滑移、预紧力和连接柔度", "塑性重分布、断裂和极限破坏", "疲劳、冲击、振动和动态放大", "长期蠕变、使用时长和温度影响", "打印方向、填充、层间粘结、各向异性及制造缺陷", "自重、残余应力和其他不随载荷同比例变化的作用"]
        mapping={'Buckling and stability (including local plate buckling)':omissions[0],
                 'Bolts, anchors, wall/substrate, welds, adhesive and mounting failure':omissions[1],
                 'Contact, separation, slip, bolt preload and unspecified joint compliance':'接触、分离、滑移、预紧及未明确建模的连接柔度',
                 'Plastic redistribution, fracture and ultimate collapse':omissions[3],
                 'Fatigue, impact, vibration and dynamic amplification':omissions[4],
                 'Creep, sustained-load duration and temperature effects':omissions[5],
                 'Unresolved infill details, layer damage, delamination and manufacturing defects':'未解析的填充细节、层间损伤、分层及制造缺陷',
                 'Directional material properties unless explicitly calibrated':'未明确校准的材料方向性',
                 'Material/manufacturing variability outside the declared calibration':'超出校准适用范围的材料与制造波动',
                 'Self-weight when not explicitly modeled':'未明确建模的自重',
                 'Residual stress and other unspecified non-scaling loads':'残余应力及其他未明确建模的固定作用'}
        mapping["Nonlinear buckling collapse and calibrated imperfection sensitivity"]="非线性屈曲塌陷与经校准的初始缺陷敏感性"
        summary += "<h2>未评估项</h2><ul>" + "".join(f"<li>{esc(mapping.get(s,s))}</li>" for s in a["not_assessed"]) + "</ul>"
    else:
        summary = "<p>计算无效：" + esc(result.get("error")) + "。不提供承载结论。</p>"
    document = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>SimpleCAE analysis</title>'
                '<style>body{font:16px system-ui;max-width:1200px;margin:36px auto;padding:20px;color:#243447}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd6df;padding:10px}img{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:16px}</style>'
                '<h1>SimpleCAE 静力分析</h1>' + summary + '<details><summary>完整结果、计算文件与来源</summary><pre>'
                + esc(json.dumps(result.get('evaluation_signal',{}), ensure_ascii=False, indent=2, allow_nan=False)) + '</pre><a href="result.json">完整 result.json 与原始网格、场结果</a></details></html>')
    (out / "report.html").write_text(document, encoding="utf-8")
