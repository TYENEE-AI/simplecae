"""Source-bound numerical repair proposals; never mutate a case or start retries."""
from pathlib import Path
import json
import math
from .case import sha256, write_json
from .defaults import DEFAULT_STRUCTURAL_ELEMENTS, DEFAULT_THERMAL_ELEMENTS, PLANNING_HEADROOM


def assembly_cost_coverage(case, result, records, sources):
    sizes=case['mesh']['sizes_mm']; rows=[]
    for body in case.get('bodies', [{'name':'body'}]):
        name=body['name'];factor=body.get('mesh_size_factor',1.);finest=sizes[-1]*factor
        samples=[d['element_count']*(d.get('mesh_size_mm',sizes[0]*factor)/finest)**3
                 for d in records if d.get('geometry_sha256')==sources[name] and d.get('element_count')]
        for level in result.get('levels',[]):
            mesh=level.get('mesh',{}); h=level.get('mesh_size_mm',sizes[-1])
            matched=[b for b in mesh.get('body_reports',[]) if b['name']==name] if case.get('bodies') else [mesh]
            samples.extend(b['element_count']*(h/sizes[-1])**3 for b in matched if b.get('element_count'))
        estimate=max(samples) if samples else None
        rows.append({'body':name,'estimated_finest_elements':estimate,'basis':'Observed cubic extrapolation' if samples else 'unobserved'})
    missing=[r['body'] for r in rows if r['estimated_finest_elements'] is None]
    subtotal=sum(r['estimated_finest_elements'] or 0 for r in rows)
    return {'bodies':rows,'missing_bodies':missing,'observed_subtotal_elements':subtotal,
            'estimated_total_elements':None if missing else subtotal,'planning_headroom':PLANNING_HEADROOM,
            'planning_total_elements':None if missing else math.ceil(subtotal*PLANNING_HEADROOM),
            'estimate_is_guarantee':False,'meaning':'Sum across independently meshed bodies; unknown bodies remain unknown. Sparse/contact memory is not predicted.'}


