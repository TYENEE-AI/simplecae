"""CalculiX deck writing, isolated execution, complete DAT field extraction."""
from __future__ import annotations
from .defaults import DEFAULT_NATIVE_TIMEOUT

import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import time
import numpy as np

from .case import sha256

ROOT = Path(__file__).resolve().parents[2]


def native_real(value):
    """CalculiX reads real fields as F20.0, even in comma-separated input."""
    x = float(value)
    if not np.isfinite(x):
        raise ValueError("Native real input must be finite")
    for precision in range(15, 11, -1):
        text = format(x, f".{precision}g")
        if len(text) <= 20:
            return text
    raise ValueError("Native real input cannot fit a 20-character field")


def validate_real_fields(path):
    """Fail before native execution rather than silently truncating an exponent."""
    number = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?$")
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("*"):
            continue
        for field in line.split(","):
            field = field.strip()
            if number.fullmatch(field) and len(field) > 20:
                raise ValueError(f"Native real field exceeds F20.0 width at {Path(path).name}:{i}; format without truncating its exponent")


def find_ccx(explicit=None):
    request = explicit or os.environ.get("SIMPLECAE_CCX")
    if request:
        p = Path(shutil.which(str(request)) or str(request)).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"CalculiX executable not found: {request}")
        return p
    config=ROOT/'.tools/runtime.json'
    if config.is_file():
        import json
        settings=json.loads(config.read_text(encoding='utf-8-sig'))
        if not isinstance(settings,dict) or not isinstance(settings.get('ccx_by_platform',{}),dict):
            raise ValueError('runtime.json must be an object with an optional ccx_by_platform object')
        configured=settings.get('ccx_by_platform',{}).get(platform.system()) or settings.get('ccx')
        if configured:
            if not isinstance(configured,str):
                raise ValueError('configured CalculiX executable must be a path or executable name')
            p=Path(shutil.which(configured) or configured).expanduser().resolve()
            if not p.is_file():raise FileNotFoundError('configured CalculiX executable is missing; rerun bootstrap or supply --ccx')
            return p
    on_path = shutil.which("ccx")
    if on_path:
        return Path(on_path).resolve()
    local = list((ROOT / ".tools" / "calculix-2.23").glob("**/ccx.exe"))
    if len(local) == 1:
        return local[0].resolve()
    raise FileNotFoundError("CalculiX not found; run scripts/bootstrap.ps1 or set SIMPLECAE_CCX / --ccx")


def write_deck(c, mesh, path):
    from .materials import material_deck,primary_material
    coords, tets, fixed, forces, meta = mesh
    m = primary_material(c)
    lines = ["*HEADING", "SimpleCAE general structural screening; units mm N MPa", "*NODE,NSET=NALL"]
    lines += [f"{n}," + ",".join(f"{v:.12g}" for v in p) for n, p in sorted(coords.items())]
    lines += ["*ELEMENT,TYPE=C3D10,ELSET=EALL"]
    lines += [f"{e}," + ",".join(map(str, ns)) for e, ns in sorted(tets.items())]
    lines += ["*NSET,NSET=FIXED"]
    lines += [",".join(map(str, fixed[i:i+16])) for i in range(0, len(fixed), 16)]
    if meta.get('materials'):
        for name,material in meta['materials'].items():
            elements=[int(e) for e,n in meta['element_material'].items() if n==name]
            lines+=[f'*ELSET,ELSET=E_{name}']+[','.join(map(str,elements[i:i+16])) for i in range(0,len(elements),16)]
            lines+=material_deck(material,name,'E_'+name)
    else:lines += material_deck(m,'BODY','EALL')
    if meta.get('connection_data'):
        from .assembly import connection_deck
        lines+=connection_deck(meta['connection_data'])
    from .constraints import boundary_lines
    boundary=boundary_lines(meta['fixed_dofs']) if 'fixed_dofs' in meta else ['FIXED,1,3']
    if meta.get('reference_support'):
        from .reference_support import equation_deck,balanced
        balanced(coords,forces,meta)
        lines+=equation_deck(meta['reference_support'])
    if boundary:lines += ["*BOUNDARY",*boundary]
    if meta.get('connection_data',{}).get('contacts'):
        from .contact import steps
        lines+=steps(c,forces,meta)
        path.write_text('\n'.join(lines)+'\n',encoding='ascii')
        return
    lines += ["*STEP", "*STATIC,SOLVER=SPOOLES", "*CLOAD"]
    lines += [f"{n},{axis+1},{float(f):.12g}" for n, vector in sorted(forces.items())
              for axis, f in enumerate(vector) if abs(f) > 1e-14]
    lines += ["*NODE PRINT,NSET=NALL", "U", "*NODE PRINT,NSET=FIXED", "RF",
              "*EL PRINT,ELSET=EALL,GLOBAL=YES", "S,E", "*NODE FILE", "U", "*EL FILE,GLOBAL=YES", "S,E", "*END STEP"]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def execution_threads():
    from .parallel import select_threads
    return select_threads()["threads"]


