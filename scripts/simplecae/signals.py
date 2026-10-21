"""Versioned numerical/design feedback; no reward for incomplete analysis."""
import json
import hashlib
import math
from pathlib import Path
from .case import write_json, CONDITIONS, NOT_ASSESSED


def physical_facts(case, assessment):
    """No missing or empty condition map can establish verified physics."""
    required=list(CONDITIONS)
    if case.get('gravity'):required.remove('self_weight_negligible')
    if case.get('schema_version')=='assembly-1.0':required.append('connection_parameters_verified')
    declared=case.get('conditions',{})
    observed=assessment.get('conditions',{})
    return bool(observed) and all(declared.get(k) is True and observed.get(k) is True for k in required)


def compact_probes(records):
    return [{k:v for k,v in p.items() if k not in ('node_ids','weights','natural_coordinates')} for p in records]


def structural_validity_guidance(result):
    """Explain existing model gates without changing their thresholds or verdict."""
    verification=result.get('assessment',{}).get('verification',{})
    if verification.get('small_response_screen_passed') is False:
        return {'focus':'model_validity','failed_gate':'small_response_screen',
                'evidence':{k:verification[k] for k in ('mesh_converged','force_and_moment_balance_passed',
                    'displacement_to_minimum_extent','small_displacement_ratio_limit','max_strain_norm','strain_norm_limit') if k in verification},
                'message':'线性小响应适用范围未通过；原始位移/应力不能用于定量加厚、承重外推或候选排名。',
                'next_step':'先核对载荷、单位、约束和响应模型；必要时基于独立依据提出新结构假设并重新验证。网格细化本身不能修复小响应超限。',
                'reanalysis_trigger':'after_relevant_model_or_input_change'}
    failed=[]
    for pose in result.get('poses',[]):
        transfer=(pose.get('task_probe_assessment') or {}).get('elastic_transfer') or {}
        if transfer.get('rotation_and_warping_screens_passed') is False:
            failed.append({'pose':pose['name'],
                           'frame_mesh_comparisons':transfer.get('frame_mesh_comparisons',[]),
                           'joint_small_response_passed':transfer.get('joint_compliance',{}).get('small_response_passed')})
    if failed:
        return {'focus':'model_validity','failed_gate':'elastic_transfer_rotation_or_warping',
                'evidence':failed,'message':'整链转角或截面翘曲适用范围未通过；连杆各自通过不能建立整机位移结论。',
                'next_step':'检查累计传递帧、关节保持刚度和截面翘曲。先解决模型适用性，勿仅靠重复细化或自动加厚来授予通过。',
                'reanalysis_trigger':'after_relevant_model_or_input_change'}
    return None


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def structural_contract(case):
    from .region_rules import region_contract
    # Geometry/provenance revisions may change; task physics and validity gates
    # must not. Face-ID hashes intentionally prevent unverified ID rebinding.
    return {key:case.get(key) for key in ('schema_version','material','supports','loads','gravity','criteria','conditions','buckling','load_cases','connections','probes')} | {k:case[k] for k in ('contact_control','bolts','stress_regions') if k in case} | {
        'body_materials':[{k:b.get(k) for k in ('name','material')} for b in case.get('bodies',[])],
        'quality_gates':{k:v for k,v in case.get('mesh',{}).items() if k not in ('sizes_mm','max_elements','local_refinements')},
        'reference_only':case.get('reference_only',False),
        'task_id':case.get('provenance',{}).get('task_id')} | region_contract(case)


def robot_contract(case, robot=None):
    from .case import load_case
    if robot is None:
        from .robot import read_urdf
        robot=read_urdf(case['model']['path'],case['model'].get('package_roots',{}),case.get('massless_links',[]))
    contract={k:case.get(k) for k in ('schema_version','poses','gravity_m_s2','payloads','loads','base','base_pose','conditions','effort_safety_factor','effort_limits','required_components','grasp','probes','actuation_reactions')}
    contract['task_id']=case.get('provenance',{}).get('task_id')
    if 'elastic_transfer' in case:contract['elastic_transfer']=case['elastic_transfer']
    contract['effective_actuator_limits']={name:{'joint_type':j['type'],
        'declared_limit':case.get('effort_limits',{}).get(name,j['effort_limit'])}
        for name,j in sorted(robot['joints'].items()) if j['type']!='fixed' and not j['mimic']}
    covered={c['link'] for c in case.get('components',[])}
    contract['rigid_link_inertials']={name:{'mass_kg':d['mass_kg'],'com_m':list(d['com_m'])}
        for name,d in sorted(robot['links'].items()) if name not in covered}
    contract['components']=[{'link':c['link'],'ports':c['ports'],'link_from_component':c.get('link_from_component'),
                            'mass_relative_tolerance':c.get('mass_relative_tolerance',.02),'com_tolerance_mm':c.get('com_tolerance_mm'),
                            'physics':structural_contract(load_case(Path(c['case_path'])))} for c in case.get('components',[])]
    return contract


