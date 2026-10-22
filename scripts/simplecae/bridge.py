"""Bind generator-native semantic faces to an inspected immutable export."""
from pathlib import Path
import json
import numpy as np
from .case import keys,number,vector,sha256
from .diagnostics import WorkflowError


def manifest_identity(manifest):
    if manifest.get('schema')=='simplecae.interface_manifold/2':
        p=manifest.get('provenance')
        fields=('generator','generator_version','definition_id','revision','content_hash')
        if not isinstance(p,dict) or any(not isinstance(p.get(k),str) or not p[k] for k in fields):
            raise ValueError('manifest provenance requires nonempty '+', '.join(fields))
        return {'model_id':p['definition_id'],'revision':p['revision'],'model_sha256':p['content_hash'],
                'generator':p['generator'],'generator_version':p['generator_version']}
    return {k:manifest.get(k) for k in ('model_id','revision','model_sha256','generator','generator_version')}


def manifest_model(path, model):
    """Carry a v2 part selection into the normal source-bound STEP importer."""
    manifest=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if manifest.get('schema')!='simplecae.interface_manifold/2': return model
    identity=manifest_identity(manifest)
    if identity['model_sha256']!=sha256(Path(model['path'])):
        raise ValueError('interface manifest belongs to a different model hash; regenerate from native selections')
    part=manifest.get('part',{})
    if part.get('solid_id') is not None:
        identifier=part['solid_id']
        if type(identifier) is not int or identifier<1: raise ValueError('manifest part.solid_id must be a positive integer')
        selected={'id':identifier,'geometry_sha256':identity['model_sha256']}
        if model.get('solid_id') and model['solid_id']!=selected:
            raise ValueError('manifest part and model.solid_id select different solids')
        return dict(model,solid_id=selected)
    if part.get('step_label'):
        return dict(model,interface_step_label=part['step_label'])
    return model


def _placement(manifest, inventory):
    if manifest['frame']=='world': return np.eye(4),'world'
    placement=manifest.get('placement') or {}
    matrix=placement.get('matrix_4x4')
    source='explicit'
    if matrix is None:
        # Only source-bound placement from the selected occurrence may be used.
        record=inventory.get('occurrence_placement') or {}
        if not record and inventory.get('source_step') and inventory.get('source_solid_label'):
            from .step_metadata import occurrence_placement,assembly_tree_placement
            source_path=Path(inventory['source_step'])
            if sha256(source_path)!=inventory['geometry_sha256']:raise ValueError('STEP source changed before occurrence placement lookup')
            record=(occurrence_placement(source_path,inventory['source_solid_label'],manifest['provenance']['definition_id']) or
                    assembly_tree_placement(source_path,inventory['source_solid_label']) or {})
        matrix=record.get('matrix_4x4');source=record.get('source')
    if matrix is None:
        raise WorkflowError('part_local manifest requires an explicit or source-bound occurrence placement; no world-frame fallback',
                            'missing_occurrence_placement',fields=['placement.matrix_4x4'],next_action='export_occurrence_placement')
    try: matrix=np.asarray(matrix,dtype=float)
    except (ValueError,TypeError) as exc: raise ValueError('placement must be a finite rigid 4x4 matrix') from exc
    if (matrix.shape!=(4,4) or not np.all(np.isfinite(matrix)) or
        not np.allclose(matrix[3],[0,0,0,1],rtol=0,atol=1e-10) or
        not np.allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3),rtol=0,atol=1e-8) or
        not np.isclose(np.linalg.det(matrix[:3,:3]),1,rtol=0,atol=1e-8)):
        raise ValueError('placement must be a finite rigid 4x4 matrix in mm; scaling/reflection is unsupported')
    return matrix,source


