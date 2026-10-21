"""Opt-in reuse of complete valid numerical evidence with mechanical input keys."""
from pathlib import Path
from copy import deepcopy
import hashlib,importlib.metadata,json,shutil,uuid
from .case import sha256,write_json
from . import __version__

def canonical(value):
    # Frame conversion creates harmless floating point cancellation. Twelve
    # significant digits bound key normalization far below numerical tolerances.
    if isinstance(value,float):return float(f'{value:.12g}')
    if isinstance(value,list):return [canonical(v) for v in value]
    if isinstance(value,dict):return {k:canonical(v) for k,v in value.items()}
    return value

def cache_key(case,executable,*,normalize=True):
    physics=deepcopy(case)
    for field in ('provenance','notes'):physics.pop(field,None)
    models=([physics['model']] if 'model' in physics else [b['model'] for b in physics['bodies']])
    for model in models:
        native=Path(model['path']).suffix.lower() in ('.step','.stp')
        for field in ('path','interface_manifest'):
            if model.get(field):model[field]=sha256(Path(model[field]))
        if native and model.get('units')=='mm':model.pop('units')
    code={p.name:sha256(p) for p in Path(__file__).parent.glob('*.py')}
    versions={n:importlib.metadata.version(n) for n in ('gmsh','numpy','scipy','trimesh','manifold3d')}
    from .solver import execution_threads
    from .parallel import default_profile_path
    import os
    profile=Path(os.environ.get('SIMPLECAE_RESOURCE_PROFILE') or default_profile_path())
    key={'physics':canonical(physics) if normalize else physics,'toolkit':__version__,'code':code,'packages':versions,'ccx':sha256(executable),'solver_threads':execution_threads(),
         'thread_mode':os.environ.get('SIMPLECAE_SOLVER_THREADS','auto'),
         'resource_profile':sha256(profile) if profile.is_file() else None}
    return hashlib.sha256(json.dumps(key,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def files_digest(folder):
    return {p.relative_to(folder).as_posix():sha256(p) for p in folder.rglob('*') if p.is_file()}

def load(cache_root,key,out):
    root=Path(cache_root).resolve()/key;index=root/'latest.json'
    if not index.is_file():return None
    try:
        record=json.loads(index.read_text(encoding='utf-8'))
        source=(root/record['directory']).resolve()
        if not source.is_relative_to(root.resolve()) or not source.is_dir():return None
        if files_digest(source)!=record['files']:return None
        result=json.loads((source/'result.json').read_text(encoding='utf-8'))
        if result.get('status') not in ('pass_under_stated_model','fail_under_stated_model') or not result.get('evaluation_signal',{}).get('valid_for_comparison'):return None
        origin=Path(record['original_output']).resolve()
        def relocate(value):
            if isinstance(value,str) and (value==str(origin) or value.startswith(str(origin)+'\\') or value.startswith(str(origin)+'/')):
                return str(out.resolve())+value[len(str(origin)):]
            if isinstance(value,list):return [relocate(v) for v in value]
            if isinstance(value,dict):return {k:relocate(v) for k,v in value.items()}
            return value
        result=relocate(result)
        result['analysis_reuse']={'cache_key':key,'numerical_evidence_created_at_utc':result.get('created_at_utc'),
            'meaning':'Numerical evidence reused for the same normalized mechanical inputs and toolkit/solver; current sources are checked anew.'}
    except (OSError,ValueError,KeyError,TypeError):return None
    # An I/O failure during restoration must abort, rather than start a solver
    # in a partially restored output directory. Corrupt evidence above is a miss.
    from .resources import require_storage,folder_bytes
    require_storage(out,folder_bytes(source))
    shutil.copytree(source,out,dirs_exist_ok=True)
    return result

def save(cache_root,key,out,result):
    if result.get('status') not in ('pass_under_stated_model','fail_under_stated_model') or not result.get('evaluation_signal',{}).get('valid_for_comparison'):return
    root=Path(cache_root).resolve()/key
    if root.is_relative_to(out.resolve()):raise ValueError('cache directory must be outside the analysis output')
    root.mkdir(parents=True,exist_ok=True)
    source=root/uuid.uuid4().hex
    from .resources import require_storage,folder_bytes
    require_storage(root,folder_bytes(out))
    shutil.copytree(out,source)
    write_json(root/'latest.json',{'directory':source.name,'original_output':str(out.resolve()),'files':files_digest(source)})
