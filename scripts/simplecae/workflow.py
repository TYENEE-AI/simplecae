from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import platform
import copy
import numpy as np

from . import __version__
from .case import load_case, sha256, write_json
from .geometry import make_mesh
from .solver import find_ccx, write_deck, execute, parse_dat, summarize
from .assessment import assess
from .report import plot_fields, render_report
from .sources import SourceGuard, source_paths


def save_field_arrays(directory,fields):
    from .materials import strength_values
    ids=list(fields['stresses']);strength=None
    if fields.get('_strength_context'):
        strength,_=strength_values(list(fields['stresses'].values()),ids,fields['_strength_context'])
    np.savez_compressed(Path(directory)/'fields.npz',node_ids=np.array(list(fields['displacements'])),
        displacements=np.array(list(fields['displacements'].values())),stress_ids=np.array(ids,dtype=int),
        stresses=np.array(list(fields['stresses'].values())),strains=np.array([fields['strains'][k] for k in ids]),
        strength_utilizations=strength if strength is not None else np.array([]))


def analyze(case_path: Path, out: Path, ccx=None, timeout=300, preview=True, *, prepared_case=None,mesh_factory=None,source_signature=None,progress=None,cache=None,reuse_levels=None,predict_capacity=True,require_fixed_response=False):
    from .progress import emit
    c = copy.deepcopy(prepared_case) if prepared_case is not None else load_case(case_path.resolve())
    from .contact import enabled as has_contact
    contact=has_contact(c)
    if not isinstance(predict_capacity,bool):raise ValueError('predict_capacity must be a boolean')
    if not isinstance(require_fixed_response,bool):raise ValueError('require_fixed_response must be a boolean')
    if not predict_capacity and (cache is not None or reuse_levels is not None):raise ValueError('capacity-disabled caching is not qualified; use a fresh solve without cache/reuse-levels')
    if contact and (cache is not None or reuse_levels is not None):raise ValueError('contact load-history caching is not qualified; use a fresh solve without cache/reuse-levels')
    if cache is not None and Path(cache).resolve().is_relative_to(out.resolve()):
        raise ValueError('cache directory must be outside the analysis output')
    if reuse_levels is not None and Path(reuse_levels).resolve().is_relative_to(out.resolve()):
        raise ValueError('level cache directory must be outside the analysis output')
    if c.get("load_cases"):
        return analyze_envelope(c,case_path,out,ccx,timeout,preview,progress=progress,cache=cache,reuse_levels=reuse_levels,predict_capacity=predict_capacity)
    signature=source_signature or (lambda:sha256(Path(c['model']['path'])))
    initial_step_hash = signature()
    guard=SourceGuard(source_paths(c)|{case_path.resolve()})
    out.mkdir(parents=True, exist_ok=False)
    result = {"schema_version": c['schema_version'], "toolkit_version": __version__,
              "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "python_version": platform.python_version(), "analysis": "linear_static_assembly" if c['schema_version']=='assembly-1.0' else "linear_static",
              "units": {"length": "mm", "force": "N", "stress": "MPa"},
              "source_case_sha256": sha256(case_path), "source_model_sha256":initial_step_hash,
              "source_step_sha256": initial_step_hash if c.get('model') and Path(c['model']['path']).suffix.lower() in ('.step','.stp') else None,
              "source_files_sha256":guard.hashes,"case": c, "levels": [],
              "analysis_options":{"predict_capacity":predict_capacity,"require_fixed_response":require_fixed_response}}
    if contact:result['analysis']='frictionless_contact_assembly' if not c.get('bolts') and not any(j['type']=='frictional_contact' for j in c['connections']) else 'staged_contact_assembly'
    write_json(out / "case.resolved.json", c)
    from .signals import structural_contract
    result['task_contract']=copy.deepcopy(structural_contract(c))
    try:
        from .resources import require_storage,native_output_estimate
        result['storage_preflight']=require_storage(out)
        executable = find_ccx(ccx)
        reuse_key=None
        if cache is not None:
            from .cache import cache_key,load
            guard.check();reuse_key=cache_key(c,executable)
            reused=load(cache,reuse_key,out)
            if reused is not None:
                guard.check();emit(progress,'cache_hit',output=str(out))
                reused.update(case=c,source_case_sha256=sha256(case_path),source_files_sha256=guard.hashes,task_contract=copy.deepcopy(structural_contract(c)))
                if c.get('model'):
                    for level in reused['levels']:
                        level['mesh']['geometry']['source_step']=c['model']['path']
                write_json(out/'case.resolved.json',c)
                from .signals import attach_signal
                attach_signal(reused,out);write_json(out/'result.json',reused);render_report(reused,out)
                guard.check()
                return reused
        components=[];preload_levels=[];locked_levels=[]
        for i, h in enumerate(c["mesh"]["sizes_mm"]):
            mesh=fields=summary=None
            require_storage(out)
            emit(progress,'mesh',level=i+1,levels=len(c['mesh']['sizes_mm']),size_mm=h)
            guard.check()
            directory = out / f"level-{i+1:02d}"
            directory.mkdir()
            cached_level=None;level_key_value=None
            if reuse_levels is not None:
                from .level_cache import level_key,restore
                level_key_value=level_key(c,h,executable)
                restored=restore(reuse_levels,level_key_value,directory)
                if restored:
                    mesh,cached_level=restored
                    emit(progress,'level_cache_hit',level=i+1,size_mm=h,output=str(directory))
            if cached_level is None:mesh = (mesh_factory or make_mesh)(c, h, directory)
            guard.check()
            guard.check_mesh(c,mesh[-1])
            mesh[-1]['storage_preflight']=require_storage(directory,native_output_estimate(mesh[-1],c))
            if mesh[-1]["geometry"]["geometry_sha256"] != initial_step_hash:
                raise RuntimeError("STEP source changed between mesh levels")
            probe_context=None
            if c.get('probes'):
                from .probes import prepare_context
                emit(progress,'probe_prepare',level=i+1)
                probe_context=prepare_context(c,mesh,directory/'mesh.npz')
            inp = directory / "job.inp"
            if cached_level is None:
                write_deck(c, mesh, inp)
                from .execution import cost_projection
                cost=cost_projection(mesh[-1],result['levels'])
                write_json(directory/'execution-plan.json',cost)
                emit(progress,'resource_estimate',level=i+1,**cost)
                emit(progress,'static',level=i+1,elements=mesh[-1]['element_count'])
                solver = execute(executable, inp, timeout)
            else:
                from .level_cache import verify_deck
                verify_deck(c,mesh,directory);solver=cached_level['solver']
            fields = parse_dat(inp.with_suffix(".dat"),exclude_sets=('BOLT_STATE',))
            bolt_data=mesh[-1].get('connection_data',{}).get('bolts',[])
            if bolt_data:
                from .bolts import summarize as bolt_summary
                initial_fields=parse_dat(inp.with_suffix('.dat'),time=1.,exclude_sets=('BOLT_STATE',))
                initial_bolts=bolt_summary(inp.with_suffix('.dat'),bolt_data,1.,displacements=initial_fields['displacements'])
                fields['_bolt_states']=bolt_summary(inp.with_suffix('.dat'),bolt_data,3.,initial_bolts,fields['displacements'])
            summary = summarize(fields, mesh,c,probe_context=probe_context) if probe_context else summarize(fields,mesh,c)
            if contact:
                from .contact import completed_steps,summarize as contact_summary,stage_names
                stages=len(stage_names(c))
                solver['completed_load_steps']=completed_steps(inp.with_suffix('.sta'),stages)
                summary['contact']=contact_summary(inp.with_suffix('.dat'),mesh[-1]['connection_data']['contacts'],displacements=fields['displacements'])
            if bolt_data:
                summary['bolts']=fields['_bolt_states']
            fixed_fields=None
            # Preload/lock are physical contact stages; only the optional linear
            # fixed-load decomposition may be omitted for a requested-load check.
            if (contact or predict_capacity or require_fixed_response) and (mesh[-1].get("fixed_nodal_forces") or bolt_data):
                emit(progress,'fixed_loads',level=i+1)
                fixed_forces={int(n):np.array(f) for n,f in mesh[-1]["fixed_nodal_forces"].items()}
                fixed_meta=copy.deepcopy(mesh[-1])
                fixed_meta["applied_force_n"]=sum(fixed_forces.values(),np.zeros(3)).tolist()
                fixed_meta["applied_moment_n_mm"]=sum((np.cross(mesh[0][n],f) for n,f in fixed_forces.items()),np.zeros(3)).tolist()
                fixed_mesh=(*mesh[:3],fixed_forces,fixed_meta)
                fixed_input=directory/"fixed.inp"
                if contact:
                    fixed_fields=parse_dat(inp.with_suffix('.dat'),time=1.,exclude_sets=('BOLT_STATE',))
                    fixed_solver={'source':'preload step of job.inp','step':1,'total_time':1.}
                elif cached_level is None:
                    write_deck(c,fixed_mesh,fixed_input)
                    fixed_solver=execute(executable,fixed_input,timeout)
                else:
                    verify_deck(c,fixed_mesh,directory,'fixed')
                    import json
                    from .level_cache import relocate
                    fixed_solver=relocate(json.loads((directory/'fixed-results.json').read_text(encoding='utf-8'))['solver'],
                                          Path(cached_level['level_reuse']['original_output']),directory.resolve())
                if not contact:fixed_fields=parse_dat(fixed_input.with_suffix(".dat"))
                if bolt_data:fixed_fields['_bolt_states']=initial_bolts
                fixed_summary=summarize(fixed_fields,fixed_mesh,c,probe_context=probe_context) if probe_context else summarize(fixed_fields,fixed_mesh,c)
                if contact:
                    fixed_summary['contact']=contact_summary(inp.with_suffix('.dat'),mesh[-1]['connection_data']['contacts'],time=1.,displacements=fixed_fields['displacements'])
                    if bolt_data:fixed_summary['bolts']=initial_bolts
                    preload_levels.append({'mesh_size_mm':h,'mesh':mesh[-1],'results':fixed_summary})
                write_json(directory/"fixed-results.json",{"results":fixed_summary,"solver":fixed_solver})
                if max(fixed_summary["force_balance_relative_error"],fixed_summary["moment_balance_relative_error"])>c["mesh"].get("balance_relative_tolerance",5e-4):
                    raise RuntimeError("fixed-load subcase failed equilibrium")
                if bolt_data:
                    locked_fields=parse_dat(inp.with_suffix('.dat'),time=2.,exclude_sets=('BOLT_STATE',))
                    locked_fields['_bolt_states']=bolt_summary(inp.with_suffix('.dat'),bolt_data,2.,initial_bolts,locked_fields['displacements'])
                    locked_summary=summarize(locked_fields,fixed_mesh,c,probe_context=probe_context) if probe_context else summarize(locked_fields,fixed_mesh,c)
                    locked_summary['contact']=contact_summary(inp.with_suffix('.dat'),mesh[-1]['connection_data']['contacts'],time=2.,displacements=locked_fields['displacements'])
                    locked_summary['bolts']=locked_fields['_bolt_states']
                    locked_levels.append({'mesh_size_mm':h,'mesh':mesh[-1],'results':locked_summary})
                    write_json(directory/'locked-results.json',{'results':locked_summary,'solver':{'source':'job.inp','step':2,'total_time':2.}})
            components.append((fields,fixed_fields))
            save_field_arrays(directory,fields)
            level = {"mesh_size_mm": h, "mesh": mesh[-1], "results": summary,
                     "solver": solver, "directory": str(directory.resolve()), "input_sha256": sha256(inp),
                     "created_at_utc":cached_level.get('created_at_utc') if cached_level else datetime.now(timezone.utc).isoformat()}
            if cached_level:level['level_reuse']=cached_level['level_reuse']
            if c.get("buckling",{}).get("enabled"):
                emit(progress,'buckling',level=i+1)
                from .buckling import run_buckling
                if cached_level is None:level["buckling"]=run_buckling(c,mesh,directory,executable,timeout)
                else:
                    from .level_cache import verify_buckling
                    level['buckling']=verify_buckling(c,mesh,directory,cached_level['buckling'])
            result["levels"].append(level)
            write_json(directory / "results.json", level)
            write_json(out / "result.json", result)
            guard.check()
            if reuse_levels is not None and cached_level is None:
                from .level_cache import write_state,save,level_key
                if level_key_value==level_key(c,h,executable):
                    write_state(mesh,directory)
                    try:save(reuse_levels,level_key_value,directory,level,c['mesh'].get('balance_relative_tolerance',5e-4))
                    except OSError as exc:emit(progress,'level_cache_write_failed',level=i+1,error=str(exc))
        emit(progress,'assessment')
        result["assessment"] = assess(c, result["levels"],components,predict_capacity=predict_capacity)
        result["status"] = result["assessment"]["status"]
        if contact:result['stage_assessments']={'service':copy.deepcopy(result['assessment'])}
        if contact and preload_levels:
            result['preload_assessment']=assess(c,preload_levels,predict_capacity=predict_capacity)
            result['stage_assessments']['preload']=result['preload_assessment']
            order={'pass_under_stated_model':0,'fail_under_stated_model':1,'indeterminate':2,'invalid':3}
            result['status']=max((result['status'],result['preload_assessment']['status']),key=order.get)
            result['assessment']['status']=result['status']
            result['assessment']['criterion_assessments'].update({'preload:'+k:v for k,v in result['preload_assessment']['criterion_assessments'].items()})
        if locked_levels:
            locked=assess(c,locked_levels,predict_capacity=predict_capacity);result['stage_assessments']['locked']=locked
            order={'pass_under_stated_model':0,'fail_under_stated_model':1,'indeterminate':2,'invalid':3}
            result['status']=max((result['status'],locked['status']),key=order.get);result['assessment']['status']=result['status']
            result['assessment']['criterion_assessments'].update({'locked:'+k:v for k,v in locked['criterion_assessments'].items()})
        if preview:
            try:
                plot_fields(mesh, fields, directory / "fields.png")
                result["preview_relative_path"] = f"{directory.name}/fields.png"
            except Exception as exc:
                result["preview_error"] = str(exc)
        if signature() != initial_step_hash:
            raise RuntimeError("STEP source changed during analysis")
        guard.check()
    except Exception as exc:
        result["status"] = "invalid"
        result.pop("assessment", None)
        result["error"] = f"{type(exc).__name__}: {exc}"
        if contact and hasattr(exc,'diagnostic'):
            exc.diagnostic['native_evidence']={'directory':str(directory.resolve()),
                **{k:solver[k] for k in ('input_sha256','dat_sha256','executable_sha256') if k in solver}}
            result['contact_diagnostic']=exc.diagnostic
            write_json(directory/'contact-diagnostic.json',exc.diagnostic)
        # A failed contact-law/stage check must not hide already verified raw
        # service fields. Keep these separate from accepted solved levels; no
        # criterion, comparison or capacity can be inferred from this record.
        if contact and locals().get('summary') is not None and fields is not None and mesh is not None and not any(l['directory']==str(directory.resolve()) for l in result['levels']):
            try:
                save_field_arrays(directory,fields)
                diagnostic={'mesh_size_mm':h,'mesh':mesh[-1],'results':summary,'directory':str(directory.resolve()),
                            'solver':solver,'input_sha256':sha256(inp),
                            'diagnostic_only':True,'unaccepted_reason':result['error']}
                write_json(directory/'diagnostic-results.json',diagnostic)
                result['diagnostic_levels']=[diagnostic]
            except Exception as preservation_error:
                result['diagnostic_preservation_error']=f'{type(preservation_error).__name__}: {preservation_error}'
    from .signals import attach_signal
    attach_signal(result,out)
    write_json(out / "result.json", result)
    emit(progress,'report',status=result['status'])
    render_report(result, out)
    if cache is not None and 'reuse_key' in locals() and reuse_key is not None:
        from .cache import save,cache_key
        try:
            if reuse_key==cache_key(c,executable):save(cache,reuse_key,out,result)
        except OSError as exc:
            emit(progress,'cache_write_failed',error=str(exc))
    return result


