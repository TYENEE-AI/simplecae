"""Conditional body-only limits. No whole-installation working load is certified."""
from __future__ import annotations

from .case import NOT_ASSESSED, CONDITIONS
import numpy as np


def field_metrics(full, fixed, factor):
    stress = np.array([full["stresses"][k]-(fixed["stresses"][k] if fixed else 0) for k in full["stresses"]])
    strains = np.array([full["strains"][k]-(fixed["strains"][k] if fixed else 0) for k in full["strains"]])
    u = np.array([full["displacements"][k]-(fixed["displacements"][k] if fixed else 0) for k in full["displacements"]])
    stress *= factor
    strains *= factor
    u *= factor
    if fixed:
        stress += np.array([fixed["stresses"][k] for k in full["stresses"]])
        strains += np.array([fixed["strains"][k] for k in full["strains"]])
        u += np.array([fixed["displacements"][k] for k in full["displacements"]])
    vm = np.sqrt(.5*((stress[:,0]-stress[:,1])**2+(stress[:,1]-stress[:,2])**2+(stress[:,2]-stress[:,0])**2)+3*np.sum(stress[:,3:]**2,axis=1))
    strain_norm = np.sqrt(np.sum(strains[:,:3]**2,axis=1)+2*np.sum(strains[:,3:]**2,axis=1))
    result={"max_von_mises_mpa":float(vm.max()), "max_displacement_mm":float(np.max(np.linalg.norm(u,axis=1))),
            "max_strain_norm":float(strain_norm.max())}
    if full.get('_strength_context'):
        from .materials import strength_summary
        result.update(strength_summary(stress,list(full['stresses']),full['_strength_context']))
    if full.get('_probe_context'):
        from .probes import scaled_probes
        result['probes']=scaled_probes(full,fixed,factor)
    if full.get('_stress_region_context'):
        from .stress_regions import summarize_regions
        result['stress_regions']=summarize_regions(stress,list(full['stresses']),full['_strength_context'],full['_stress_region_context'])
    return result


def fixed_load_limit(full,fixed,sigma_allow,disp_allow):
    def utilization(a):
        r=field_metrics(full,fixed,a)
        strength=r.get('strength_utilization') if 'strength_utilization' in r else r["max_von_mises_mpa"]/sigma_allow
        from .probes import stiffness_utilization
        return max(strength,stiffness_utilization(r,disp_allow))
    if utilization(0)>1:
        return None,"fixed loads alone exceed the body criteria"
    low,high=0.,1.
    while utilization(high)<=1 and high<1e6:
        low,high=high,high*2
    if utilization(high)<=1:
        return None,"no finite payload limit found within the supported scale range"
    for _ in range(60):
        mid=(low+high)/2
        if utilization(mid)<=1:
            low=mid
        else:
            high=mid
    r=field_metrics(full,fixed,low)
    strength=r.get('strength_utilization') if 'strength_utilization' in r else r["max_von_mises_mpa"]/sigma_allow
    from .probes import stiffness_utilization
    governing="strength" if strength >= stiffness_utilization(r,disp_allow) else "stiffness"
    return low,governing


