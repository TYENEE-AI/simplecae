"""Typed case batches with native-crash isolation and audited resume receipts."""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from pathlib import Path
from datetime import datetime,timezone
import json,re,subprocess,sys
from .case import keys,number,sha256,write_json
from .sources import SourceGuard,source_paths
from .paths import worker_entry
from .execution import run_owned_worker

def load_campaign(path):
    path=Path(path).resolve();value=json.loads(path.read_text(encoding='utf-8-sig'))
    keys(value,['schema_version','title','items','notes'],['schema_version','title','items'],'campaign')
    if value['schema_version']!='simplecae-campaign-1.0':raise ValueError('unsupported campaign schema_version')
    if not isinstance(value['title'],str) or not value['title'].strip():raise ValueError('campaign title must be nonempty')
    if not isinstance(value['items'],list) or not value['items']:raise ValueError('campaign needs items')
    names=[]
    for item in value['items']:
        keys(item,['id','case_path','case_sha256','ledger_path'],['id','case_path','case_sha256'],'campaign item')
        if not isinstance(item['id'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',item['id']):raise ValueError('campaign id must be a safe unique name')
        names.append(item['id'])
        for key in ('case_path','ledger_path'):
            if key in item:
                p=Path(item[key]);item[key]=str((path.parent/p).resolve() if not p.is_absolute() else p.resolve())
        if sha256(Path(item['case_path']))!=item['case_sha256']:raise ValueError('campaign case hash mismatch for '+item['id'])
    if len(set(names))!=len(names):raise ValueError('campaign ids must be unique')
    return value

def file_hashes(folder):
    return {p.relative_to(folder).as_posix():sha256(p) for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='completion.json'}

def run_campaign(path,out,*,ccx=None,timeout=DEFAULT_NATIVE_TIMEOUT,preview=True,resume=False,progress=None,reuse_levels=None,storage='compact'):
    from .retention import validate_storage
    validate_storage(storage)
    from .api import check_case
    from .cache import cache_key
    from .solver import find_ccx
    from .progress import emit
    from . import __version__
    path=Path(path).resolve();out=Path(out).resolve();campaign=load_campaign(path);executable=find_ccx(ccx)
    if out.exists() and not resume:raise ValueError('campaign output exists; use a fresh directory or explicit --resume')
    out.mkdir(parents=True,exist_ok=True);records=[]
    def save():
        order={'pass_under_stated_model':0,'fail_under_stated_model':1,'indeterminate':2,'invalid':3}
        counts={state:sum(r['status']==state for r in records) for state in order}
        report={'schema_version':'simplecae-campaign-result-1.0','toolkit_version':__version__,'title':campaign['title'],
            'campaign_sha256':sha256(path),'items':records,'requested_count':len(campaign['items']),
            'completed_count':len(records),'status':max((r['status'] for r in records),key=order.get,default='indeterminate'),
            'status_counts':counts,'all_results_valid':len(records)==len(campaign['items']) and all(r.get('valid_for_comparison') for r in records),
            'whole_product_rating_available':False,'physical_tests_performed':False}
        write_json(out/'campaign-result.json',report)
        return report
    for index,item in enumerate(campaign['items']):
        emit(progress,'campaign_item',item=item['id'],index=index+1,total=len(campaign['items']))
        root=out/'items'/item['id'];root.mkdir(parents=True,exist_ok=True)
        entry={'id':item['id'],'case_path':item['case_path'],'status':'invalid','valid_for_comparison':False,'physical_conditions_verified':False};directory=None
        try:
            case=check_case(item['case_path']);key=cache_key(case,executable)
            guard=SourceGuard(source_paths(case)|{Path(item['case_path']),path})
            receipt=None;directory=None;reused=False
            if resume:
                for candidate in sorted(root.glob('attempt-*'),reverse=True):
                    record=candidate/'completion.json'
                    if not record.is_file():continue
                    try:
                        current=json.loads(record.read_text(encoding='utf-8'))
                        if (current['analysis_key']==key and current['process_exit']==0
                                and current.get('source_files_sha256')==guard.hashes
                                and current['files']==file_hashes(candidate)):
                            receipt=current;directory=candidate;reused=True;break
                    except (OSError,ValueError,KeyError):continue
            if receipt is None:
                numbers=[int(p.name.split('-')[-1]) for p in root.glob('attempt-*') if p.is_dir() and p.name.split('-')[-1].isdigit()]
                directory=root/f'attempt-{max(numbers,default=0)+1:04d}';directory.mkdir()
                analysis=directory/'analysis'
                command=[sys.executable,worker_entry(),'analyze',item['case_path'],'--out',str(analysis),'--ccx',str(executable),'--timeout',str(timeout),'--quiet','--storage',storage]
                if not preview:command.append('--no-preview')
                if reuse_levels:command+=['--reuse-levels',str(Path(reuse_levels).resolve()/item['id'])]
                # The child isolates C++ aborts. Solver-level timeout is still enforced.
                start=datetime.now(timezone.utc).isoformat()
                max_wall=timeout*max(3,len(case.get('mesh',{}).get('sizes_mm',[0,1,2])))*2*max(1,len(case.get('load_cases',[])))+120
                with (directory/'process.log').open('w',encoding='utf-8') as stream:
                    try:process=run_owned_worker(command,stdout=stream,stderr=subprocess.STDOUT,timeout=max_wall)
                    except subprocess.TimeoutExpired:
                        write_json(directory/'process-timeout.json',{'wall_timeout_seconds':max_wall})
                        raise RuntimeError('native analysis process exceeded campaign wall timeout; retained artifacts')
                guard.check()
                if cache_key(check_case(item['case_path']),executable)!=key:raise RuntimeError('campaign source/tool changed during analysis')
                receipt={'analysis_key':key,'started_utc':start,'completed_utc':datetime.now(timezone.utc).isoformat(),
                    'process_exit':process.returncode,'source_files_sha256':guard.hashes,'files':file_hashes(directory)}
                write_json(directory/'completion.json',receipt)
            guard.check();entry.update(output_relative_path=directory.relative_to(out).as_posix(),resumed=reused)
            if receipt['process_exit']!=0:raise RuntimeError(f"native analysis process exited {receipt['process_exit']}; retained process.log and incomplete artifacts")
            signal=json.loads((directory/'analysis'/'signal.json').read_text(encoding='utf-8'))
            entry.update(status=signal['analysis_status'],valid_for_comparison=signal['valid_for_comparison'],physical_conditions_verified=signal['physical_conditions_verified'],signal=signal)
            if item.get('ledger_path'):
                from .evidence import inspect_ledger
                entry['evidence']=inspect_ledger(Path(item['ledger_path']))
        except (OSError,ValueError,RuntimeError,KeyError) as exc:
            entry.update(status='invalid',valid_for_comparison=False,physical_conditions_verified=False,error=str(exc))
        if directory is not None:entry['output_relative_path']=directory.relative_to(out).as_posix()
        records.append(entry);save()
    return save()
