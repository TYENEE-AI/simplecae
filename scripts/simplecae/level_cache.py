"""Opt-in immutable solved-mesh evidence, including indeterminate refinements."""
from pathlib import Path
from copy import deepcopy
import json,shutil,uuid
import numpy as np
from .case import sha256,write_json
from .cache import cache_key,files_digest


def level_key(case,h,executable):
    physics=deepcopy(case)
    physics['mesh']['sizes_mm']=[h]
    # Unlike pose-level complete reuse, continuation requires exact floating
    # input values. All other criteria, bounds, source and tool hashes remain.
    return cache_key(physics,executable,normalize=False)


def write_state(mesh,directory):
    xyz,tets,fixed,forces,_=mesh
    ids=list(xyz);elements=list(tets);fids=list(forces)
    np.savez_compressed(Path(directory)/'mesh-state.npz',node_ids=np.asarray(ids,dtype=np.int64),
                        xyz=np.asarray([xyz[n] for n in ids]),element_ids=np.asarray(elements,dtype=np.int64),
                        connectivity=np.asarray([tets[e] for e in elements],dtype=np.int64),
                        fixed=np.asarray(fixed,dtype=np.int64),force_node_ids=np.asarray(fids,dtype=np.int64),
                        forces=np.asarray([forces[n] for n in fids],dtype=float).reshape(-1,3))


def read_state(directory,meta):
    with np.load(Path(directory)/'mesh-state.npz',allow_pickle=False) as a:
        ids=a['node_ids'];elements=a['element_ids'];conn=a['connectivity'];p=a['xyz'];fids=a['force_node_ids'];f=a['forces'];fixed=a['fixed']
        if len(ids)!=len(set(ids)) or len(elements)!=len(set(elements)) or len(fids)!=len(set(fids)):
            raise ValueError('reused mesh contains duplicate IDs')
        if p.shape!=(len(ids),3) or conn.shape!=(len(elements),10) or f.shape!=(len(fids),3) or not np.all(np.isfinite(p)) or not np.all(np.isfinite(f)):
            raise ValueError('reused mesh state shape or values are invalid')
        if set(conn.ravel())-set(ids) or set(fixed)-set(ids) or set(fids)-set(ids):raise ValueError('reused mesh references unknown nodes')
        if meta['node_count']!=len(ids) or meta['element_count']!=len(elements):raise ValueError('reused mesh metadata count mismatch')
        xyz={int(n):v.copy() for n,v in zip(ids,p)};tets={int(e):[int(n) for n in nodes] for e,nodes in zip(elements,conn)}
        forces={int(n):v.copy() for n,v in zip(fids,f)}
        return xyz,tets,[int(n) for n in fixed],forces,meta


def relocate(value,origin,out):
    if isinstance(value,str) and (value==str(origin) or value.startswith(str(origin)+'\\') or value.startswith(str(origin)+'/')):
        return str(out)+value[len(str(origin)):]
    if isinstance(value,list):return [relocate(v,origin,out) for v in value]
    if isinstance(value,dict):return {k:relocate(v,origin,out) for k,v in value.items()}
    return value


def restore(root,key,directory):
    folder=Path(root).resolve()/'levels'/key;index=folder/'latest.json'
    if not index.is_file():return None
    try:
        record=json.loads(index.read_text(encoding='utf-8'));source=(folder/record['directory']).resolve()
        if not source.is_relative_to(folder) or not source.is_dir() or files_digest(source)!=record['files']:return None
        level=json.loads((source/'results.json').read_text(encoding='utf-8'))
        if not record.get('numerical_level_complete') or not (source/'mesh-state.npz').is_file():return None
        required=['mesh.npz','job.inp','job.dat','job.frd','job.solver.log']
        if level['mesh'].get('fixed_nodal_forces'):required+=['fixed.inp','fixed.dat','fixed.frd','fixed-results.json']
        if level.get('buckling'):required+=['buckling.inp','buckling.dat','buckling.frd']
        if any(not (source/name).is_file() or (source/name).stat().st_size==0 for name in required):return None
        level=relocate(level,Path(record['original_output']).resolve(),Path(directory).resolve())
        # Validate readable state before restoring, so corruption is a clean miss.
        read_state(source,level['mesh'])
    except (OSError,ValueError,KeyError,TypeError):return None
    # Disk failure is fatal. Never fall through into a solver on partial output.
    from .resources import require_storage,folder_bytes
    require_storage(directory,folder_bytes(source))
    shutil.copytree(source,directory,dirs_exist_ok=True)
    level['level_reuse']={'key':key,'original_output':record['original_output'],
                          'numerical_evidence_created_at_utc':level.get('created_at_utc'),
                          'meaning':'Exact physics/source/tool/solver match; DAT fields and input decks independently rechecked in the new output.'}
    return read_state(directory,level['mesh']),level


def save(root,key,directory,level,tolerance):
    summary=level['results']
    if max(summary['force_balance_relative_error'],summary['moment_balance_relative_error'])>tolerance:return False
    folder=Path(root).resolve()/'levels'/key;directory=Path(directory).resolve()
    if folder.is_relative_to(directory):raise ValueError('level cache must be outside the analysis output')
    folder.mkdir(parents=True,exist_ok=True);target=folder/uuid.uuid4().hex
    from .resources import require_storage,folder_bytes
    require_storage(folder,folder_bytes(directory))
    shutil.copytree(directory,target)
    record={'directory':target.name,'original_output':str(directory),'files':files_digest(target),'numerical_level_complete':True}
    pending=folder/(uuid.uuid4().hex+'.json');write_json(pending,record);pending.replace(folder/'latest.json')
    return True


def verify_deck(case,mesh,directory,filename='job'):
    from .solver import write_deck
    original=Path(directory)/(filename+'.inp');reconstructed=Path(directory)/('reconstructed-'+filename+'.inp')
    write_deck(case,mesh,reconstructed)
    if sha256(original)!=sha256(reconstructed):raise ValueError('reused numerical deck does not match reconstructed current physics')


def verify_buckling(case,mesh,directory,cached):
    from .buckling import parse_buckling_dat,write_buckling_deck
    directory=Path(directory);inp=directory/'reconstructed-buckling.inp';write_buckling_deck(case,mesh,inp)
    if sha256(inp)!=sha256(directory/'buckling.inp'):raise ValueError('reused buckling deck differs from current physics')
    factors,modes=parse_buckling_dat(directory/'buckling.dat')
    if factors!=cached['factors'] or set(modes)!=set(cached['available_modes']):raise ValueError('reused buckling factor/mode mismatch')
    for values in modes.values():
        if set(values)!=set(mesh[0]) or not all(np.all(np.isfinite(v)) for v in values.values()) or max(np.linalg.norm(v) for v in values.values())<=0:
            raise ValueError('reused buckling field coverage/values invalid')
    return cached