def recorded_contract_matches(case,contract,robot=False):
    """Retain the recorded contract hash, but reject contradictory embedded inputs."""
    if not robot:
        try:return contract==structural_contract(case)
        except (ValueError, OSError, KeyError, TypeError):return False
    # Component template physics and URDF-derived ratings are frozen at solve time.
    # Compare the embedded task/ports without re-reading possibly archived templates.
    keys=('schema_version','poses','gravity_m_s2','payloads','loads','base','base_pose',
          'conditions','effort_safety_factor','effort_limits','required_components','grasp','probes','actuation_reactions')
    if any(contract.get(k)!=case.get(k) for k in keys):return False
    if contract.get('elastic_transfer')!=case.get('elastic_transfer'):return False
    if contract.get('task_id')!=case.get('provenance',{}).get('task_id'):return False
    projected=lambda entries:[{k:e.get(k) for k in ('link','ports','link_from_component','com_tolerance_mm')} |
                              {'mass_relative_tolerance':e.get('mass_relative_tolerance',.02)} for e in entries]
    return projected(contract.get('components',[]))==projected(case.get('components',[]))


def design_signal(result):
    if result.get('analysis') in ('fatigue_data', 'creep_data'):
        from .durability import signal as durability_signal
        return durability_signal(result)
    if result.get('analysis')=='motion_loads':
        from .motion import signal as motion_signal
        return motion_signal(result)
    if result.get('analysis')=='modal':
        from .modal import signal as modal_signal
        return modal_signal(result)
    if result.get('analysis')=='thermal_solid':
        from .thermal_solid import signal as thermal_signal
        return thermal_signal(result)
    if result.get('analysis')=='thermal_network':
        from .thermal_network import signal as thermal_signal
        return thermal_signal(result)
    case=result.get('case',{});robot=result.get('analysis')=='urdf_static'
    try:
        contract=result.get('task_contract') or (robot_contract(case) if robot else structural_contract(case))
    except (ValueError,TypeError,OSError,KeyError) as exc:
        contract={'task_id':case.get('provenance',{}).get('task_id'),'unresolved_contract':str(exc)}
    status=result.get('status','invalid');valid=status in ('pass_under_stated_model','fail_under_stated_model')
    valid=valid and 'unresolved_contract' not in contract
    feedback=[];utilizations={};metrics={};coverage={};physical=False;limit=None;criterion_assessments={}
    if contract.get('region_bindings'):
        from .case import sha256
        models=[case['model']] if 'model' in case else [b['model'] for b in case.get('bodies',[])]
        try:
            for model in models:
                if model.get('interface_manifest'):
                    for field in ('path','interface_manifest'):
                        p=Path(model[field]).resolve()
                        if result.get('source_files_sha256',{}).get(str(p))!=sha256(p):
                            raise ValueError('Region source changed since the recorded solve')
        except (OSError,ValueError,KeyError) as exc:
            valid=False;feedback.append({'kind':'evidence_gap','scope':'region_binding','message':str(exc)})
    if result.get('task_contract') and not recorded_contract_matches(case,contract,robot):
        valid=False
        feedback.append({'kind':'evidence_gap','scope':'task_contract',
            'message':'Recorded task contract contradicts the embedded case; do not rank or reuse capacity from this record.'})
    if robot:
        # Older robot records omitted the actual URDF rating thresholds.
        valid=valid and 'effective_actuator_limits' in contract and 'rigid_link_inertials' in contract
        actuator_utilizations=[]
        coverage=result.get('coverage',{})
        physical=all(case.get('conditions',{}).values()) and bool(case.get('conditions'))
        limit=result.get('conditional_payload_limit')
        declared=[p['name'] for p in case.get('poses',[])];observed=[p.get('name') for p in result.get('poses',[])]
        if not declared or sorted(declared)!=sorted(observed):
            valid=False;physical=False
            feedback.append({'kind':'evidence_gap','scope':'pose_coverage','message':'Solved poses do not exactly cover the declared pose list.'})
        for pose in result.get('poses',[]):
            valid=valid and pose['status'] in ('pass_under_stated_model','fail_under_stated_model')
            expected_components=sorted(c['link'] for c in case.get('components',[]))
            actual_components=sorted(c.get('robot_load_transfer',{}).get('link','') for c in pose.get('components',[]))
            if expected_components!=actual_components or set(pose['actuator_efforts'])!=set(contract.get('effective_actuator_limits',{})):
                valid=False;physical=False
                feedback.append({'kind':'evidence_gap','scope':'pose_component_or_actuator_coverage','pose':pose['name'],
                    'message':'Pose evidence does not cover exactly the declared components and independent actuators.'})
            reactions=pose.get('actuation_reaction_assessment')
            if case.get('actuation_reactions'):
                if reactions is None:
                    valid=False;physical=False
                    feedback.append({'kind':'evidence_gap','scope':'actuation_reactions','pose':pose['name'],'message':'Requested reaction path evidence is missing.'})
                else:
                    physical=physical and reactions['declared_paths_verified']
                    metrics.setdefault('actuation_reaction_paths',{})[pose['name']]=reactions
            if reactions and reactions['unrouted_actuators']:
                feedback.append({'kind':'coverage_gap','scope':'actuation_reactions','pose':pose['name'],
                                 'message':'Independent actuator efforts have no declared drive/reaction attachment paths: '+', '.join(reactions['unrouted_actuators'])})
            for name,e in pose['actuator_efforts'].items():
                if e['utilization'] is None or not math.isfinite(e['utilization']) or e['utilization']<0:valid=False
                if e['utilization'] is not None:
                    utilizations[f"{pose['name']}/actuator/{name}"]=e['utilization']
                    actuator_utilizations.append(e['utilization'])
            contact=pose['contact_equilibrium']
            if contact is not None:
                criterion_assessments[f"{pose['name']}/ground_equilibrium"]={
                    'status':'pass_under_stated_model' if contact['feasible'] else 'fail_under_stated_model',
                    'utilization':None, 'feasible':contact['feasible'],
                    'scope':'Declared rigid unilateral point-contact static equilibrium only; no support strength or compliance qualification'}
            if case.get('base',{}).get('type')=='contacts' and contact is None:
                valid=False;physical=False
                feedback.append({'kind':'evidence_gap','scope':'declared_ground_contacts','pose':pose['name'],'message':'Requested ground-contact equilibrium evidence is missing.'})
            grasp=pose.get('grasp_assessment')
            if case.get('grasp') and grasp is None:
                valid=False;physical=False
                feedback.append({'kind':'evidence_gap','scope':'grasp_friction','pose':pose['name'],
                    'message':'Requested grip friction assessment is missing; no favorable comparison margin is available.'})
            if grasp is not None:
                criterion_assessments[f"{pose['name']}/grasp_friction"]={
                    'status':'pass_under_stated_model' if grasp['feasible'] else 'fail_under_stated_model',
                    'utilization':grasp.get('utilization'),'scope':grasp.get('scope')}
                if grasp.get('utilization') is not None and (not math.isfinite(grasp['utilization']) or grasp['utilization']<0):valid=False
                physical=physical and all(grasp['conditions'].values())
                if grasp['utilization'] is not None:utilizations[f"{pose['name']}/grasp_friction"]=grasp['utilization']
                if not grasp['feasible']:
                    feedback.append({'kind':'constraint_failure','scope':'grasp_friction','pose':pose['name'],
                        'available_friction_n':grasp['available_friction_n'],'required_tangential_force_n':grasp['required_tangential_force_n'],
                        'message':'Declared finite pads cannot balance the workpiece force/moment demand.' if grasp.get('model')=='finite_pad_wrench' else 'Declared grip friction cannot resist the workpiece tangential demand, even if actuator and part criteria pass.',
                        'suggestion':'Verify contact surfaces and measured friction, increase controlled normal force within real actuator/object/structure limits, or use a form-fitting grasp; reanalyze.'})
            if contact is not None and not contact['feasible']:
                feedback.append({'kind':'constraint_failure','scope':'declared_ground_contacts','pose':pose['name'],
                                 'message':'Current support points/friction cannot balance the external wrench.',
                                 'suggestion':'Consider moving the center of mass, widening the support, changing the pose or reducing payload; recalculate all criteria.'})
            for component in pose.get('components',[]):
                child=design_signal(component)
                for n,u in child['utilizations'].items():utilizations[f"{pose['name']}/{component['robot_load_transfer']['link']}/{n}"]=u
                if not child['valid_for_comparison']:valid=False
                physical=physical and child['physical_conditions_verified']
                for name,e in child.get('criterion_assessments',{}).items():
                    criterion_assessments[f"{pose['name']}/{component['robot_load_transfer']['link']}/{name}"]=e
            task_probes=pose.get('task_probe_assessment')
            if case.get('probes') and task_probes is None:valid=False
            if task_probes:
                coverage=dict(coverage,displacement_scope=task_probes.get('measurement_scope','independent_component_fields'),whole_robot_displacement_available=False)
                expected_probes=sorted(p['name'] for p in case.get('probes',[]))
                observed_probes=sorted(p['name'] for p in task_probes.get('probes',[]))
                from .joint_compliance import enabled as joint_compliance_enabled,evidence_matches
                expected_scope='first_order_link_and_joint_compliance' if joint_compliance_enabled(case) else 'first_order_section_frames' if case.get('elastic_transfer') else 'independent_component_fields'
                if expected_probes!=observed_probes or task_probes.get('measurement_scope','independent_component_fields')!=expected_scope:
                    valid=False
                    feedback.append({'kind':'evidence_gap','scope':'task_probe_coverage','message':'Requested task probe names and displacement model scope must exactly match the solved evidence.'})
                if case.get('elastic_transfer') and not case['elastic_transfer']['joints_locked_verified']:physical=False
                if case.get('elastic_transfer'):
                    e=task_probes.get('elastic_transfer') or {}
                    if task_probes.get('measurement_scope')!=expected_scope or not e.get('rotation_and_warping_screens_passed') or len(e.get('frame_mesh_comparisons',[]))<2 or not all(e['frame_mesh_comparisons'][-2:]):
                        valid=False
                        feedback.append({'kind':'evidence_gap','scope':'elastic_transfer','message':'Requested section-frame transfer has no complete qualified frame/rotation/warping evidence.'})
                    if joint_compliance_enabled(case):
                        if not evidence_matches(case,e.get('joint_compliance')):
                            valid=False
                            feedback.append({'kind':'evidence_gap','scope':'joint_compliance','message':'Requested joint springs lack complete consistent fixed/full response evidence.'})
                        if not all(s['verified'] for s in case['elastic_transfer']['joint_compliance'].values()):physical=False
                valid=valid and task_probes['status'] in ('pass_under_stated_model','fail_under_stated_model')
                metrics.setdefault('pose_probes',{})[pose['name']]=task_probes['probes']
                for name,e in task_probes['criterion_assessments'].items():
                    criterion_assessments[f"{pose['name']}/{name}"]=e
                    if e['utilization'] is not None:utilizations[f"{pose['name']}/{name}"]=e['utilization']
        metrics['max_actuator_utilization']=max(actuator_utilizations) if actuator_utilizations else None
    elif result.get('analysis')=='load_case_envelope':
        entries=result.get('cases',[])
        valid=valid and bool(entries);physical=bool(entries)
        coverage={'alternative_load_cases':[e['name'] for e in entries]}
        declared=[e['name'] for e in case.get('load_cases',[])]
        observed=[e['name'] for e in entries]
        if declared and sorted(declared)!=sorted(observed):
            valid=False;physical=False
            feedback.append({'kind':'evidence_gap','scope':'load_case_coverage','message':'Solved alternatives do not exactly cover the declared load-case list.'})
        for e in entries:
            child_case=dict(e.get('case') or case)
            child_case.pop('load_cases',None)
            for spec in case.get('load_cases',[]):
                if spec['name']==e['name']:
                    child_case['loads']=spec['loads']
                    if 'gravity' in spec:child_case['gravity']=spec['gravity']
            child=design_signal({'analysis':'linear_static','case':child_case,
                'status':e['status'],'assessment':e.get('assessment') or {}})
            valid=valid and child['valid_for_comparison']
            physical=physical and child['physical_conditions_verified']
            for name,u in child['utilizations'].items():utilizations[f"{e['name']}/{name}"]=u
            for item in child['feedback']:
                feedback.append(dict(item,load_case=e['name']))
            for name,v in child.get('criterion_assessments',{}).items():criterion_assessments[f"{e['name']}/{name}"]=v
        limit={'available':result.get('common_payload_scale_limit') is not None,'scale_factor':result.get('common_payload_scale_limit')}
    else:
        assessment=result.get('assessment',{})
        verification=assessment.get('verification',{})
        valid=valid and assessment.get('status')==status and all(verification.get(k) is True for k in ('force_and_moment_balance_passed','mesh_converged','small_response_screen_passed'))
        if case.get('stress_regions'):
            names={r['name'] for r in case['stress_regions']}
            region_pairs=verification.get('stress_region_mesh_comparisons',[])
            valid=valid and verification.get('stress_regions_converged') is True and len(region_pairs)>=2 and all(
                set(pair)==names and all(item.get('converged') is True for item in pair.values()) for pair in region_pairs[-2:])
        for name,key in [('strength','strength_utilization'),('stiffness','stiffness_utilization')]:
            u=assessment.get(key)
            if u is None or not math.isfinite(u) or u<0:valid=False
            else:utilizations[name]=u
        if assessment.get('buckling',{}):
            b=assessment['buckling'].get('reference_utilization')
            usable=b is not None and math.isfinite(b) and b>=0
            if usable:utilizations['elastic_buckling']=b
            valid=valid and assessment['buckling'].get('mesh_converged') is True and usable
        elif case.get('buckling',{}).get('enabled'):valid=False
        physical=physical_facts(case,assessment)
        limit=assessment.get('conditional_body_limit')
        if result.get('levels'):
            level=result['levels'][-1];r=level['results']
            metrics={k:r[k] for k in ('max_displacement_mm','max_von_mises_mpa','force_balance_relative_error','moment_balance_relative_error')}
            metrics['material_volume_mm3']=level['mesh']['mesh_volume_mm3'];metrics['modeled_mass_kg']=level['mesh'].get('mass_kg')
            for key in ('max_displacement_node','max_displacement_location_mm','max_displacement_vector_mm'):
                if key in r:metrics[key]=r[key]
            if r.get('probes'):metrics['probes']=compact_probes(r['probes'])
            metrics['strength_peak']=r.get('strength_peak')
            metrics['peak_element_centroid_mm']=r.get('peak_element_centroid_mm')
            coverage={'body_count':level['mesh'].get('geometry',{}).get('solid_count',len(case.get('bodies',[])) or 1),'failure_criteria':assessment.get('failure_criteria'),
                      'gravity_modeled':bool(case.get('gravity')),'elastic_buckling_requested':bool(case.get('buckling',{}).get('enabled'))}
            for m in level['mesh'].get('materials',{'BODY':case.get('material',{})}).values():
                if m.get('failure_criterion')=='max_stress' and not m.get('calibration'):physical=False
            if any(j['type']=='linear_interface' and not j.get('calibration') for j in case.get('connections',[])):physical=False
            if utilizations.get('strength',0)>1:
                peak=r.get('strength_peak') or {}
                qualified=status!='invalid' and assessment.get('criterion_assessments',{}).get('strength',{}).get('status')=='fail_under_stated_model' and verification.get('small_response_screen_passed') is True and verification.get('force_and_moment_balance_passed') is True
                feedback.append({'kind':'constraint_failure' if qualified else 'raw_exceedance','scope':'body_strength','location_mm':peak.get('element_centroid_mm',r['peak_element_centroid_mm']),
                                 'failure_criterion':peak.get('failure_criterion'),'material_id':peak.get('material_id'),'component':peak.get('component'),
                                 'location_meaning':'centroid of peak-stress element, not exact integration point',
                                 'message':'Converged peak integration-point strength utilization exceeds the stated allowable.' if qualified else 'Unqualified raw strength utilization exceeds the allowable; establish local/global convergence and model validity before concluding that the geometry is too weak.',
                                 'suggestion':'Inspect the located section, actual transition radius and load-spreading area; change permitted geometry and reanalyze with the same required loads, material, mounting and criteria.' if qualified else 'Inspect mesh quality, support/load transitions and raw hotspot evidence; do not reduce required loads, discard peaks or prescribe a strength improvement from an unresolved stress field.'})
            for probe in r.get('probes',[]):
                if probe.get('utilization') is not None and probe['utilization']>1:
                    qualified=status!='invalid' and assessment.get('criterion_assessments',{}).get('probe:'+probe['name'],{}).get('status')=='fail_under_stated_model' and verification.get('small_response_screen_passed') is True and verification.get('force_and_moment_balance_passed') is True
                    item={'kind':'design_guidance' if qualified else 'raw_exceedance','scope':'probe:'+probe['name'],
                        'point_mm':probe.get('point_mm'),'from_point_mm':probe.get('from_point_mm'),'to_point_mm':probe.get('to_point_mm'),
                        'displacement_vector_mm':probe['displacement_vector_mm'],'actual_displacement_mm':probe['value_mm'],
                        'allowed_displacement_mm':probe['allowable_displacement_mm'],
                        'message':'The named task displacement exceeds its explicit limit; this quantity is distinct from the global maximum.' if qualified else 'Unqualified raw task displacement exceeds the limit; establish numerical/model validity before a quantitative design change.',
                        'suggestion':'Inspect the declared task point, section and load path; relative measurements cover modeled elastic bodies only, not omitted connection or pad compliance.' if qualified else 'Review failed model and numerical gates; no stiffness multiplier is qualified.'}
                    if qualified:item['required_stiffness_multiplier']=probe['utilization']
                    feedback.append(item)
            global_allow=case.get('criteria',{}).get('max_displacement_mm')
            if global_allow and r['max_displacement_mm']/global_allow>1:
                qualified=status!='invalid' and assessment.get('criterion_assessments',{}).get('stiffness',{}).get('status')=='fail_under_stated_model' and verification.get('small_response_screen_passed') is True and verification.get('force_and_moment_balance_passed') is True
                item={'kind':'design_guidance' if qualified else 'raw_exceedance','scope':'stiffness','location_mm':r.get('max_displacement_location_mm'),
                    'node':r.get('max_displacement_node'),'displacement_vector_mm':r.get('max_displacement_vector_mm'),
                    'actual_displacement_mm':r['max_displacement_mm'],'allowed_displacement_mm':case['criteria']['max_displacement_mm'],
                    'message':'Maximum modeled displacement exceeds the functional limit at this node.' if qualified else 'Unqualified raw maximum displacement exceeds the limit; it is not a verified design failure.',
                    'suggestion':'Inspect displacement direction, bending length, section depth and connection compliance. For an approximately constant-section cantilever only, t_new/t_old is about utilization^(1/3); this is a hypothesis requiring fresh analysis.' if qualified else 'Review failed model and numerical gates; no thickness or stiffness multiplier is qualified.'}
                if qualified:item['required_stiffness_multiplier']=r['max_displacement_mm']/global_allow
                feedback.append(item)
        for reason in (limit or {}).get('withheld_reasons',[]):
            feedback.append({'kind':'evidence_gap','message':reason})
    from .stress_regions import unresolved_findings
    feedback.extend(unresolved_findings(result))
    children=result.get('poses',[]) if robot else result.get('cases',[]) if result.get('analysis')=='load_case_envelope' else []
    if children:
        order={'pass_under_stated_model':0,'fail_under_stated_model':1,'indeterminate':2,'invalid':3}
        expected=max((p.get('status','invalid') for p in children),key=lambda s:order.get(s,3))
        if status!=expected:
            valid=False
            feedback.append({'kind':'evidence_gap','scope':'aggregate_status','message':'Aggregate status contradicts its constituent results.'})
    for name,u in utilizations.items():
        if u>1:feedback.append({'kind':'constraint_failure' if valid else 'raw_exceedance','scope':name,'utilization':u,
            'message':'Exceeded the stated model criterion.' if valid else 'Raw response exceeds the limit; numerical validity remains unresolved.'})
    if result.get('assessment'):criterion_assessments=result['assessment'].get('criterion_assessments',{})
    for name,e in criterion_assessments.items():
        if name.startswith(('preload:','locked:','bolt:','contact_motion:')) and e.get('utilization') is not None:utilizations[name]=e['utilization']
    if status=='invalid':criterion_assessments={name:dict(e,status='invalid') for name,e in criterion_assessments.items()}
    for name,evidence in criterion_assessments.items():
        if evidence['status']=='fail_under_stated_model':
            feedback.append({'kind':'confirmed_criterion_failure','scope':name,
                'utilization':evidence['utilization'],
                'message':'This criterion has converged and fails; other unresolved criteria do not remove this finding. Aggregate comparison and capacity gates still apply.'})
    if not valid:
        feedback.insert(0,{'kind':'invalid_or_unresolved_analysis','message':result.get('error') or 'Resolve missing criteria, convergence or validity gates before ranking this candidate.'})
        if guidance:=structural_validity_guidance(result):
            feedback.insert(1,dict(kind='model_applicability',**guidance))
        if limit:
            limit=dict(limit,available=False,withheld_reasons=list(limit.get('withheld_reasons',[]))+['Analysis or task evidence is invalid/unresolved; no conditional capacity is usable.'])
            for key in ('load_pattern_scale_factor','scale_factor','vertical_payload_mass_equivalent_kg',
                        'scaled_loads_n','governing_limit','predicted_response_screen'):
                if key in limit:limit[key]=None
    declared_materials=[case.get('material',{})]+[body.get('material',{}) for body in case.get('bodies',[])]
    from .contact import enabled as has_contact
    if has_contact(case):
        from .contact import stage_names
        expected={j['name'] for j in case['connections'] if j['type'] in ('frictionless_contact','frictional_contact')}
        stages=len(stage_names(case))
        advanced=bool(case.get('bolts')) or any(j['type']=='frictional_contact' for j in case['connections'])
        complete=result.get('analysis')==('staged_contact_assembly' if advanced else 'frictionless_contact_assembly') and len(result.get('levels',[]))>=3
        if advanced:
            service=result.get('stage_assessments',{}).get('service',{});gates=service.get('verification',{})
            complete=complete and all(gates.get(k) is True for k in ('mesh_converged','force_and_moment_balance_passed','small_response_screen_passed'))
            complete=complete and all(k in criterion_assessments for k in service.get('criterion_assessments',{}))
        for level in result.get('levels',[]):
            steps=level.get('solver',{}).get('completed_load_steps',{})
            outputs=level.get('results',{}).get('contact',[])
            complete=complete and set(map(int,steps))==set(range(1,stages+1)) and all(abs(s.get('step_time',0)-1)<1e-7 for s in steps.values())
            complete=complete and {p['name'] for p in outputs}==expected and all(p.get('available') for p in outputs)
            if advanced:complete=complete and all(p.get('output_coverage_verified') is True for p in outputs)
            for spec in case['connections']:
                if spec['type']!='frictional_contact':continue
                p=next((v for v in outputs if v['name']==spec['name']),{})
                complete=complete and all(k in p for k in ('peak_tangential_displacement_mm','peak_shear_mpa','sliding_sample_count','coulomb_bound_passed','small_sliding_screen_passed'))
                complete=complete and p.get('coulomb_bound_passed') is True and p.get('small_sliding_screen_passed') is True
                complete=complete and 'contact_motion:'+spec['name'] in criterion_assessments
            if case.get('bolts'):
                bolts=level['results'].get('bolts',[])
                complete=complete and {b['name'] for b in bolts}=={b['name'] for b in case['bolts']} and all(b.get('locked') is True and b.get('axis_screen_passed') is True and b.get('lock_error_mm') is not None and b['lock_error_mm']<=max(1e-9,abs(b['adjustment_mm'])*1e-7) for b in bolts)
                complete=complete and all('bolt:'+b['name'] in criterion_assessments for b in case['bolts'])
        if stages>=2:
            preload=result.get('preload_assessment') or {};gates=preload.get('verification',{})
            complete=complete and all(gates.get(k) is True for k in ('mesh_converged','force_and_moment_balance_passed','small_response_screen_passed'))
            complete=complete and all('preload:'+k in criterion_assessments for k in preload.get('criterion_assessments',{}))
            order={'pass_under_stated_model':0,'fail_under_stated_model':1,'indeterminate':2,'invalid':3}
            complete=complete and order.get(status,3)>=order.get(preload.get('status'),3)
            if case.get('bolts'):
                locked=result.get('stage_assessments',{}).get('locked',{});gates=locked.get('verification',{})
                complete=complete and all(gates.get(k) is True for k in ('mesh_converged','force_and_moment_balance_passed','small_response_screen_passed'))
                complete=complete and order.get(status,3)>=order.get(locked.get('status'),3)
                complete=complete and all('locked:'+k in criterion_assessments for k in locked.get('criterion_assessments',{}))
        if not complete:
            valid=False
            failed_stage_gates = [
                f"{name}/{gate}"
                for name, stage in result.get('stage_assessments', {}).items()
                for gate in ('mesh_converged', 'force_and_moment_balance_passed', 'small_response_screen_passed')
                if stage.get('verification', {}).get(gate) is not True]
            feedback.append({'kind':'evidence_gap','scope':'contact_history',
                'failed_stage_gates':failed_stage_gates,
                'message':'Contact-history qualification is incomplete: it requires both complete stage outputs '
                          'and valid mesh, equilibrium, contact-law and locking checks. '
                          + ('Recorded unresolved stage gates: '+', '.join(failed_stage_gates)+'. '
                             'This does not imply that native load steps were missing.' if failed_stage_gates
                             else 'Inspect stage endpoints, contact/bolt coverage and their validity checks; '
                                  'a service-only or linear result cannot substitute for the declared history.')})
    if (has_contact(case) or case.get('elastic_transfer')) and limit and limit.get('available'):
        valid=False
        feedback.append({'kind':'evidence_gap','scope':'capacity','message':'Automatic capacity extrapolation is not qualified for this contact/section-transfer mode.'})
    # Mechanics coverage gates above can invalidate an otherwise plausible raw
    # record too. Keep all public capacity values withheld in that situation.
    if not valid and limit:
        limit=dict(limit,available=False)
        for key in ('load_pattern_scale_factor','scale_factor','vertical_payload_mass_equivalent_kg','scaled_loads_n','governing_limit','predicted_response_screen'):
            if key in limit:limit[key]=None
    if any(m.get('calibration',{}).get('kind')=='mathematical_reference' for m in declared_materials):physical=False
    if any(m.get('failure_criterion')=='max_stress' and not m.get('calibration') for m in declared_materials):physical=False
    if any(j['type'] in ('linear_interface','frictionless_contact','frictional_contact') and not j.get('calibration') for j in case.get('connections',[])):physical=False
    worst=max(utilizations.values()) if utilizations else None
    # A contact failure has no scalar stress utilization. Do not report a
    # favorable scalar bottleneck margin in that case, even if motors pass.
    margin=1/worst if valid and worst is not None and worst>0 and not any(f.get('scope')=='declared_ground_contacts' for f in feedback) else None
    if status=='fail_under_stated_model' and margin is not None and margin>1:
        margin=None
    from .hotspot import mesh_sensitivity
    hotspot=mesh_sensitivity(result)
    if hotspot:feedback.append(hotspot)
    return {'schema_version':'simplecae-signal-1.0','analysis_status':status,'valid_for_comparison':valid,
            'feasible_under_stated_model':status=='pass_under_stated_model' if valid else None,
            'physical_conditions_verified':bool(physical),'whole_installation_rating_available':False,
            'task_contract_sha256':digest(contract),'task_id':contract.get('task_id'),
            'candidate':case.get('provenance',{}),'utilizations':utilizations,'bottleneck_margin':margin,
            'metrics':metrics,'coverage':coverage,'conditional_limit':limit,'feedback':feedback,
            'criterion_assessments':criterion_assessments,
            'not_assessed':result.get('assessment',{}).get('not_assessed') or result.get('not_assessed') or NOT_ASSESSED,
            'score_meaning':'Raw model margin only when valid; physical conditions and unassessed scope remain separate. No automatic installation rating or universal reward.'}