def timeout_diagnostic(inp, timeout):
    """Report completed progress and native work, without declaring convergence."""
    from .case import write_json
    log=inp.with_suffix('.solver.log').read_text(encoding='utf-8',errors='replace')
    steps={}
    sta=inp.with_suffix('.sta')
    if sta.is_file():
        for row in sta.read_text(errors='replace').splitlines():
            parts=row.split()
            if len(parts)!=7:continue
            try:
                step,increment,attempt,iterations=map(int,parts[:4])
                step_time=float(parts[5].replace('D','E'))
            except ValueError:continue
            steps[str(step)]={'last_completed_increment':increment,'step_time':step_time}
    counts=[int(v) for v in re.findall(r'Number of contact spring elements=\s*(\d+)',log)]
    equations=re.findall(r'number of equations\s+(\d+)',log)
    result={'status':'timeout','timeout_seconds':timeout,'completed_progress':steps,
            'equations':int(equations[-1]) if equations else None,
            'factorization_count':log.count('Factoring the system of equations'),
            'last_contact_spring_count':counts[-1] if counts else None,
            'maximum_contact_spring_count':max(counts) if counts else None,
            'meaning':'Native progress only; completed intermediate increments do not qualify the full load.',
            'next_action':'Inspect mesh cost and the recorded load stage. Use located refinement and '
                          'appropriate numerical load increments; preserve full endpoints and all contact '
                          'gates. A timeout alone does not establish instability or justify more budget.'}
    write_json(inp.with_suffix('.solver-diagnostic.json'),result)
    return result