def advise(case_path, evidence, out):
    from .api import check_case
    from .geometry import session, inventory
    from .execution import cost_projection, hardware_snapshot
    from .sources import SourceGuard, source_paths
    case = check_case(case_path)
    if case['schema_version'] not in ('1.0','2.0','assembly-1.0','thermal-solid-1.0'):
        raise ValueError('mesh advice currently supports structural solids/assemblies and solid thermal cases')
    guard=SourceGuard(source_paths(case) | {Path(case_path).resolve()})
    evidence, out = Path(evidence).resolve(), Path(out).resolve()
    if out.exists(): raise ValueError('advice output must be fresh')
    root = evidence.parent if evidence.is_file() else evidence
    if not root.is_dir(): raise ValueError('evidence directory does not exist')
    result_path = evidence if evidence.is_file() and evidence.name=='result.json' else root/'result.json'
    if result_path.is_file():guard.add([result_path])
    result = json.loads(result_path.read_text(encoding='utf-8')) if result_path.is_file() else {}
    models = [('body',case['model'])] if 'model' in case else [(b['name'],b['model']) for b in case.get('bodies',[])]
    if not models or 'mesh' not in case: raise ValueError('mesh advice requires a solid/assembly case')
    sources = {name:sha256(Path(model['path'])) for name,model in models}
    records=[]
    for pattern in ('mesh-diagnostic.json','resource-diagnostic.json'):
        for path in root.rglob(pattern):
            guard.add([path])
            d=json.loads(path.read_text(encoding='utf-8'))
            if d.get('geometry_sha256') not in sources.values():
                raise ValueError('diagnostic belongs to different CAD; do not apply stale mesh advice')
            records.append(d)
    if result:
        old=result.get('case',{})
        old_models=[old['model']] if 'model' in old else [b['model'] for b in old.get('bodies',[])]
        bound=result.get('source_files_sha256',result.get('source',{}))
        if len(old_models)!=len(models) or any(bound.get(str(Path(m['path']).resolve()))!=sources[n]
                for (n,_),m in zip(models,old_models)):
            raise ValueError('result CAD hashes do not match this case')
    if not records and not result: raise ValueError('no retained result or diagnostic found')
    actions=[];mesh=case['mesh'];sizes=mesh['sizes_mm']
    coverage=assembly_cost_coverage(case,result,records,sources)
    same_contract=False;qualified=False
    if result:
        from .signals import design_signal, structural_contract
        qualified=design_signal(result)['valid_for_comparison']
        if case['schema_version']=='thermal-solid-1.0' and result.get('levels'):
            from .thermal_solid import contract
            expected=contract(case,result['levels'][0].get('realized_inputs',{}))
        else:expected=structural_contract(case)
        same_contract=expected==result.get('task_contract')
    numerical_done=qualified and same_contract
    if not numerical_done:
        for name,model in models:
            relevant=[d for d in records if d.get('geometry_sha256')==sources[name]]
            faces={f['id']:f for d in relevant for f in d.get('adjacent_cad_faces',[]) if f.get('type')!='Plane'}
            body_factor=next((b.get('mesh_size_factor',1.) for b in case.get('bodies',[]) if b['name']==name),1.)
            h=min([d.get('mesh_size_mm',sizes[0]*body_factor) for d in relevant]+[sizes[0]*body_factor])
            location_basis='Curved CAD faces adjacent to rejected elements.'
            if not faces and any(d.get('stage')=='high_order_optimize' and d.get('status')=='rejected' for d in relevant):
                # Positive Jacobians can still fail native distortion targets.
                # An empty invalid-element list must not imply a valid mesh.
                with session(Path(model['path']),model) as g:info=inventory(g,Path(model['path']))
                faces={f['id']:f for f in info['faces'] if f['type']!='Plane'}
                location_basis='Unlocalized native optimizer failure: all curved faces of this bound body are trial candidates, not identified defects.'
            # A nonconverged raw peak locates a neighborhood, not a defect or
            # a strength improvement. Only propose explicit curved-face sizing.
            if not faces and result.get('levels') and len(models)==1:
                v=result.get('assessment',{}).get('verification',{})
                if v.get('small_response_screen_passed') is not False and v.get('mesh_converged') is False:
                    level=result['levels'][-1];point=level.get('results',{}).get('peak_element_centroid_mm')
                    h=level.get('mesh_size_mm',sizes[-1])
                    if point:
                        with session(Path(model['path']),model) as g:info=inventory(g,Path(model['path']))
                        faces={f['id']:f for f in info['faces'] if f['type']!='Plane' and
                               all(f['bbox_mm'][i]-h<=point[i]<=f['bbox_mm'][i+3]+h for i in range(3))}
                        location_basis='Curved CAD faces near a nonconverged raw peak; not a verified geometric defect.'
            if faces:
                extents=[f['bbox_mm'][i+3]-f['bbox_mm'][i] for f in faces.values() for i in range(3)
                         if f['bbox_mm'][i+3]-f['bbox_mm'][i]>h*1e-6]
                target=min(h/2,min(extents)/4) if extents else h/2
                desired_factor=target/h
                # A tiny trimmed face extent is not a license to propose an
                # arbitrarily expensive group-wide refinement. Use observed
                # counts at the requested finest size as a planning bound.
                finest=sizes[-1]*body_factor
                observations=[(d['element_count'],d.get('mesh_size_mm',h)) for d in relevant if d.get('element_count')]
                if len(models)==1:
                    observations += [(level['mesh']['element_count'],level.get('mesh_size_mm',sizes[-1]))
                                     for level in result.get('levels',[]) if level.get('mesh',{}).get('element_count')]
                baseline_count=max((n*(size/finest)**3 for n,size in observations),default=None)
                observed_body=next(r['estimated_finest_elements'] for r in coverage['bodies'] if r['body']==name)
                if observed_body is not None:baseline_count=max(baseline_count or 0,observed_body)
                budget=mesh.get('max_elements',DEFAULT_THERMAL_ELEMENTS if case['schema_version']=='thermal-solid-1.0' else DEFAULT_STRUCTURAL_ELEMENTS)
                other_cost=sum(r['estimated_finest_elements'] or 0 for r in coverage['bodies'] if r['body']!=name)
                available=max(0.,budget-other_cost*PLANNING_HEADROOM)
                budget_floor=(baseline_count*PLANNING_HEADROOM/available)**(1/3) if baseline_count and available else (1. if baseline_count else 0.)
                sizing={'geometry_requested_factor':desired_factor,'observed_finest_element_estimate':baseline_count,
                        'element_budget':budget,'available_after_observed_other_bodies':available,
                        'unobserved_bodies':coverage['missing_bodies'],'budget_limited':budget_floor>desired_factor,
                        'planning_headroom':PLANNING_HEADROOM,
                        'meaning':'Uniform cubic extrapolation with explicit planning headroom, not an upper bound on local meshing or total assembly cost.'}
                if budget_floor>=1:
                    actions.append({'kind':'mesh_budget_conflict','body':name,'sizing_estimate':sizing,
                                    'next_action':'Review mesh allocation or explicitly revise the resource budget before further refinement.'})
                    continue
                target=h*max(desired_factor,budget_floor)
                proposal={'name':'diagnostic_curvature','selector':{'type':'face_ids','ids':sorted(faces),
                    'geometry_sha256':sources[name]},'size_factor':target/h,'distance_mm':max(h,2*target)}
                actions.append({'kind':'local_refinement','body':name,
                    'input_location':'mesh.local_refinements' if len(models)==1 else f'bodies[{name}].local_refinements',
                    'proposed_entry':proposal,'merge_policy':'Merge with existing entries; retain stronger existing sizing. Do not duplicate a name.',
                    'sizing_estimate':sizing,
                    'location_basis':location_basis,
                    'basis':'Located curved faces request h/2 or one quarter of measured face extent. Observed count and the declared element budget limit the proposed first trial; unresolved geometry remains explicit. Not guaranteed convergence.'})
        counts=[d['element_count']*(d.get('mesh_size_mm',sizes[-1]*b.get('mesh_size_factor',1.))/(sizes[-1]*b.get('mesh_size_factor',1.)))**3
                for d in records if d.get('element_count')
                for b in (case.get('bodies') or [{'name':'body'}]) if d.get('geometry_sha256')==sources[b['name']]]
        if counts:
            proposed=math.ceil(max(max(counts),coverage['observed_subtotal_elements'])*PLANNING_HEADROOM)
            if proposed>mesh.get('max_elements',DEFAULT_THERMAL_ELEMENTS if case['schema_version']=='thermal-solid-1.0' else DEFAULT_STRUCTURAL_ELEMENTS):
                actions.append({'kind':'element_budget','proposed_max_elements':proposed,
                    'coverage':coverage,
                    'basis':'Summed observed body counts × cubic size ratio to finest requested mesh × planning headroom. Unknown bodies still need allocation; not a memory guarantee.'})
        fields=[d['field_value_count'] for d in records if d.get('field_value_count')]
        if fields:actions.append({'kind':'field_budget','proposed_max_field_values':math.ceil(max(fields)*PLANNING_HEADROOM),
                                 'basis':'Observed requested field values × planning headroom; retain all requested samples.'})
    levels=result.get('levels',[]);projection=None
    if levels:
        last=levels[-1];m=last.get('mesh',{})
        if m.get('node_count') and m.get('element_count'):
            h=last.get('mesh_size_mm',m.get('mesh_size_mm',sizes[-1]));ratio=max(1.,(h/sizes[-1])**3)
            projected={k:math.ceil(m[k]*ratio) for k in ('node_count','element_count')}
            projection=cost_projection(projected,levels)
    observed=None; profile=root/'execution-observation.json'
    if profile.is_file():
        guard.add([profile]);observed=json.loads(profile.read_text(encoding='utf-8'))
    from .mesh_policy import mesh_policy
    output={'schema_version':'simplecae-advice-1.0','case_path':str(Path(case_path).resolve()),
        'source_bindings':guard.hashes,'model_hashes':sources,'actions':actions,'cost_projection':projection,
        'hardware_observation':hardware_snapshot(),'automatic_retry':False,'input_modified':False,
        'mesh_policy':mesh_policy(case),'assembly_cost_coverage':coverage,
        'execution_observation':observed,
        'same_workload_planning_seconds_range':([observed['total_wall_seconds'],observed['total_wall_seconds']*PLANNING_HEADROOM] if observed else None),
        'evidence_numerically_qualified':qualified,'same_physics_contract':same_contract,
        'next_action':'numerics_resolved_review_design_result' if numerical_done else
                      'review_proposals_then_start_fresh_attempt' if actions else 'inspect_unresolved_evidence_no_automatic_retry',
        'limitations':['Proposals are not numerical acceptance. Keep loads, materials, constraints and accuracy unchanged.',
                       'Native cost_projection excludes meshing/reporting; execution_observation measures those when available. Replay range is planning headroom, not a statistical confidence interval or a changed-mesh runtime guarantee.',
                       'A new local mesh changes element costs; inspect preview and use a finite explicit budget. No unbounded retry loop.']}
    guard.check();write_json(out,output);return output