def attach_signal(result,out):
    signal=design_signal(result);result['evaluation_signal']=signal
    write_json(Path(out)/'signal.json',signal)
    return signal


def compare_results(paths):
    records=[];legacy_robot=False
    for path in paths:
        result=json.loads(Path(path).read_text(encoding='utf-8-sig'));signal=design_signal(result)
        if result.get('analysis')=='urdf_static' and 'rigid_link_inertials' not in (result.get('task_contract') or {}):legacy_robot=True
        records.append({'result_path':str(Path(path).resolve()),'signal':signal})
    if len(records)<2:raise ValueError('comparison needs at least two results')
    signals=[r['signal'] for r in records]
    reasons=[]
    if legacy_robot:reasons.append('legacy robot evidence has no frozen rigid-link mass/COM; rerun before ranking')
    if any(not s['valid_for_comparison'] for s in signals):reasons.append('at least one candidate has invalid/unresolved analysis')
    if any(not s['task_id'] for s in signals):reasons.append('explicit shared provenance.task_id is required')
    if len({s['task_contract_sha256'] for s in signals})!=1:reasons.append('task material, load/support/pose, criteria or validity contract differs')
    return {'schema_version':'simplecae-comparison-1.0','comparable':not reasons,'withheld_reasons':reasons,'candidates':records,
            'meaning':'Compare raw metrics/margins for a shared task contract; the generation engine chooses its objectives and edits.'}