def assess(c, levels, field_components=None, *, predict_capacity=True):
    if not levels:
        raise ValueError("assessment requires solved levels")
    from .materials import primary_material
    cr, m = c["criteria"], primary_material(c)
    rt = levels[-1]["results"]
    du = c["mesh"].get("displacement_relative_tolerance", .05)
    ds = c["mesh"].get("stress_relative_tolerance", .10)
    balance_tol = c["mesh"].get("balance_relative_tolerance", 5e-4)
    pairs = []
    from .probes import convergence,stiffness_utilization
    required_probes={p['name'] for p in c.get('probes',[]) if p.get('max_displacement_mm') or p.get('convergence_required')}
    for p in c.get('probes',[]):
        if p['type']=='relative' and p['name'] in required_probes:required_probes.update([p['from_probe'],p['to_probe']])
    expected_probes={p['name'] for p in c.get('probes',[])}
    if any({p['name'] for p in level['results'].get('probes',[])}!=expected_probes for level in levels):
        raise ValueError('solved named probe coverage does not match this case')
    for a, b in zip(levels, levels[1:]):
        previous, current = a["results"], b["results"]
        u = abs(current["max_displacement_mm"]-previous["max_displacement_mm"])/max(current["max_displacement_mm"], 1e-30)
        s = abs(current["max_von_mises_mpa"]-previous["max_von_mises_mpa"])/max(current["max_von_mises_mpa"], 1e-30)
        strength_change=abs(current['strength_utilization']-previous['strength_utilization'])/max(current['strength_utilization'],1e-30) if current.get('strength_utilization') is not None and previous.get('strength_utilization') is not None else None
        pairs.append({"displacement_relative_change": u, "stress_relative_change": s,
                      "strength_utilization_relative_change":strength_change,
                      "displacement_converged": u <= du, "stress_converged": s <= ds and (strength_change is None or strength_change<=ds),
                      "probes":convergence(previous.get('probes',[]),current.get('probes',[]),du)})
    converged = len(pairs) >= 2 and all(p["displacement_converged"] and p["stress_converged"] for p in pairs[-2:])
    probes_converged=len(pairs)>=2 and all(p['probes'][name]['converged'] for p in pairs[-2:] for name in required_probes)
    converged=converged and probes_converged
    from .stress_regions import compare_regions
    region_names={r['name'] for r in c.get('stress_regions',[])}
    region_pairs=[compare_regions(a['results'].get('stress_regions',[]),b['results'].get('stress_regions',[]),region_names,ds) for a,b in zip(levels,levels[1:])]
    regions_converged=not region_names or (len(region_pairs)>=2 and all(v['converged'] for pair in region_pairs[-2:] for v in pair.values()))
    converged=converged and regions_converged
    from .contact import enabled as has_contact
    contact=has_contact(c);contact_pairs=[]
    if contact:
        expected={s['name'] for s in c['connections'] if s['type'] in ('frictionless_contact','frictional_contact')}
        for a,b in zip(levels,levels[1:]):
            old={p['name']:p for p in a['results'].get('contact',[])};new={p['name']:p for p in b['results'].get('contact',[])}
            ok=set(old)==set(new)==expected and all(p['available'] for p in list(old.values())+list(new.values()))
            changes={}
            if ok:
                for name,p in new.items():
                    pressure=abs(p['peak_pressure_mpa']-old[name]['peak_pressure_mpa'])/max(p['peak_pressure_mpa'],old[name]['peak_pressure_mpa'],1e-8)
                    gap=abs(p['minimum_gap_mm']-old[name]['minimum_gap_mm'])
                    gap_tolerance=next(s.get('gap_convergence_tolerance_mm',1e-5) for s in c['connections'] if s['name']==name)
                    changes[name]={'pressure_relative_change':pressure,'minimum_gap_change_mm':gap,'gap_absolute_tolerance_mm':gap_tolerance,
                                   'converged':pressure<=ds and gap<=gap_tolerance}
                    spec=next(s for s in c['connections'] if s['name']==name)
                    if spec['type']=='frictional_contact':
                        from .contact import STRESS_RESOLUTION_MPA
                        slip=abs(p.get('peak_tangential_displacement_mm',float('inf'))-old[name].get('peak_tangential_displacement_mm',float('inf')))
                        tolerance=spec.get('slip_convergence_tolerance_mm',1e-5)
                        shear=abs(p.get('peak_shear_mpa',float('inf'))-old[name].get('peak_shear_mpa',float('inf')))/max(p.get('peak_shear_mpa',0),old[name].get('peak_shear_mpa',0),1e-8)
                        near_zero=max(p.get('peak_shear_mpa',float('inf')),old[name].get('peak_shear_mpa',float('inf')))<=STRESS_RESOLUTION_MPA
                        changes[name].update(tangential_displacement_change_mm=slip,tangential_absolute_tolerance_mm=tolerance,shear_relative_change=shear,
                                             shear_both_below_native_resolution=near_zero,shear_native_resolution_mpa=STRESS_RESOLUTION_MPA)
                        changes[name]['converged']=changes[name]['converged'] and slip<=tolerance and (shear<=ds or near_zero)
                ok=all(p['converged'] for p in changes.values())
            contact_pairs.append({'converged':bool(ok),'contacts':changes})
        contact_converged=len(contact_pairs)>=2 and all(p['converged'] for p in contact_pairs[-2:])
        converged=converged and contact_converged
    balance_ok = all(max(l["results"]["force_balance_relative_error"], l["results"]["moment_balance_relative_error"]) <= balance_tol for l in levels)
    small_u_limit = cr.get("max_small_displacement_ratio", .05)
    strain_limit = cr.get("max_strain_norm", .01)
    small_u = rt.get('deformation_displacement_mm',rt["max_displacement_mm"]) / rt["minimum_bbox_extent_mm"]
    linear_screen = small_u <= small_u_limit and rt["max_strain_norm"] <= strain_limit
    bolt_comparisons=[]
    if c.get('bolts'):
        expected={b['name'] for b in c['bolts']}
        for a,b in zip(levels,levels[1:]):
            old={r['name']:r for r in a['results'].get('bolts',[])};new={r['name']:r for r in b['results'].get('bolts',[])}
            if set(old)!=expected or set(new)!=expected:raise ValueError('incomplete bolt state coverage')
            changes={n:abs(new[n]['force_n']-old[n]['force_n'])/max(abs(new[n]['force_n']),1e-8) for n in expected}
            bolt_comparisons.append({'force_relative_changes':changes,'converged':all(v<=min(du,ds) for v in changes.values())})
        bolt_converged=len(bolt_comparisons)>=2 and all(p['converged'] for p in bolt_comparisons[-2:])
        converged=converged and bolt_converged
        linear_screen=linear_screen and all(b.get('axis_screen_passed') is True for l in levels for b in l['results'].get('bolts',[]))
    if contact:
        linear_screen=linear_screen and all(p.get('small_sliding_screen_passed') is True and p.get('coulomb_bound_passed') is True
            for l in levels for p in l['results'].get('contact',[]) if next(j for j in c['connections'] if j['name']==p['name'])['type']=='frictional_contact')
    safety=cr.get('strength_safety_factor',cr.get('yield_safety_factor'))
    sigma_allow = (m["yield_strength_mpa"] / safety
                   if m.get("yield_strength_mpa") and safety and m.get("failure_criterion") == "von_mises_yield" else None)
    strength_ratio = rt['strength_utilization'] if 'strength_utilization' in rt else rt["max_von_mises_mpa"]/sigma_allow if sigma_allow else None
    disp_allow = cr.get("max_displacement_mm")
    stiffness_ratio = stiffness_utilization(rt,disp_allow)
    def criterion_state(utilization, mesh_ok, applicable=True):
        if not balance_ok:
            state='invalid'
        elif not applicable or utilization is None or not mesh_ok or not linear_screen:
            state='indeterminate'
        else:
            state='fail_under_stated_model' if utilization>1 else 'pass_under_stated_model'
        return {'status':state,'utilization':utilization,'mesh_converged':mesh_ok,
                'equilibrium_passed':balance_ok,'small_response_screen_passed':linear_screen,
                'physical_verification_separate':True}
    displacement_converged=len(pairs)>=2 and all(p['displacement_converged'] for p in pairs[-2:])
    stress_converged=len(pairs)>=2 and all(p['stress_converged'] for p in pairs[-2:]) and regions_converged
    criteria_evidence={'strength':criterion_state(strength_ratio,stress_converged),
                       'stiffness':criterion_state(stiffness_ratio,(displacement_converged or disp_allow is None) and probes_converged)}
    if c.get('bolts'):
        for b in rt['bolts']:criteria_evidence['bolt:'+b['name']]=criterion_state(b['utilization'],bolt_converged)
    if contact:
        for p in rt.get('contact',[]):
            spec=next(j for j in c['connections'] if j['name']==p['name'])
            if spec['type']=='frictional_contact':
                criteria_evidence['contact_motion:'+p['name']]=criterion_state(p.get('peak_tangential_displacement_mm',0.)/spec['max_tangential_displacement_mm'] if p.get('available') else None,contact_converged)
    for probe in rt.get('probes',[]):
        if probe['utilization'] is None:continue
        probe_ok=len(pairs)>=2 and all(p['probes'][probe['name']]['converged'] for p in pairs[-2:])
        criteria_evidence['probe:'+probe['name']]=criterion_state(probe['utilization'],probe_ok)
    reasons = []
    if not balance_ok:
        reasons.append("force/moment equilibrium did not pass")
    if not converged:
        reasons.append("two consecutive refined mesh comparisons have not converged; peak stress may be singular")
    if not regions_converged:
        reasons.append("declared local stress regions have not converged; inspect their located raw peaks before changing CAD")
    if not linear_screen:
        reasons.append("small-displacement/strain screening failed; linear extrapolation is unsuitable")
    if strength_ratio is None:
        reasons.append("explicit applicable failure criterion, strength data and strength safety factor are required")
    materials=levels[-1]['mesh'].get('materials',{'BODY':m}) if 'mesh' in levels[-1] else {'BODY':m}
    for name,material in materials.items():
        if material.get('failure_criterion')=='max_stress' and not material.get('calibration'):
            reasons.append(f"directional strength calibration and applicability are not recorded: {name}")
    if stiffness_ratio is None:
        reasons.append("an explicit allowable displacement or named probe limit is required")
    reasons += [f"condition not verified: {k}" for k in CONDITIONS if not c["conditions"][k] and not (k=="self_weight_negligible" and c.get("gravity"))]
    if c.get('connections'):
        if not c['conditions'].get('connection_parameters_verified',False):reasons.append('condition not verified: connection_parameters_verified')
        for connection in c['connections']:
            if connection['type']=='linear_interface' and not connection.get('calibration'):
                reasons.append('linear interface stiffness calibration and applicability are not recorded: '+connection['name'])
        if len(materials)>1:sigma_allow=None
    buckling=None
    if c.get("buckling",{}).get("enabled"):
        factors=[l.get("buckling",{}).get("lowest_positive_factor") for l in levels]
        changes=[abs(b-a)/b for a,b in zip(factors,factors[1:])] if all(f is not None and f>0 for f in factors) else []
        normalized=all(l.get('buckling',{}).get('reference_normalization_verified') is True for l in levels)
        buckling_ok=normalized and len(changes)>=2 and all(x<=c["buckling"].get("eigenvalue_relative_tolerance",.05) for x in changes[-2:])
        buckling={"lowest_positive_load_factor":factors[-1],"mesh_relative_changes":changes,"mesh_converged":buckling_ok,
                  "reference_normalization_verified":normalized,
                  "safety_factor":c["buckling"].get("safety_factor",2.),"reference_utilization":c["buckling"].get("safety_factor",2.)/factors[-1] if factors[-1] else None,
                  "interpretation":"ideal elastic bifurcation screening; not nonlinear collapse or calibrated imperfection allowance"}
        if not buckling_ok:
            reasons.append("elastic buckling factors lack mesh/reference-scale qualification or no positive factor was found")
        criteria_evidence['elastic_buckling']=criterion_state(buckling['reference_utilization'],buckling_ok)
    scale, governing, predicted_small = None, None, None
    if contact:
        reasons.append('Contact load history is nonlinear; no affine superposition or automatic load-capacity factor. Recompute each requested load.')
    if not predict_capacity:
        reasons.append('Capacity prediction was not requested; full requested loads were assessed without optional capacity extrapolation.')
    if not reasons:
        limits = {"strength": 1/max(strength_ratio, 1e-30), "stiffness": 1/max(stiffness_ratio, 1e-30)}
        governing = min(limits, key=limits.get)
        candidate = limits[governing]
        if field_components and any(fixed is not None for _,fixed in field_components):
            candidate,detail=fixed_load_limit(*field_components[-1],sigma_allow,disp_allow)
            if candidate is None:
                reasons.append(detail)
            else:
                governing=detail
        if candidate is not None and buckling and buckling["lowest_positive_load_factor"]/buckling["safety_factor"] < candidate:
            candidate=buckling["lowest_positive_load_factor"]/buckling["safety_factor"]
            governing="elastic_buckling_screening"
        predicted = field_metrics(*field_components[-1],candidate) if field_components and candidate is not None else None
        predicted_small = {"displacement_to_minimum_extent": (predicted["max_displacement_mm"]/rt["minimum_bbox_extent_mm"] if predicted else candidate*small_u),
                           "strain_norm": (predicted["max_strain_norm"] if predicted else candidate*rt["max_strain_norm"])} if candidate is not None else None
        if predicted and len(field_components)>=3:
            metrics=[field_metrics(full,fixed,candidate) for full,fixed in field_components]
            pchanges=[{"displacement":abs(b["max_displacement_mm"]-a["max_displacement_mm"])/max(b["max_displacement_mm"],1e-30),
                       "stress":abs(b["max_von_mises_mpa"]-a["max_von_mises_mpa"])/max(b["max_von_mises_mpa"],1e-30),
                       "strength":abs(b['strength_utilization']-a['strength_utilization'])/max(b['strength_utilization'],1e-30) if b.get('strength_utilization') is not None and a.get('strength_utilization') is not None else 0.} for a,b in zip(metrics,metrics[1:])]
            if any(p["displacement"]>du or p["stress"]>ds or p['strength']>ds for p in pchanges[-2:]):
                reasons.append("response at the predicted fixed-plus-payload limit did not converge")
            predicted_probe_pairs=[convergence(a.get('probes',[]),b.get('probes',[]),du) for a,b in zip(metrics,metrics[1:])]
            if any(not p[name]['converged'] for p in predicted_probe_pairs[-2:] for name in required_probes):
                reasons.append('named probe response at the predicted fixed-plus-payload limit did not converge')
            predicted_region_pairs=[compare_regions(a.get('stress_regions',[]),b.get('stress_regions',[]),region_names,ds) for a,b in zip(metrics,metrics[1:])]
            if any(not v['converged'] for pair in predicted_region_pairs[-2:] for v in pair.values()):
                reasons.append('local stress response at the predicted fixed-plus-payload limit did not converge')
        if candidate is None:
            pass
        elif reasons:
            pass
        elif predicted_small["displacement_to_minimum_extent"] > small_u_limit or predicted_small["strain_norm"] > strain_limit:
            reasons.append("predicted limiting load exceeds small-displacement/strain screening; no linear capacity issued")
        else:
            scale = candidate
    if not balance_ok:
        status = "invalid"
    elif not linear_screen or not converged or strength_ratio is None or stiffness_ratio is None or (buckling and not buckling["mesh_converged"]):
        status = "indeterminate"
    elif max(strength_ratio, stiffness_ratio, buckling["reference_utilization"] if buckling else 0) > 1:
        status = "fail_under_stated_model"
    else:
        status = "pass_under_stated_model"
    if status in ('pass_under_stated_model','fail_under_stated_model'):
        additional=[v for k,v in criteria_evidence.items() if k.startswith(('bolt:','contact_motion:'))]
        if any(v['status']=='indeterminate' for v in additional):status='indeterminate'
        elif any(v['status']=='fail_under_stated_model' for v in additional):status='fail_under_stated_model'
    if contact and not contact_converged:status='indeterminate' if balance_ok else 'invalid'
    # Only a single downward vertical payload can be converted into a mass-equivalent.
    loads = c["loads"]
    mass_equivalent = None
    if scale is not None and len(loads) == 1 and loads[0].get("scalable",True) and not any(loads[0].get("total_moment_n_mm",[0,0,0])) and "application_point_mm" not in loads[0]:
        f = loads[0]["total_force_n"]
        if abs(f[0]) < 1e-12 and abs(f[1]) < 1e-12 and f[2] < 0:
            mass_equivalent = -f[2]*scale/9.80665
    return {
        "scope": "structural bodies and explicitly declared axial bolt tension/contact motion under stated fixtures/material/load pattern; no whole installation/product qualification" if contact else "structural bodies under stated fixtures/material/load pattern; declared failure criteria, displacement and requested elastic buckling screening",
        "status": status, "whole_installation_status": "not_assessed",
        "strength_utilization": strength_ratio, "stiffness_utilization": stiffness_ratio, "buckling":buckling,
        "criterion_assessments":criteria_evidence,
        "allowable_von_mises_mpa": sigma_allow, "allowable_displacement_mm": disp_allow,
        "strength_peak":rt.get('strength_peak'),"failure_criteria":{name:material.get('failure_criterion','not_specified') for name,material in materials.items()},
        "stress_regions":rt.get('stress_regions',[]),
        "verification": {"force_and_moment_balance_passed": balance_ok, "mesh_converged": converged,
                         "stress_regions_converged":regions_converged,"stress_region_mesh_comparisons":region_pairs,
                         **({'bolt_mesh_comparisons':bolt_comparisons} if c.get('bolts') else {}),
                         "mesh_comparisons": pairs, "small_response_screen_passed": linear_screen,
                         **({'contact_mesh_comparisons':contact_pairs} if contact else {}),
                         "displacement_to_minimum_extent": small_u, "max_strain_norm": rt["max_strain_norm"],
                         "small_displacement_ratio_limit": small_u_limit, "strain_norm_limit": strain_limit},
        "conditional_body_limit": {"available": scale is not None, "prediction_requested":predict_capacity,"load_pattern_scale_factor": scale,
             "governing_limit": governing if scale is not None else None,
             "scaled_loads_n": [{"name": l["name"], "scalable":l.get("scalable",True), "total_force_n": [v*(scale if l.get("scalable",True) else 1.) for v in l["total_force_n"]],
                                 "total_moment_n_mm":[v*(scale if l.get("scalable",True) else 1.) for v in l.get("total_moment_n_mm",[0,0,0])]} for l in loads] if scale is not None else None,
             "vertical_payload_mass_equivalent_kg": mass_equivalent,
             "predicted_response_screen": predicted_small,
             "withheld_reasons": reasons,
             "meaning": "Conditional body yield/displacement and requested elastic-buckling screening limit; scalable load pattern changes while fixed loads remain constant. NOT an installation working load or ultimate load."},
        "conditions": c["conditions"], "not_assessed": [s for s in NOT_ASSESSED if not (buckling and s.startswith("Buckling")) and not (c.get("gravity") and s.startswith("Self-weight"))
            and not (contact and s.startswith('Contact, separation'))
            and not (s.startswith('Directional material') and all(m.get('failure_criterion')=='max_stress' and m.get('calibration') for m in materials.values()))]
            + (['Nonplanar/large sliding contact, accumulated irreversible slip, wear, friction/preload uncertainty, local bolt threads/bearing/shear/bending, torque-to-preload conversion and unspecified joint compliance. Only declared planar contact and any explicit equivalent axial bolts are assessed.',
                'Intermediate-increment peaks, arbitrary unload/reload cycles and time-dependent relaxation; criteria assess the requested stage endpoints.'] if contact else [])
            + (["Nonlinear buckling collapse and calibrated imperfection sensitivity"] if buckling else []),
        "limitations": ["Only scalable loads scale together; modeled gravity and fixed loads remain constant. Unspecified loads and pre-stresses are omitted.",
                    "Six source-bound material-point equations remove rigid motion only; global displacement depends on the gauge and physical fixture/contact compliance is omitted." if c.get('reference_only') else "Declared support translation components are prescribed on full CAD faces (zero initially, any explicit fixture motion in service); unspecified fixture compliance is omitted.",
                        "Peak integration-point stress is used without arbitrary clipping or percentile filtering.",
                        "The small-response thresholds are screening heuristics, not a nonlinear verification.",
                        "von Mises yield applies to isotropic ductile materials. Directional max-stress checks require calibrated tension/compression/shear allowables and do not model damage interaction, delamination or defects."]}
