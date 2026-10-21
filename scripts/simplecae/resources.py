"""Conservative storage preflight; never delete evidence to make room."""
from pathlib import Path
import errno,shutil

RESERVE_BYTES=256*1024**2

def require_storage(path,estimated_bytes=0):
    directory=Path(path).resolve()
    while not directory.exists():directory=directory.parent
    free=shutil.disk_usage(directory).free
    required=int(max(0,estimated_bytes))+RESERVE_BYTES
    if free<required:
        raise OSError(errno.ENOSPC,
            f'Insufficient disk space at {directory}: free {free/1024**2:.1f} MiB; '
            f'need approximately {required/1024**2:.1f} MiB including a256 MiB reserve. '
            'Choose another output/cache volume or explicitly archive obsolete data; retained evidence was not deleted.')
    return {'free_bytes':free,'estimated_additional_bytes':int(max(0,estimated_bytes)),
            'reserve_bytes':RESERVE_BYTES,'estimate_is_guarantee':False}

def native_output_estimate(mesh,case):
    # DAT/FRD, decks, meshes, fields and JSON. Actual solver/filesystem growth varies.
    jobs=1+bool(mesh.get('fixed_nodal_forces'))+bool(case.get('buckling',{}).get('enabled'))
    from .contact import enabled,stage_names
    if enabled(case):jobs=len(stage_names(case))
    return jobs*(mesh['node_count']*2048+mesh['element_count']*8192)

def folder_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob('*') if p.is_file())
