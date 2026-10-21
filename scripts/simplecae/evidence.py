"""Product evidence ledger, with file binding and no certification inference."""
from pathlib import Path
import datetime,html,json,re
from .case import keys,sha256,write_json

STATES=('unassessed','calculated','physical_pending','physical_recorded')
KINDS=('simulation','analytic_calculation','supplier_document','software_build','software_test','physical_test','physical_inspection')
DOMAINS=('material','procurement','interfaces','assembly','structure','contact','actuation','force_calibration','control','fault_response','lifetime','physical_acceptance')
TITLES=('材料与制造参数','采购型号与来源','实际接口与尺寸','装配和安装','结构强度与刚度','摩擦与接触','传动和驱动反力','传感器标定与真实夹力','控制行为','故障响应','耐久寿命','实物任务验收')
HASH=re.compile(r'^[0-9a-fA-F]{64}$')


def file_ref(ref,parent,label):
    keys(ref,['path','sha256'],['path','sha256'],label)
    if not isinstance(ref['path'],str) or not ref['path'] or not isinstance(ref['sha256'],str) or not HASH.fullmatch(ref['sha256']):
        raise ValueError(label+' needs a path and SHA256')
    p=(parent/ref['path']).resolve()
    current=sha256(p) if p.is_file() else None
    return {'path':str(p),'declared_sha256':ref['sha256'].lower(),'current_sha256':current,
            'status':'missing' if current is None else 'current' if current==ref['sha256'].lower() else 'stale'}


def inspect_ledger(path):
    path=Path(path).resolve();c=json.loads(path.read_text(encoding='utf-8-sig'))
    from .schemas import check_contract
    check_contract(c,'evidence')
    keys(c,['schema_version','title','bindings','items','notes'],['schema_version','title','bindings','items'],'evidence ledger')
    if c['schema_version']!='simplecae-evidence-1.0':raise ValueError('unsupported evidence ledger version')
    if not isinstance(c['title'],str) or not c['title'].strip():raise ValueError('ledger needs a title')
    if not isinstance(c['bindings'],dict) or not c['bindings']:raise ValueError('ledger requires source bindings')
    bindings={n:file_ref(ref,path.parent,'source binding') for n,ref in c['bindings'].items()}
    if any(not isinstance(n,str) or not n for n in bindings):raise ValueError('binding IDs must be nonempty')
    if not isinstance(c['items'],list) or not c['items']:raise ValueError('ledger requires explicit coverage items')
    items=[];seen=set()
    for item in c['items']:
        keys(item,['id','domain','title','state','statement','evidence'],['id','domain','title','state','statement','evidence'],'evidence item')
        for field in ('id','title','statement'):
            if not isinstance(item[field],str) or not item[field].strip():raise ValueError('evidence item text must be nonempty')
        if item['id'] in seen:raise ValueError('evidence item IDs must be unique')
        seen.add(item['id'])
        if item['domain'] not in DOMAINS or item['state'] not in STATES:raise ValueError('unknown evidence domain/state')
        if not isinstance(item['evidence'],list):raise ValueError('evidence references must be a list')
        evidence=[];gaps=[]
        for record in item['evidence']:
            keys(record,['file','kind','applies_to','source_sha256','outcome','date','operator','test_method','scope'],['file','kind','applies_to','source_sha256','scope'],'evidence record')
            if record['kind'] not in KINDS:raise ValueError('unknown evidence kind')
            if not isinstance(record['scope'],str) or not record['scope'].strip():raise ValueError('evidence must state its scope')
            if not isinstance(record['applies_to'],list) or not record['applies_to'] or set(record['applies_to'])-set(bindings):
                raise ValueError('evidence must reference known source bindings')
            snapshots=record['source_sha256']
            if not isinstance(snapshots,dict) or set(snapshots)!=set(record['applies_to']) or any(not isinstance(h,str) or not HASH.fullmatch(h) for h in snapshots.values()):
                raise ValueError('evidence requires a SHA256 snapshot for every applicable source')
            if record['kind'] in ('physical_test','physical_inspection'):
                for field in ('operator','test_method'):
                    if not isinstance(record.get(field),str) or not record[field].strip():raise ValueError('physical evidence requires operator and test_method')
                if record.get('outcome') not in ('pass','fail','inconclusive'):raise ValueError('physical evidence outcome must be explicit')
                try:datetime.date.fromisoformat(record['date'])
                except (KeyError,TypeError,ValueError):raise ValueError('physical evidence requires an ISO test date')
            info=file_ref(record['file'],path.parent,'evidence file')
            source_gaps=[n for n in record['applies_to'] if bindings[n]['status']!='current' or snapshots[n].lower()!=bindings[n]['declared_sha256']]
            usable=info['status']=='current' and not source_gaps
            if not usable:gaps.append({'file':info['path'],'file_status':info['status'],'changed_or_missing_sources':source_gaps})
            evidence.append(dict(record,file=info,usable_for_declared_sources=usable))
        state=item['state'];kinds={r['kind'] for r in evidence}
        if state=='calculated' and not kinds & {'simulation','analytic_calculation','software_build','software_test'}:
            raise ValueError('calculated item requires calculation or software evidence')
        if state=='physical_recorded' and not kinds & {'physical_test','physical_inspection'}:
            raise ValueError('physical_recorded cannot be granted by a build, simulation, supplier document or software test')
        effective='evidence_missing_or_stale' if state in ('calculated','physical_recorded') and gaps else state
        outcomes=[r['outcome'] for r in evidence if r['kind'] in ('physical_test','physical_inspection') and r['usable_for_declared_sources']]
        items.append(dict(item,evidence=evidence,declared_state=state,effective_state=effective,
                          physical_outcomes=outcomes,evidence_gaps=gaps,
                          physical_measurement_independently_verified=False))
    missing_domains=sorted(set(DOMAINS)-{x['domain'] for x in items})
    for domain in missing_domains:
        items.append({'id':'unlisted:'+domain,'domain':domain,'title':TITLES[DOMAINS.index(domain)],
                      'declared_state':'unassessed','effective_state':'unassessed','state':'unassessed',
                      'statement':'清单未列出此项，自动保留为未评估。','evidence':[],'physical_outcomes':[],
                      'evidence_gaps':[],'physical_measurement_independently_verified':False})
    # File hashes protect version matching, not truthfulness or test adequacy.
    current_hash=sha256(path)
    return {'schema_version':'simplecae-evidence-review-1.0','title':c['title'],'source_ledger':str(path),'source_ledger_sha256':current_hash,
            'bindings':bindings,'items':items,'unlisted_domains':missing_domains,
            'whole_product_rating_available':False,'certification_available':False,
            'meaning':'File-bound external evidence inventory. Recorded physical results are user-supplied claims; file integrity does not verify measurement truth, protocol adequacy or product certification.'}