def _resolve_v2(manifest, inventory):
    keys(manifest,['schema','frame','part','placement','regions','provenance'],
         ['schema','frame','part','regions','provenance'],'interface manifest v2')
    if manifest['frame'] not in ('world','part_local'): raise ValueError('manifest frame must be world or part_local')
    keys(manifest['part'],['solid_id','step_label'],label='manifest part')
    if manifest.get('placement') is not None:
        keys(manifest['placement'],['source','matrix_4x4'],label='manifest placement')
    provenance=manifest['provenance']
    keys(provenance,['generator','generator_version','definition_id','revision','content_hash','parameters','package_id','package_version','package_sha256','source_file','source_files_sha256','semantic_family','cad_material_label','cad_density_kg_m3'],
         ['generator','generator_version','definition_id','revision','content_hash'],'manifest provenance')
    if any(not isinstance(provenance[k],str) or not provenance[k] for k in ('generator','generator_version','definition_id','revision','content_hash')):
        raise ValueError('manifest provenance identity fields must be nonempty strings')
    if provenance['content_hash']!=inventory['geometry_sha256']:
        raise ValueError('interface manifest belongs to a different model hash; regenerate from native selections')
    if inventory.get('solid_count',1)!=1: raise ValueError('v2 binding requires exactly one selected solid')
    part=manifest['part'];selected=inventory.get('source_solid_id')
    if part.get('solid_id') is not None and part['solid_id']!=selected:
        raise ValueError('manifest solid_id does not match the inspected selected solid')
    if part.get('step_label') and part['step_label']!=inventory.get('source_solid_label'):
        raise ValueError('manifest STEP label does not match the inspected selected solid')
    if inventory.get('source_solid_count',1)>1 and selected is None:
        raise ValueError('assembly manifest requires an explicitly selected solid')
    matrix,source=_placement(manifest,inventory)
    regions=manifest['regions']
    if not isinstance(regions,dict) or not regions: raise ValueError('interface manifest needs named regions')
    resolved={};evidence={}
    for name,region in regions.items():
        if not isinstance(name,str) or not name.strip(): raise ValueError('interface region name must be nonempty')
        keys(region,['faces','face_count','surface_types','native_selector','rule'],['faces','face_count'],'interface region v2')
        count=region['face_count'];signatures=region['faces']
        if type(count) is not int or count<1: raise ValueError('region face_count must be a positive integer')
        if not isinstance(signatures,list) or len(signatures)!=count:
            raise WorkflowError(f'interface {name} face_count differs from exported signatures','interface_face_count',
                fields=[f'regions.{name}.face_count'],next_action='review_native_selection',
                details={'expected':count,'candidate_faces':signatures})
        kinds=region.get('surface_types',[])
        if not isinstance(kinds,list) or any(not isinstance(k,str) or not k for k in kinds): raise ValueError('surface_types must be a list of type names')
        matches=[];observations=[]
        for signature in signatures:
            keys(signature,['centroid_mm','area_mm2','surface_type','normal_hint','native_face_id'],['centroid_mm','area_mm2'],'face signature v2')
            center=matrix[:3,:3]@np.array(vector(signature['centroid_mm'],'face center'))+matrix[:3,3]
            area=number(signature['area_mm2'],'face area',True)
            allowed=[signature['surface_type']] if signature.get('surface_type') else kinds
            if not allowed: raise ValueError('v2 signature requires surface_type or region.surface_types')
            if kinds and any(k.lower() not in [t.lower() for t in kinds] for k in allowed):
                raise ValueError(f'interface {name} face surface_type contradicts allowed surface_types')
            candidates=[]
            for face in inventory['faces']:
                if face['type'].lower() not in [k.lower() for k in allowed]: continue
                if abs(face['area_mm2']-area)>max(area*1e-5,1e-6): continue
                if signature.get('normal_hint') is not None:
                    normal=np.array(vector(signature['normal_hint'],'normal_hint'))
                    if np.linalg.norm(normal)==0: raise ValueError('normal_hint must be nonzero')
                    if face.get('normal') is not None and np.dot(matrix[:3,:3]@(normal/np.linalg.norm(normal)),face['normal'])<1-1e-6: continue
                candidates.append({'id':face['id'],'distance_mm':float(np.linalg.norm(np.array(face['centroid_mm'])-center)),
                                   'centroid_mm':face['centroid_mm'],'area_mm2':face['area_mm2'],'surface_type':face['type']})
            candidates.sort(key=lambda c:c['distance_mm'])
            near=[c for c in candidates if c['distance_mm']<=1e-3]
            # A tiny absolute floor keeps a zero-distance tie ambiguous too.
            if len(near)!=1 or (len(candidates)>1 and candidates[1]['distance_mm']<10*max(candidates[0]['distance_mm'],1e-10)):
                raise WorkflowError(f'interface {name}: ambiguous_signature; matched {len(near)} whole faces',
                    'ambiguous_signature',fields=[f'regions.{name}.faces'],next_action='review_native_selection',
                    details={'world_centroid_mm':center.tolist(),'candidate_faces':candidates,'selected_solid_id':selected})
            matches.append(near[0]['id']);observations.append(near[0])
        if len(set(matches))!=count: raise ValueError(f'interface {name} has duplicate face signatures')
        if 'rule' in region:
            from .region_rules import select_region
            if sorted(matches)!=select_region(inventory,region['rule']): raise ValueError(f'interface {name} contradicts its region rule')
        resolved[name]=sorted(matches);evidence[name]=observations
    return {'regions':resolved,'frame':manifest['frame'],'placement_source':source,'matrix_4x4':matrix.tolist(),
            'source_solid_id':selected,'source_solid_label':inventory.get('source_solid_label'),
            'matching_evidence':evidence,'warnings':[],**manifest_identity(manifest),
            'meaning':'Exact source hash, selected solid, declared frame and unique centroid/area/type signatures; no face-ID migration.'}


def resolve_interfaces(path,inventory):
    path=Path(path)
    manifest=json.loads(path.read_text(encoding='utf-8-sig'))
    if manifest.get('schema')=='simplecae.interface_manifold/2':
        return dict(_resolve_v2(manifest,inventory),manifest_sha256=sha256(path))
    keys(manifest,['schema_version','generator','generator_version','model_id','revision','parameters','model_path',
                   'model_sha256','package_path','package_sha256','regions','export_report'],
         ['schema_version','generator','model_id','revision','model_sha256','regions'],'interface manifest')
    if manifest['schema_version']!='1.0' or manifest['generator'] not in ('simplecadapi','cadgen','custom'):
        raise ValueError('unsupported interface manifest version or generator')
    if manifest['model_sha256']!=inventory['geometry_sha256']:
        raise ValueError('interface manifest belongs to a different model hash; regenerate from native selections')
    if inventory.get('source_solid_count',inventory.get('solid_count',1))!=1:
        raise ValueError('v1 interface manifest is ambiguous for an assembly; export v2 with an explicit frame and selected part')
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
            'model_id':manifest['model_id'],'revision':manifest['revision'],'frame':'world',
            'warnings':['legacy_interface_world_frame: v1 supports this source-bound single-solid STEP; no migration is required for this binding. For multi-solid or part-local frame handoff, export a v2 native manifest from CAD and run bind-regions --native-manifest.'],
            'meaning':'Native selections rebound by unique centroid/area signatures and exact model hash; face IDs are not inherited across edits.'}
