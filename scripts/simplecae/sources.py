"""Reject changes to any file contributing to one numerical problem."""
from pathlib import Path
from .case import load_case, sha256


def source_paths(case):
    paths=set()
    if case.get('schema_version') in ('fatigue-data-1.0', 'creep-data-1.0'):
        from .durability import evidence_sources
        paths.update(Path(s['path']).resolve() for s in evidence_sources(case))
    for model in [case.get('model',{})]+[b['model'] for b in case.get('bodies',[])]:
        for key in ('path','interface_manifest'):
            if model.get(key):paths.add(Path(model[key]).resolve())
    for component in case.get('components',[]):
        template=Path(component['case_path']).resolve()
        paths.add(template)
        paths.update(source_paths(load_case(template)))
    if case.get('schema_version') in ('robot-1.0', 'motion-loads-1.0'):
        from .robot import read_urdf
        model=case['model']
        robot=read_urdf(model['path'],model.get('package_roots',{}),case.get('massless_links',[]))
        paths.update(Path(asset['path']).resolve() for asset in robot['assets'])
    return paths


class SourceGuard:
    def __init__(self, paths):
        self.hashes={str(p):sha256(p) for p in sorted({Path(p).resolve() for p in paths})}

    def check(self):
        for name,expected in self.hashes.items():
            path=Path(name)
            if not path.is_file() or sha256(path)!=expected:
                raise RuntimeError(f'Analysis source changed or disappeared: {name}')

    def add(self, paths):
        self.check()
        for p in paths:
            p=Path(p).resolve()
            if str(p) not in self.hashes:self.hashes[str(p)]=sha256(p)

    def check_mesh(self, case, metadata):
        models=([case['model']] if 'model' in case else [b['model'] for b in case['bodies']])
        geometries=([metadata['geometry']] if 'model' in case else [r['source_geometry'] for r in metadata['body_reports']])
        for model,geometry in zip(models,geometries):
            if geometry['geometry_sha256']!=self.hashes[str(Path(model['path']).resolve())]:
                raise RuntimeError('Meshed geometry differs from the initial analysis source')
            manifest=model.get('interface_manifest')
            if manifest and geometry.get('interfaces',{}).get('manifest_sha256')!=self.hashes[str(Path(manifest).resolve())]:
                raise RuntimeError('Meshed interfaces differ from the initial analysis source')
