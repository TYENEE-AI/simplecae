"""Repeat explicit whole-face rules on each CAD revision; never guess nearest faces."""
from pathlib import Path
import json
from .case import keys, number, sha256, write_json
from .diagnostics import WorkflowError


def region_summary(faces):
    area=sum(f['area_mm2'] for f in faces)
    center=[sum(f['area_mm2']*f['centroid_mm'][i] for f in faces)/area for i in range(3)] if area else None
    return {'face_count':len(faces),'area_mm2':area,'area_weighted_centroid_mm':center}


def select_region(info, rule):
    keys(rule, ['plane', 'surface_types', 'centroid_bounds_mm', 'face_count'],
         ['face_count'], 'region rule')
    counts = rule['face_count']
    if (not isinstance(counts, list) or len(counts) != 2 or
            any(type(n) is not int or n < 1 for n in counts) or counts[0] > counts[1]):
        raise ValueError('region face_count needs explicit positive [minimum, maximum]')
    faces = list(info['faces'])
    if not any(k in rule for k in ('plane', 'surface_types', 'centroid_bounds_mm')):
        raise ValueError('region rule needs a geometric predicate')
    if 'plane' in rule:
        from .case import selector
        from .geometry import select_faces
        spec = dict(rule['plane'], type='plane'); selector(spec)
        try:ids = set(select_faces(info, spec))
        except ValueError as exc:
            raise WorkflowError(str(exc),'region_selection_invalid',fields=['regions.*.plane'],
                next_action='review_region_candidates',details={'candidate_faces':faces,'plane':spec}) from exc
        faces = [f for f in faces if f['id'] in ids]
    if 'surface_types' in rule:
        kinds = rule['surface_types']
        if not isinstance(kinds, list) or not kinds or any(not isinstance(k, str) or not k.strip() for k in kinds):
            raise ValueError('surface_types needs nonempty CAD surface type names')
        faces = [f for f in faces if f['type'] in kinds]
    if 'centroid_bounds_mm' in rule:
        bounds = rule['centroid_bounds_mm']; keys(bounds, ['x', 'y', 'z'], label='centroid bounds')
        if not bounds: raise ValueError('centroid bounds must not be empty')
        for axis, pair in bounds.items():
            if not isinstance(pair, list) or len(pair) != 2 or pair == [None, None]:
                raise ValueError('centroid bounds need [lower, upper], with at most one null')
            lo, hi = [number(v, 'centroid bound') if v is not None else v for v in pair]
            if lo is not None and hi is not None and lo > hi: raise ValueError('reversed centroid bounds')
            faces = [f for f in faces if (lo is None or f['centroid_mm']['xyz'.index(axis)] >= lo)
                     and (hi is None or f['centroid_mm']['xyz'.index(axis)] <= hi)]
    if not counts[0] <= len(faces) <= counts[1]:
        raise WorkflowError(f'region rule matched {len(faces)} faces, expected {counts}; review topology/rule, no automatic nearest-face substitution',
            'region_selection_count',fields=['regions.*.face_count'],next_action='review_region_candidates',
            details={'expected_face_count':counts,'matched':region_summary(faces),'candidate_faces':faces,
                     'available_surface_types':sorted({f['type'] for f in info['faces']})})
    return sorted(f['id'] for f in faces)


def bind_regions(model, rules_path, out, *, previous=None, native_manifest=None):
    from .geometry import session, inventory
    from .sources import SourceGuard
    from .bridge import resolve_interfaces
    model, out = map(lambda p: Path(p).resolve(), (model, out))
    source = Path(native_manifest or rules_path).resolve()
    report_path=out.with_name(out.name+'.binding-report.json')
    if out.exists() or report_path.exists(): raise ValueError('interface output and binding report must be fresh; retain the previous binding')
    guard = SourceGuard([model, source])
    spec = json.loads(source.read_text(encoding='utf-8-sig'))
    with session(model, {'path':str(model)}) as g: info = inventory(g, model)
    if native_manifest is not None:
        if rules_path is not None: raise ValueError('Choose explicit rules or a current native manifest, not both')
        resolve_interfaces(source,info)
        manifest=spec
    else:
        manifest=_rule_manifest(spec,info)
    diagnostics={}
    prior=None
    if previous is not None:
        previous=Path(previous).resolve();guard.add([previous])
        prior=json.loads(previous.read_text(encoding='utf-8-sig'))
        if prior['model_id']!=manifest['model_id']: raise ValueError('Previous binding belongs to a different model_id')
    for name,region in manifest['regions'].items():
        current=region_summary(region['faces']);old=region_summary(prior['regions'][name]['faces']) if prior and name in prior['regions'] else None
        diagnostics[name]={'current':current,'previous':old,'face_count_delta':current['face_count']-old['face_count'] if old else None,
            'area_change_fraction':current['area_mm2']/old['area_mm2']-1 if old and old['area_mm2'] else None,
            'centroid_shift_mm':[a-b for a,b in zip(current['area_weighted_centroid_mm'],old['area_weighted_centroid_mm'])] if old else None,
            'intent_verified':False}
    guard.check(); write_json(out, manifest)
    binding = resolve_interfaces(out, info)
    guard.check()
    report={'manifest':str(out),'model_sha256':info['geometry_sha256'],'regions':binding['regions'],
            'region_diagnostics':diagnostics,'previous_manifest_sha256':sha256(previous) if previous else None,
            'meaning':'Current hash-bound selections only. Area/centroid/count changes are observations, not proof of semantic intent; inspect preview. No nearest-face substitution.'}
    write_json(report_path,report)
    return report


def _rule_manifest(spec,info):
    keys(spec, ['schema_version','model_id','regions'], ['schema_version','model_id','regions'], 'region rules')
    if spec['schema_version'] != 'simplecae-region-rules-1.0' or not isinstance(spec['model_id'],str) or not spec['model_id'].strip():
        raise ValueError('region rules need supported version and stable nonempty model_id')
    if not isinstance(spec['regions'],dict) or not spec['regions']: raise ValueError('region rules need named regions')
    regions = {}
    for name, rule in spec['regions'].items():
        if not isinstance(name,str) or not name.strip(): raise ValueError('region name must not be empty')
        selected = select_region(info, rule)
        regions[name] = {'rule':rule, 'faces':[{k:f[k] for k in ('area_mm2','centroid_mm')}
                          for f in info['faces'] if f['id'] in selected]}
    manifest = {'schema_version':'1.0','generator':'custom','model_id':spec['model_id'],
                'revision':info['geometry_sha256'], 'model_sha256':info['geometry_sha256'],
                'regions':regions}
    return manifest


def region_contract(case):
    """Keep rule identity in task comparisons; source hashes still bind each solve."""
    result = {}
    models = [('body',case['model'])] if 'model' in case else [(b['name'],b['model']) for b in case.get('bodies',[])]
    for name, model in models:
        if not model.get('interface_manifest'): continue
        manifest = json.loads(Path(model['interface_manifest']).read_text(encoding='utf-8-sig'))
        if manifest['model_sha256'] != sha256(Path(model['path'])):
            raise ValueError('region manifest belongs to a different model hash')
        regions = manifest['regions']
        placement=next((b.get('placement',{}) for b in case.get('bodies',[]) if b['name']==name),{})
        result[name] = {'model_id':manifest['model_id'], 'placement':placement, 'regions':{
            k:({'rule':v['rule']} if 'rule' in v else
               {'legacy_source_sha256':manifest['model_sha256'],'faces':v['faces']}) for k,v in regions.items()}}
    return {'region_bindings':result} if result else {}