def ledger_html(record,out):
    import os
    labels={'unassessed':'未评估','calculated':'已有计算/软件检查','physical_pending':'待实测','physical_recorded':'已登记实测记录','evidence_missing_or_stale':'证据缺失或版本已变化'}
    rows=''
    for item in record['items']:
        refs=[]
        for ref in item['evidence']:
            label=html.escape(Path(ref['file']['path']).name)
            if ref.get('snapshot_path'):
                url=Path(os.path.relpath(ref['snapshot_path'],out)).as_posix();label='<a href="'+html.escape(url,quote=True)+'">'+label+'</a>'
            elif ref.get('snapshot_note'):label+='（'+html.escape(ref['snapshot_note'])+'）'
            refs.append(label+' '+html.escape(ref['kind'])+' / '+('版本匹配' if ref['usable_for_declared_sources'] else '不可沿用')+'：'+html.escape(ref['scope']))
        outcomes=' / 实测结果 '+', '.join(item['physical_outcomes']) if item['physical_outcomes'] else ''
        rows+='<tr><td>'+html.escape(item['title'])+'</td><td>'+labels[item['effective_state']]+html.escape(outcomes)+'</td><td>'+html.escape(item['statement'])+'</td><td>'+'<br>'.join(refs)+'</td></tr>'
    return '<h2>产品证据清单</h2><p>计算通过、软件测试和实测记录分别显示。实测记录可含失败或不确定结果；登记文件与版本匹配不代表本工具独立核实了测量，也不会产生产品认证或整机额定值。</p><table><tr><th>项目</th><th>证据状态</th><th>范围与下一步</th><th>来源</th></tr>'+rows+'</table>'


def review_ledger(path,out):
    from .product import STYLE
    from .sources import SourceGuard
    record=inspect_ledger(path)
    files={Path(path).resolve()}|{Path(b['path']) for b in record['bindings'].values() if b['current_sha256']}
    files|={Path(r['file']['path']) for i in record['items'] for r in i['evidence'] if r['file']['current_sha256']}
    guard=SourceGuard(files)
    declared={str(Path(path).resolve()):record['source_ledger_sha256']}|{b['path']:b['current_sha256'] for b in record['bindings'].values() if b['current_sha256']}
    declared.update({r['file']['path']:r['file']['current_sha256'] for i in record['items'] for r in i['evidence'] if r['file']['current_sha256']})
    if any(guard.hashes[p]!=h for p,h in declared.items()):raise RuntimeError('evidence files changed during review')
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    import shutil,re
    snapshots=out/'evidence-files';snapshots.mkdir()
    for item in record['items']:
        for ref in item['evidence']:
            source=Path(ref['file']['path'])
            if ref['file']['current_sha256'] is None:ref['snapshot_note']='源文件缺失';continue
            if source.stat().st_size>10*1024*1024:ref['snapshot_note']='文件超过10MiB，原始路径记录于JSON';continue
            target=snapshots/(ref['file']['current_sha256'][:16]+'-'+re.sub(r'[^\w.\-]','_',source.name))
            if not target.exists():shutil.copyfile(source,target)
            if sha256(target)!=ref['file']['current_sha256']:raise RuntimeError('evidence snapshot differs from inspected file')
            ref['snapshot_path']=str(target)
    record['evidence_snapshot_scope']='Only individually referenced files <=10MiB copied with hash checks. Source bindings remain original/tested revisions; snapshots do not upgrade stale or physical claims.'
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+html.escape(record['title'])+'</title><style>'+STYLE+'</style><h1>'+html.escape(record['title'])+'</h1>'+ledger_html(record,out)+'</html>'
    guard.check();write_json(out/'evidence-review.json',record);(out/'evidence.html').write_text(page,encoding='utf-8')
    return {'evidence':str(out/'evidence.html'),'data':str(out/'evidence-review.json'),'meaning':record['meaning']}


def init_ledger(paths,out,title='产品证据清单'):
    out=Path(out).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():raise ValueError('evidence ledger output already exists; preserve the original record')
    bindings={'source'+str(i+1):{'path':str(Path(p).resolve()),'sha256':sha256(Path(p))} for i,p in enumerate(paths)}
    if not bindings:raise ValueError('ledger needs at least one model, fixture or task source')
    write_json(out,{'schema_version':'simplecae-evidence-1.0','title':title,'bindings':bindings,
                   'items':[{'id':n,'domain':n,'title':t,'state':'unassessed','statement':'待补充本项计算、来源或实物测试证据。','evidence':[]} for n,t in zip(DOMAINS,TITLES)]})
    return {'ledger':str(out),'meaning':'Editable evidence checklist; no source has been marked physically verified.'}