def execute(ccx: Path, inp: Path, timeout=DEFAULT_NATIVE_TIMEOUT, analysis_type="static", *, threads=None):
    validate_real_fields(inp)
    for ext in (".dat", ".sta", ".frd"):
        if inp.with_suffix(ext).exists():
            raise ValueError("solver output already exists; use a fresh analysis directory")
    env = os.environ.copy()
    from .parallel import select_threads, available_cpus
    if threads is None:
        resource_plan=select_threads(ccx,inp,analysis_type)
        threads=resource_plan["threads"]
    else:
        if isinstance(threads,bool) or not isinstance(threads,int) or not 1<=threads<=available_cpus():
            raise ValueError("Native thread override exceeds the available CPU count")
        resource_plan={"mode":"calibration","threads":threads,"physics_changed":False}
    for key in ('OMP_NUM_THREADS','NUMBER_OF_CPUS','CCX_NPROC_EQUATION_SOLVER','CCX_NPROC_RESULTS','CCX_NPROC_STIFFNESS'):
        env[key]=str(threads)
    log_path=inp.with_suffix('.solver.log')
    started=time.monotonic()
    try:
        # Keep the native iteration trace inspectable while a long solve runs,
        # and retain it on timeout. No in-memory capture delays the evidence.
        with log_path.open('w',encoding='utf-8') as stream:
            result = subprocess.run([str(ccx), "-i", inp.stem], cwd=inp.parent,
                                    env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        with log_path.open('a',encoding='utf-8') as stream:stream.write('\nTIMEOUT\n')
        try:
            timeout_diagnostic(inp,timeout)
            detail=f"inspect {inp.with_suffix('.solver-diagnostic.json')}"
        except Exception as diagnostic_error:
            detail=f"inspect {log_path}; diagnostic unavailable: {diagnostic_error}"
        raise RuntimeError(f"CalculiX exceeded {timeout} seconds; {detail}") from exc
    log=log_path.read_text(encoding='utf-8',errors='replace')
    if result.returncode != 0 or re.search(r"\*ERROR|segmentation fault|fatal error", log, re.I):
        raise RuntimeError(f"CalculiX failed (exit {result.returncode}); inspect {inp.with_suffix('.solver.log')}")
    sta = inp.with_suffix(".sta")
    if analysis_type == "static" and (not sta.is_file() or not any(re.match(r"^\s*\d+\s+\d+\s+\d+", row) for row in sta.read_text().splitlines())):
        raise RuntimeError("CalculiX has no completed static increment")
    for ext in (".dat", ".frd"):
        p = inp.with_suffix(ext)
        if not p.is_file() or p.stat().st_size == 0:
            raise RuntimeError(f"missing solver field output {p}")
    return {"executable": str(ccx), "executable_sha256": sha256(ccx), "returncode": result.returncode,
            "banner": next((r.strip() for r in log.splitlines() if "Version" in r), "see solver log"),
            "requested_threads":threads,
            "resource_plan":resource_plan,
            "elapsed_seconds":time.monotonic()-started,
            "native_work":native_work(log,inp.parent),
            "log": str(inp.with_suffix(".solver.log")), "analysis_type": analysis_type,
            "input_sha256": sha256(inp), "dat_sha256": sha256(inp.with_suffix(".dat")),
            "frd_sha256": sha256(inp.with_suffix(".frd")), "command": [str(ccx), "-i", inp.stem]}


def native_work(log, directory):
    """Cost evidence, not convergence or a guarantee that requested CPUs were used."""
    counts=[int(x) for x in re.findall(r'Number of contact spring elements=\s*(\d+)',log)]
    equations=re.findall(r'number of equations\s+(\d+)',log)
    spooles=Path(directory)/'spooles.out'
    observed=sorted(set(int(n) for n in re.findall(r'Using\s+(\d+)\s+threads',
        spooles.read_text(errors='replace') if spooles.is_file() else '')))
    return {'equations':int(equations[-1]) if equations else None,
            'factorization_count':log.count('Factoring the system of equations'),
            'maximum_contact_spring_count':max(counts) if counts else None,
            'spooles_reported_threads':observed,
            'meaning':'Native work counts and requested/observed parallelism; no convergence override.'}


def mises(s):
    a, b, c, xy, xz, yz = np.asarray(s)
    return float(np.sqrt(.5*((a-b)**2 + (b-c)**2 + (c-a)**2) + 3*(xy*xy+xz*xz+yz*yz)))


def dat_real(token):
    # Fortran's fixed-width scientific format omits E for 3-digit exponents.
    # Near-zero fields in unloaded separated bodies can legitimately do this.
    value=token.replace('D','E').replace('d','e')
    match=re.fullmatch(r'([+-]?(?:\d+\.\d*|\.\d+))([+-]\d{3,})',value)
    return float(match[1]+'E'+match[2] if match else value)


def parse_dat(path,*,time=None,exclude_sets=()):
    fields = {"displacements": {}, "reactions": {}, "stresses": {}, "strains": {}}
    section = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        low = line.strip().lower()
        header=next((key for prefix,key in (("displacements (","displacements"),("forces (","reactions"),("stresses (","stresses"),("strains (","strains")) if low.startswith(prefix)),None)
        if header:
            if any('for set '+name.lower()+' ' in low for name in exclude_sets):
                section=None;continue
            section=header
            if 'time' not in low and time is not None:raise RuntimeError('DAT time stamp is missing for requested load stage')
            stamp=float(low.rsplit('time',1)[1].replace('d','e')) if 'time' in low else None
            if time is not None and abs(stamp-time)>1e-7:section=None
            elif section:fields[section]={}
        elif low and low[0].isalpha():
            section=None
        else:
            parts = line.split()
            try:
                values = [dat_real(p) for p in parts]
            except ValueError:
                continue
            if section in ("displacements", "reactions") and len(values) == 4:
                fields[section][int(values[0])] = np.array(values[1:])
            elif section in ("stresses", "strains") and len(values) == 8:
                fields[section][(int(values[0]), int(values[1]))] = np.array(values[2:])
    if any(not values for values in fields.values()):
        raise RuntimeError("incomplete DAT fields: require displacements, fixed-node forces, stress and strain")
    if any(not np.all(np.isfinite(v)) for table in fields.values() for v in table.values()):
        raise RuntimeError("non-finite solver field")
    fields['_source_directory']=str(path.resolve().parent)
    return fields


def summarize(fields, mesh, case=None,*,probe_context=None):
    coords, tets, fixed, forces, meta = mesh
    if set(fields["displacements"]) != set(coords) or set(fields["reactions"]) != set(fixed):
        raise RuntimeError("DAT node coverage does not match this mesh")
    expected = {(e, ip) for e in tets for ip in (1, 2, 3, 4)}
    if set(fields["stresses"]) != expected or set(fields["strains"]) != expected:
        raise RuntimeError("DAT integration-point coverage does not match C3D10 mesh")
    u_node = max(coords, key=lambda n: np.linalg.norm(fields["displacements"][n]))
    bolt_forces={}
    states={b['name']:b for b in fields.get('_bolt_states',[])}
    for b in meta.get('connection_data',{}).get('bolts',[]):
        if b['name'] not in states:raise RuntimeError('missing bolt state for physical support reaction accounting')
        for role,sign in [('master',1.),('slave',-1.)]:
            for node,weight in b['ports'][role]['weights'].items():
                n=int(node);bolt_forces[n]=bolt_forces.get(n,np.zeros(3))+sign*weight*states[b['name']]['force_n']*np.array(b['axis'])
    ip_vm = {key: mises(s) for key, s in fields["stresses"].items()}
    peak = max(ip_vm, key=ip_vm.get)
    # RF includes both the constraint reaction and externally applied nodal
    # loads. All loads in this backend are explicit CLOAD, including gravity.
    reactions = {n: (f - forces.get(n, np.zeros(3)) - bolt_forces.get(n,np.zeros(3))) *
                 np.isin([1,2,3],meta.get('fixed_dofs',{}).get(str(n),[1,2,3]))
                 for n, f in fields["reactions"].items()}
    reaction = np.sum(list(reactions.values()), axis=0)
    from .contact import enabled as has_contact
    nonlinear=case is not None and has_contact(case)
    moment_coords={n:p+fields['displacements'][n] for n,p in coords.items()} if nonlinear else coords
    rmoment = np.sum([np.cross(moment_coords[n], f) for n, f in reactions.items()], axis=0)
    diag = float(np.linalg.norm(np.ptp(np.array(list(coords.values())), axis=0)))
    force_residual = reaction + np.array(meta["applied_force_n"])
    applied_moment=sum((np.cross(moment_coords[n],f) for n,f in forces.items()),np.zeros(3)) if nonlinear else np.array(meta['applied_moment_n_mm'])
    moment_residual = rmoment + applied_moment
    force_scale=meta['load_force_scale_n'];scale_basis='declared_force_moment_or_preload'
    if force_scale <= 0 and meta.get('service_boundary'):
        # For pure displacement control the applied work is at the fixtures.
        # Normalize by the actual opposing reaction magnitudes, not a made-up
        # force or the residual (which would normalize an error to itself).
        force_scale=float(sum(np.linalg.norm(f) for f in reactions.values())/2)
        scale_basis='half_sum_fixture_reaction_magnitudes'
    if not np.isfinite(force_scale) or force_scale <= 0:
        raise ValueError('No positive force/reaction scale for equilibrium verification; inspect the prescribed-motion load path')
    force_error = float(np.linalg.norm(force_residual) / force_scale)
    moment_error = float(np.linalg.norm(moment_residual) / (force_scale*diag))
    strain_norm = max(float(np.sqrt(np.sum(e[:3]**2) + 2*np.sum(e[3:]**2))) for e in fields["strains"].values())
    centroid = np.mean([coords[n] for n in tets[peak[0]][:4]], axis=0)
    result={"max_displacement_mm": float(np.linalg.norm(fields["displacements"][u_node])),
            "max_displacement_node": u_node, "max_displacement_location_mm": coords[u_node].tolist(),
            "max_displacement_vector_mm":np.asarray(fields['displacements'][u_node]).tolist(),
            "max_von_mises_mpa": ip_vm[peak], "peak_stress_element": peak[0], "peak_stress_integration_point": peak[1],
            "peak_element_centroid_mm": centroid.tolist(), "max_strain_norm": strain_norm,
            "reaction_force_n": reaction.tolist(), "reaction_moment_n_mm": rmoment.tolist(),
            "equilibrium_force_scale_n":force_scale,"equilibrium_scale_basis":scale_basis,
            "reaction_definition": "CalculiX RF minus CLOAD and equivalent bolt attachment forces, restricted to supported translations; generalized tightening/lock reactions are internal, not fixture reactions",
            "force_residual_n": force_residual.tolist(), "moment_residual_n_mm": moment_residual.tolist(),
            "force_balance_relative_error": force_error, "moment_balance_relative_error": moment_error,
            "minimum_bbox_extent_mm": float(np.min(np.ptp(np.array(list(coords.values())), axis=0)))}
    if fields.get('_source_directory'):
        from .mesh_diagnostics import element_quality
        result['peak_mesh_quality']=element_quality(fields['_source_directory'],peak[0])
    corners=np.array([coords[n] for n in tets[peak[0]][:4]])
    edges=[float(np.linalg.norm(corners[i]-corners[j])) for i in range(4) for j in range(i)]
    result['peak_element_corner_edges_mm']={'minimum':min(edges),'mean':float(np.mean(edges)),'maximum':max(edges)}
    if meta.get('reference_support'):
        from .reference_support import summarize as reference_summary
        result.update(reference_summary(meta['reference_support'],coords,fields['displacements'],fields['reactions'],forces,meta))
        result['reaction_definition']='Reference equations remove rigid motion only; their forces are numerical diagnostics, not physical fixture or actuator reactions'
    if case is not None:
        from .probes import evaluate_probes,evaluate_context
        if probe_context is None:result['probes']=evaluate_probes(case,mesh,fields)
        else:
            fields['_probe_context']=probe_context
            result['probes']=evaluate_context(probe_context,lambda n:fields['displacements'][n])
        from .materials import context,strength_summary
        ctx=context(case,meta,tets);fields['_strength_context']=ctx
        result.update(strength_summary(list(fields['stresses'].values()),list(fields['stresses']),ctx))
        if case.get('stress_regions'):
            from .stress_regions import region_context, summarize_regions
            regions=region_context(case,mesh,list(fields['stresses']))
            fields['_stress_region_context']=regions
            result['stress_regions']=summarize_regions(list(fields['stresses'].values()),list(fields['stresses']),ctx,regions)
        if result['strength_peak']:
            nodes=tets[result['strength_peak']['element']][:4]
            result['strength_peak']['element_centroid_mm']=np.mean([coords[n] for n in nodes],axis=0).tolist()
            if fields.get('_source_directory'):
                result['strength_peak']['mesh_quality']=element_quality(fields['_source_directory'],result['strength_peak']['element'])
    return result
