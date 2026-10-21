"""Bind generator-native semantic faces to an inspected immutable export."""
from pathlib import Path
import json
import numpy as np
from .case import keys,number,vector,sha256


def resolve_interfaces(path,inventory):
    path=Path(path)
    manifest=json.loads(path.read_text(encoding='utf-8-sig'))
    keys(manifest,['schema_version','generator','generator_version','model_id','revision','parameters','model_path',
                   'model_sha256','package_path','package_sha256','regions','export_report'],
         ['schema_version','generator','model_id','revision','model_sha256','regions'],'interface manifest')
    if manifest['schema_version']!='1.0' or manifest['generator'] not in ('simplecadapi','cadgen','custom'):
        raise ValueError('unsupported interface manifest version or generator')
    if manifest['model_sha256']!=inventory['geometry_sha256']:
        raise ValueError('interface manifest belongs to a different model hash; regenerate from native selections')
    if not isinstance(manifest['regions'],dict) or not manifest['regions']:
        raise ValueError('interface manifest needs named regions')
    result={}
    for name,region in manifest['regions'].items():
        keys(region,['faces','native_selector','rule'],['faces'],'interface region')
        if not isinstance(name,str) or not name or not isinstance(region['faces'],list) or not region['faces']:
            raise ValueError('interface regions require nonempty names and face signatures')
        resolved=[]
        for signature in region['faces']:
            keys(signature,['centroid_mm','area_mm2'],['centroid_mm','area_mm2'],'face signature')
            center=vector(signature['centroid_mm'],'face center')
            area=number(signature['area_mm2'],'face area',True)
            matches=[f['id'] for f in inventory['faces'] if np.allclose(f['centroid_mm'],center,rtol=0,atol=1e-3)
                     and abs(f['area_mm2']-area)<=max(area*1e-5,1e-6)]
            if len(matches)!=1:
                raise ValueError(f'interface {name} signature matched {len(matches)} whole faces; refine native selection/export')
            resolved.extend(matches)
        if len(set(resolved))!=len(resolved):
            raise ValueError('interface has duplicate face signatures')
        if 'rule' in region:
            from .region_rules import select_region
            if sorted(resolved) != select_region(inventory, region['rule']):
                raise ValueError(f'interface {name} signatures contradict its region rule')
        result[name]=sorted(resolved)
    return {'regions':result,'manifest_sha256':sha256(path),'generator':manifest['generator'],
            'model_id':manifest['model_id'],'revision':manifest['revision'],
            'meaning':'Native selections rebound by unique centroid/area signatures and exact model hash; face IDs are not inherited across edits.'}
