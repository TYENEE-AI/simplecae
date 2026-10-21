"""Readable declared load path, shared by preflight and result reports."""
import html


def path_table(assessment):
    rows=''
    for pair in assessment['pairs']:
        a,b=pair['ports'];effort=f"{pair['holding_effort']:.6g}"+(' N' if pair['type']=='prismatic' else ' N·m')
        route=html.escape(a['link'])+' ← '+html.escape(pair['name'])+' → '+html.escape(b['link'])
        def vec(v):return '['+', '.join(f'{x:.6g}' for x in v)+']'
        points=vec(a['position_m'])+' / '+vec(b['position_m'])+' m'
        check='有外部核对声明' if pair['verified'] else '尚未核对'
        rows+='<tr><td>'+route+'</td><td>'+effort+'</td><td>'+points+'</td><td>'+check+'</td></tr>'
    gaps=', '.join(assessment['unrouted_actuators']) or '无'
    return '<h3>驱动与反力路径</h3><p>等大反向力或力矩按声明端口传递；原始保持力仍用于执行器额定值检查。未声明路径：'+html.escape(gaps)+'。路径闭合不等于传动或后支座强度已验证。</p><table><tr><th>作用端 ← 驱动 → 反力端</th><th>保持力/矩</th><th>世界坐标端点</th><th>安装核对</th></tr>'+rows+'</table>'
