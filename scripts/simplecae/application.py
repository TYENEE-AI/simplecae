"""One application-level view without upgrading partial models to product ratings."""
from pathlib import Path
import html,json
from .case import write_json
from .signals import design_signal
from .product import STYLE,omission_label

def summarize_application(paths,out,title='SimpleCAE 方案评估',*,ledger=None):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False);analyses=[];omissions=set()
    labels={'invalid':'计算无效','indeterminate':'证据不足','fail_under_stated_model':'声明模型下不满足','pass_under_stated_model':'声明模型下满足'}
    rows=''
    for path in paths:
        path=Path(path).resolve();result=json.loads(path.read_text(encoding='utf-8-sig'));signal=design_signal(result)
        missing=signal.get('conditional_limit',{}).get('withheld_reasons',[]) if signal.get('conditional_limit') else []
        entry={'name':path.parent.name,'result':str(path),'analysis_status':result['status'],'comparison_usable':signal['valid_for_comparison'],
               'model_feasible':signal['feasible_under_stated_model'],'physical_conditions_verified':signal['physical_conditions_verified'],
               'coverage':signal['coverage'],'metrics':signal['metrics'],'utilizations':signal['utilizations'],
               'evidence_gaps':missing,'not_assessed':signal['not_assessed']}
        analyses.append(entry);omissions.update(entry['not_assessed'])
        coverage=entry['coverage'];coverage_text='已做零件FEM：'+', '.join(coverage.get('component_fem_links',[]))+'；未做FEM：'+', '.join(coverage.get('links_without_fem',[])) if result['analysis']=='urdf_static' else '仅覆盖当前声明本体与判据'
        metric_labels={'max_displacement_mm':'最大位移 mm','max_von_mises_mpa':'最大等效应力 MPa','max_actuator_utilization':'最大执行器利用率'}
        metrics='；'.join(metric_labels[k]+' = '+(f'{v:.6g}' if isinstance(v,(int,float)) else str(v)) for k,v in entry['metrics'].items() if k in metric_labels)
        import os
        try:report_url=Path(os.path.relpath(path.parent/'report.html',out)).as_posix()
        except ValueError:report_url=(path.parent/'report.html').as_uri()
        rows+='<tr><td>'+html.escape(entry['name'])+'</td><td>'+labels[result['status']]+'</td><td>'+html.escape(metrics)+'</td><td>'+html.escape(coverage_text)+'</td><td>'+('已核实' if entry['physical_conditions_verified'] else '仍有未核实物理条件')+'</td><td><a href="'+html.escape(report_url,quote=True)+'">完整分析</a></td></tr>'
    record={'title':title,'analyses':analyses,'whole_product_rating_available':False,
            'not_assessed':sorted(omissions),'meaning':'Application evidence overview; individual model passes do not prove a product or unmodeled component safe.'}
    ledger_section=''
    if ledger:
        from .evidence import review_ledger,ledger_html
        reviewed=review_ledger(ledger,out/'evidence')
        record['product_evidence']=json.loads(Path(reviewed['data']).read_text(encoding='utf-8'))
        ledger_section=ledger_html(record['product_evidence'],out)
    write_json(out/'application.json',record)
    page='<html lang="zh-CN"><meta charset="utf-8"><title>'+html.escape(title)+'</title><style>'+STYLE+'table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd6e2;padding:10px}</style><h1>'+html.escape(title)+'</h1><p>下面分别列出模型结果、已覆盖零件和未核实条件。通过某个零件的强度检查，不代表整个产品已验证或已取得额定承载。</p><table><tr><th>分析</th><th>模型结果</th><th>主要数值</th><th>覆盖</th><th>物理条件</th><th>证据</th></tr>'+rows+'</table><h2>仍需处理的未评估项</h2><ul>'+''.join('<li>'+html.escape(omission_label(v))+'</li>' for v in sorted(omissions))+'</ul><p>请将这些缺项落实为器件选型、加工/装配要求或实物测试；本页不会将缺项隐藏为整机通过。</p></html>'
    page=page.replace('</html>',ledger_section+'</html>')
    (out/'application.html').write_text(page,encoding='utf-8');return {'application':str(out/'application.html'),'meaning':record['meaning']}
