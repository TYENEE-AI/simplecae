"""CalculiX elastic eigenvalue buckling; no nonlinear collapse/imperfection claim."""
from __future__ import annotations
from pathlib import Path
import re
import numpy as np
from .case import write_json
from .solver import write_deck, execute


def cload_lines(forces):
    return [f"{n},{a+1},{float(v):.12g}" for n,f in sorted(forces.items()) for a,v in enumerate(f) if abs(v)>1e-14]


def write_buckling_deck(c, mesh, path):
    write_deck(c,mesh,path)
    prefix = path.read_text(encoding="ascii").split("*STEP\n",1)[0]
    fixed = {int(n):np.array(f) for n,f in mesh[-1].get("fixed_nodal_forces",{}).items()}
    variable = {n:f-fixed.get(n,np.zeros(3)) for n,f in mesh[3].items()}
    if not any(np.linalg.norm(f)>1e-12 for f in variable.values()):
        raise ValueError("buckling needs a nonzero scalable reference load pattern")
    lines = [prefix.rstrip()]
    if fixed:
        lines += ["*STEP", "*STATIC,SOLVER=SPOOLES", "*CLOAD,OP=NEW"] + cload_lines(fixed) + ["*END STEP"]
    lines += ["*STEP", "*BUCKLE,SOLVER=SPOOLES", f"{c['buckling'].get('modes',3)},1e-6", "*CLOAD,OP=NEW"]
    lines += cload_lines(variable)
    lines += ["*NODE PRINT,NSET=NALL", "U", "*NODE FILE", "U", "*END STEP"]
    path.write_text("\n".join(lines)+"\n",encoding="ascii")


def parse_buckling_dat(path):
    rows, modes = [], {}
    eigen_table, mode, displacements = False, None, False
    for line in path.read_text(encoding="utf-8",errors="replace").splitlines():
        compact = re.sub(r"\s+","",line).upper()
        if "BUCKLINGFACTOROUTPUT" in compact or "EIGENVALUEOUTPUT" in compact:
            eigen_table, mode, displacements = True, None, False
            continue
        match = re.search(r"EIGENVALUENUMBER(\d+)",compact)
        if match:
            mode, eigen_table, displacements = int(match.group(1)), False, False
            modes[mode] = {}
            continue
        if line.strip().lower().startswith("displacements ("):
            displacements = True
            continue
        try:
            values = [float(p.replace("D","E")) for p in line.split()]
        except ValueError:
            continue
        if eigen_table and len(values) >= 2 and values[0] == int(values[0]):
            rows.append({"mode":int(values[0]), "load_factor":float(values[1])})
        elif mode is not None and displacements and len(values)==4:
            modes[mode][int(values[0])] = np.array(values[1:])
    if not rows or any(not np.isfinite(row["load_factor"]) for row in rows):
        raise RuntimeError("no finite buckling factors found in DAT")
    return rows,modes


def run_buckling(c,mesh,out:Path,ccx,timeout):
    inp = out/"buckling.inp"
    write_buckling_deck(c,mesh,inp)
    solver = execute(ccx,inp,timeout,analysis_type="buckling")
    factors,modes = parse_buckling_dat(inp.with_suffix(".dat"))
    node_ids = sorted(mesh[0])
    available = []
    for m,field in modes.items():
        if set(field) != set(node_ids):
            raise RuntimeError(f"buckling mode {m} has incomplete node coverage")
        values = np.array([field[n] for n in node_ids])
        if not np.all(np.isfinite(values)) or np.max(np.linalg.norm(values,axis=1))<=0:
            raise RuntimeError("invalid buckling eigenvector")
        values /= np.max(np.linalg.norm(values,axis=1))
        np.savez_compressed(out/f"buckling-mode-{m:02d}.npz",node_ids=node_ids,displacements=values)
        available.append(m)
    positive = [f for f in factors if f["load_factor"]>0]
    if set(available) != {f["mode"] for f in factors}:
        raise RuntimeError("buckling factors and eigenvector coverage do not match")
    result = {"analysis":"elastic_eigenvalue_buckling", "factors":factors,
              "lowest_positive_factor":min((f["load_factor"] for f in positive),default=None),
              "available_modes":available,"solver":solver,
              "limitations":["Linear bifurcation estimate of the stated ideal model, not nonlinear collapse capacity.",
                              "Initial imperfections, plasticity and changing contact are not included.",
                              "Negative factors correspond to reversed load direction; no positive factor among requested modes does not prove stability."]}
    write_json(out/"buckling.json",result)
    return result
