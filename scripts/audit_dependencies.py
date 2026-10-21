"""Collect exact installed dependency notices; no wheels or binaries are redistributed."""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata as metadata
import json
import re


def collect(root):
    inventory_path=root/'licenses/dependency-inventory.json'
    old=json.loads(inventory_path.read_text(encoding='utf-8')) if inventory_path.exists() else {'dependencies':[]}
    records=[]
    for line in (root/'requirements-lock.txt').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):continue
        name,version=line.split('==')
        dist=metadata.distribution(name)
        if dist.version!=version:raise ValueError(f'{name}: installed version does not match lock')
        notices=[]
        for entry in sorted(dist.files or [],key=str):
            if not re.search(r'licen[cs]e|copying|notice|authors',Path(str(entry)).name,re.I):continue
            source=Path(dist.locate_file(entry))
            if not source.is_file():raise ValueError(f'{name}: notice file missing: {entry}')
            target=Path('licenses/dependencies')/name/(f'{len(notices):02d}-'+source.name)
            data=source.read_bytes();(root/target).parent.mkdir(parents=True,exist_ok=True)
            (root/target).write_bytes(data)
            notices.append({'installed_relative_path':str(entry).replace('\\','/'),
                            'notice_path':target.as_posix(),'sha256':hashlib.sha256(data).hexdigest()})
        if not notices:raise ValueError(f'{name}: no installed license/notice found; review manually')
        fields=dist.metadata
        records.append({'name':name,'version':version,'license_expression':fields.get('License-Expression'),
                        'license_metadata':fields.get('License'),
                        'license_classifiers':[v for v in fields.get_all('Classifier',[]) if 'License' in v],
                        'project_urls':fields.get_all('Project-URL',[]),'notices':notices})
    result={'scope':'Exact Windows Python lock, including test/transitive packages. Metadata and notices are retained verbatim; dependency code/binaries are not bundled.',
            'dependencies':records}
    inventory_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    retained={v['notice_path'] for d in records for v in d['notices']}
    for entry in (v for d in old['dependencies'] for v in d['notices']):
        path=(root/entry['notice_path']).resolve()
        if entry['notice_path'] not in retained and path.is_relative_to((root/'licenses/dependencies').resolve()):path.unlink(missing_ok=True)
    return result


def check(root):
    inventory=json.loads((root/'licenses/dependency-inventory.json').read_text(encoding='utf-8'))
    expected=dict(line.split('==') for line in (root/'requirements-lock.txt').read_text(encoding='utf-8').splitlines() if line.strip() and not line.startswith('#'))
    actual={r['name']:r['version'] for r in inventory['dependencies']}
    if actual!=expected:raise ValueError('dependency notice inventory does not match the lock')
    count=0
    for record in inventory['dependencies']:
        if not record['notices']:raise ValueError('missing dependency notice')
        for item in record['notices']:
            path=(root/item['notice_path']).resolve()
            if not path.is_relative_to((root/'licenses').resolve()):raise ValueError('notice escapes license directory')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('changed dependency notice')
            count+=1
    if 'GNU GENERAL PUBLIC LICENSE' not in (root/'LICENSE').read_text(encoding='utf-8'):raise ValueError('missing full project license')
    return {'passed':True,'locked_distributions':len(actual),'notice_files':count,
            'project_license':'GPL-3.0-or-later','dependency_code_bundled':False,
            'scope':'Notice completeness and hashes; not a legal opinion or clearance of third-party binary redistribution.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--collect',action='store_true');p.add_argument('--out',type=Path);a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    if a.collect:collect(root)
    result=check(root)
    if a.out:a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