def analyze_envelope(c,case_path,out,ccx,timeout,preview,*,progress=None,cache=None,reuse_levels=None,predict_capacity=True):
    import html
    out.mkdir(parents=True,exist_ok=False)
    entries=[]
    guard=SourceGuard(source_paths(c)|{case_path.resolve()})
    source_error=None
    for i,spec in enumerate(c["load_cases"]):
        try:guard.check()
        except RuntimeError as exc:
            source_error=str(exc);break
        child=copy.deepcopy(c)
        child.pop("load_cases")
        child["loads"]=spec["loads"]
        if "gravity" in spec:
            child["gravity"]=spec["gravity"]
        child_path=out/f"case-{i+1:02d}.json"
        write_json(child_path,child)
        directory=out/f"case-{i+1:02d}"
        solved=analyze(child_path,directory,ccx,timeout,preview,progress=progress,cache=cache,reuse_levels=reuse_levels,predict_capacity=predict_capacity)
        entries.append({"name":spec["name"],"status":solved["status"],"result_relative_path":f"{directory.name}/result.json",
                        "report_relative_path":f"{directory.name}/report.html","case":solved['case'],"assessment":solved.get("assessment"),"error":solved.get("error")})
    try:guard.check()
    except RuntimeError as exc:source_error=str(exc)
    priority={"invalid":4,"indeterminate":3,"fail_under_stated_model":2,"pass_under_stated_model":1}
    status='invalid' if source_error else max((e["status"] for e in entries),key=priority.get)
    limits=[e["assessment"]["conditional_body_limit"]["load_pattern_scale_factor"] if e["assessment"] and e["assessment"]["conditional_body_limit"]["available"] else None for e in entries]
    result={"schema_version":"2.0","toolkit_version":__version__,"analysis":"load_case_envelope","status":status,"source_case_sha256":sha256(case_path),
            "source_files_sha256":guard.hashes,"case":c,"cases":entries,"analysis_options":{"predict_capacity":predict_capacity},
            "common_payload_scale_limit":min(limits) if limits and not source_error and all(x is not None for x in limits) else None,
            "meaning":"Minimum conditional scalable-load factor across the listed alternative operation cases. Fixed loads stay constant in each case; no installation certification."}
    from .signals import structural_contract
    result['task_contract']=copy.deepcopy(structural_contract(c))
    if status=='invalid':result['error']=source_error or 'At least one load case is invalid; inspect child reports.'
    result['not_assessed']=sorted({item for e in entries for item in (e.get('assessment') or {}).get('not_assessed',[])})
    result['whole_installation_status']='not_assessed'
    from .signals import attach_signal
    attach_signal(result,out)
    write_json(out/"result.json",result)
    rows="".join(f'<tr><td>{html.escape(str(e["name"]))}</td><td>{html.escape(e["status"])}</td><td><a href="{e["report_relative_path"]}">查看该工况</a></td></tr>' for e in entries)
    (out/"report.html").write_text('<!doctype html><meta charset="utf-8"><title>SimpleCAE 工况汇总</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto}table{width:100%;border-collapse:collapse}td{padding:15px;border-bottom:1px solid #ccc}</style><h1>多个使用工况的分析汇总</h1><p>各工况中的固定载荷保持不变，比较的是各自的可增加载荷。全部成立条件与未评估项见分工况报告。</p><table>'+rows+'</table>',encoding="utf-8")
    return result
