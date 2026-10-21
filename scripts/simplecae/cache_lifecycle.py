"""Explicit cache inventory, verified archive and fresh restore; no automatic purge."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile
from .case import sha256, write_json
from .retention import _linked


def _files(root):
    if _linked(root): raise ValueError('Cache root must not be a link/reparse point')
    files={}
    for p in root.rglob('*'):
        if _linked(p) or not p.resolve().is_relative_to(root): raise ValueError('Cache contains a link or escaped path')
        if p.is_file():files[p.relative_to(root).as_posix()]={'sha256':sha256(p),'bytes':p.stat().st_size}
    return files


def _strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,list):
        for item in value:yield from _strings(item)
    elif isinstance(value,dict):
        for k,v in value.items():yield k;yield from _strings(v)


def plan_cache(root, references=()):
    root=Path(root).absolute()
    if _linked(root):raise ValueError('Cache root must not be a link/reparse point')
    root=root.resolve()
    # Never mistake a task/output/source directory for a cache.
    base=root/'levels' if (root/'levels').is_dir() else root
    if base!=root and set(root.iterdir())!={base}:raise ValueError('Expected a dedicated solved-level cache')
    children=list(base.iterdir())
    if not children or any(not p.is_dir() or not re.fullmatch('[0-9a-f]{64}',p.name) for p in children):
        raise ValueError('Expected a dedicated SimpleCAE cache with hash-key directories')
    files=_files(root);found=[];errors=[];scanned={}
    for ref in references:
        ref=Path(ref).resolve()
        if not ref.exists():raise ValueError('Reference root does not exist')
        paths=[ref] if ref.is_file() else sorted(ref.rglob('*.json'))
        for path in paths:
            if path.is_relative_to(root):continue
            try:
                value=json.loads(path.read_text(encoding='utf-8-sig'));scanned[str(path)]=sha256(path)
                for s in _strings(value):
                    if len(s)>32767:continue
                    candidate=Path(s)
                    if candidate.is_absolute() and candidate.resolve().is_relative_to(root):
                        found.append({'record':str(path),'target':str(candidate.resolve())})
            except (OSError,ValueError) as exc:errors.append({'record':str(path),'error':str(exc)})
    return {'schema_version':'simplecae-cache-plan-1','root':str(root),'files':files,
            'total_bytes':sum(f['bytes'] for f in files.values()),'references':found,'reference_errors':errors,
            'reference_roots':[str(Path(p).resolve()) for p in references],'reference_hashes':scanned,
            'deletion_authorized':False,
            'meaning':'Read-only inventory. References cover only explicitly supplied roots. Archive does not delete originals; retain source models, task ledgers and reports separately.'}


def archive_cache(plan_path,out):
    plan=json.loads(Path(plan_path).read_text(encoding='utf-8-sig'));root=Path(plan['root']).resolve();out=Path(out).resolve()
    if plan.get('schema_version')!='simplecae-cache-plan-1':raise ValueError('Unsupported cache plan')
    if out.exists() or out.is_relative_to(root):raise ValueError('Archive must be fresh and outside the cache')
    if _files(root)!=plan['files']:raise ValueError('Cache changed after preview; regenerate the plan')
    out.parent.mkdir(parents=True,exist_ok=True)
    from .resources import require_storage
    require_storage(out.parent,plan['total_bytes'])
    with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        archive.writestr('cache-manifest.json',json.dumps(plan,ensure_ascii=False))
        for name in plan['files']:archive.write(root/name,'data/'+name)
    check=verify_archive(out)
    if _files(root)!=plan['files']:raise ValueError('Cache changed during archive; originals retained, regenerate after writers stop')
    receipt={'archive':str(out),'archive_sha256':sha256(out),'verified_files':check['verified_files'],
             'originals_retained':True,'references':plan['references'],'deletion_authorized':False}
    write_json(out.with_name(out.name+'.receipt.json'),receipt);return receipt


def verify_archive(path):
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate archive entries')
        info=archive.getinfo('cache-manifest.json')
        if info.file_size>32*1024**2:raise ValueError('Oversized archive manifest')
        manifest=json.loads(archive.read(info))
        if manifest.get('schema_version')!='simplecae-cache-plan-1':raise ValueError('Unsupported archive manifest')
        expected={'cache-manifest.json'}
        for name,record in manifest['files'].items():
            p=PurePosixPath(name)
            if not name or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or p.as_posix()!=name:
                raise ValueError('Unsafe archive path')
            member='data/'+name;expected.add(member)
            info=archive.getinfo(member)
            if info.file_size!=record['bytes']:raise ValueError('Archive size mismatch')
            h=hashlib.sha256()
            with archive.open(info) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
            if h.hexdigest()!=record['sha256']:raise ValueError('Archive hash mismatch')
        if set(names)!=expected:raise ValueError('Unlisted archive members')
        return {'verified_files':len(manifest['files']),'manifest':manifest}


def restore_cache(archive_path,out):
    archive_path=Path(archive_path).resolve();out=Path(out).absolute()
    if out.exists() or out.is_symlink():raise ValueError('Restore needs a fresh destination')
    # Verify the entire archive before creating any recovery file.
    check=verify_archive(archive_path);before=sha256(archive_path);manifest=check['manifest']
    from .resources import require_storage
    require_storage(out,sum(f['bytes'] for f in manifest['files'].values()))
    out.mkdir(parents=True,exist_ok=False);out=out.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for name,record in manifest['files'].items():
            target=(out/name).resolve()
            if not target.is_relative_to(out):raise ValueError('Recovery path escaped destination')
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open('data/'+name) as src,target.open('xb') as dst:
                import shutil
                shutil.copyfileobj(src,dst,1024*1024)
    if sha256(archive_path)!=before or _files(out)!=manifest['files']:raise ValueError('Recovery verification failed; retain diagnostics and do not use partial cache')
    return {'restored':str(out),'verified_files':check['verified_files'],'original_archive_retained':True,
            'meaning':'Byte-identical cache restore only. Normal solver-cache validation still runs; no task verdict restored.'}
