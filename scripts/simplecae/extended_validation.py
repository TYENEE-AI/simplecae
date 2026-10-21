"""Reproducible numerical checks beyond the original axial/bending baseline."""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from pathlib import Path
import copy
import math
import numpy as np
from .benchmarks import bar_case, generate_examples
from .case import write_json
from .geometry import session
from .workflow import analyze


def generate_advanced(out):
    out.mkdir(parents=True,exist_ok=False)
    generate_examples(out/"base")
    with session() as g:
        g.model.occ.addBox(0,-5,-5,300,10,10)
        g.model.occ.synchronize()
        g.write(str(out/"column.step"))
    column=bar_case("column",[-100.,0.,0.],[5.,4.,3.])
    column["schema_version"]="2.0"
    column["model"]={"path":"column.step","expected_bbox_mm":[[0,-5,-5],[300,5,5]]}
    column["loads"][0]["selector"]["position_mm"]=300.
    column["buckling"]={"enabled":True,"modes":3,"safety_factor":2.}
    write_json(out/"column.case.json",column)
    preload=copy.deepcopy(column)
    preload["loads"].append({"name":"fixed_compression","selector":copy.deepcopy(column["loads"][0]["selector"]),"total_force_n":[-20.,0.,0.],"scalable":False})
    write_json(out/"preloaded-column.case.json",preload)
    gravity=bar_case("cantilever",[0.,0.,-100.],[5.,4.,3.])
    gravity["schema_version"]="2.0"
    gravity["model"]["path"]="base/cantilever.step"
    gravity["material"]["density_kg_m3"]=7800.
    gravity["gravity"]={"acceleration_m_s2":[0.,0.,-9.80665]}
    gravity["conditions"]["self_weight_negligible"]=False
    write_json(out/"gravity-beam.case.json",gravity)
    ownweight=copy.deepcopy(gravity)
    ownweight["loads"]=[]
    write_json(out/"selfweight-only.case.json",ownweight)
    moment=bar_case("cantilever",[0.,0.,0.],[5.,4.,3.])
    moment["schema_version"]="2.0"
    moment["model"]["path"]="base/cantilever.step"
    moment["loads"][0]["total_moment_n_mm"]=[0.,1000.,0.]
    write_json(out/"end-moment.case.json",moment)
    return out


def tip_mean(result,axis):
    directory=Path(result["levels"][-1]["directory"])
    mesh=np.load(directory/"mesh.npz")
    fields=np.load(directory/"fields.npz")
    tip=float(mesh["xyz"][:,0].max())
    ids={int(n) for n,p in zip(mesh["node_ids"],mesh["xyz"]) if abs(p[0]-tip)<1e-6}
    return abs(float(np.mean([u[axis] for n,u in zip(fields["node_ids"],fields["displacements"]) if int(n) in ids])))


def validate_extended(out,ccx=None,timeout=DEFAULT_NATIVE_TIMEOUT):
    out.mkdir(parents=True,exist_ok=False)
    inputs=generate_advanced(out/"inputs")
    results={}
    checks=[]
    for name in ("column","preloaded-column","gravity-beam","selfweight-only","end-moment"):
        result=analyze(inputs/f"{name}.case.json",out/name,ccx,timeout,preview=True)
        results[name]=result
        checks.append({"name":name+" complete numerical solve","passed":result["status"]!="invalid","error":result.get("error")})
    def compare(name,actual,expected,tol):
        err=abs(actual-expected)/max(abs(expected),1e-30)
        checks.append({"name":name,"actual":actual,"expected":expected,"relative_error":err,"relative_tolerance":tol,"passed":err<=tol})
    if all(r["status"]!="invalid" for r in results.values()):
        ei=200000*(10000/12)
        critical=math.pi**2*ei/(4*300**2)
        compare("Euler cantilever-column load factor",results["column"]["assessment"]["buckling"]["lowest_positive_load_factor"],critical/100,.03)
        compare("Euler preloaded-column incremental load factor",results["preloaded-column"]["assessment"]["buckling"]["lowest_positive_load_factor"],(critical-20)/100,.03)
        weight=.078*9.80665
        compare("self-weight resultant",-results["selfweight-only"]["levels"][-1]["mesh"]["applied_force_n"][2],weight,1e-6)
        compare("gravity-only tip displacement",tip_mean(results["selfweight-only"],2),weight*100**3/(8*ei),.05)
        compare("gravity plus payload tip displacement",tip_mean(results["gravity-beam"],2),.2+weight*100**3/(8*ei),.05)
        compare("end-moment tip displacement",tip_mean(results["end-moment"],2),1000*100**2/(2*ei),.05)
        compare("end-moment resultant",results["end-moment"]["levels"][-1]["mesh"]["applied_moment_n_mm"][1],1000.,1e-8)
        checks.append({"name":"selfweight-only does not invent a payload capacity","passed":not results["selfweight-only"]["assessment"]["conditional_body_limit"]["available"]})
        for name,result in results.items():
            for i,level in enumerate(result["levels"]):
                checks.append({"name":f"{name} force/moment equilibrium {i+1}","passed":max(level["results"]["force_balance_relative_error"],level["results"]["moment_balance_relative_error"])<=5e-4})
            if result["assessment"].get("buckling"):
                checks.append({"name":name+" eigenvalue mesh convergence","passed":result["assessment"]["buckling"]["mesh_converged"]})
                modes=result["levels"][-1]["buckling"]["available_modes"]
                checks.append({"name":name+" all requested mode vectors","passed":len(modes)==3})
    proof={"passed":all(c["passed"] for c in checks),"checks":checks,
           "evidence_kind":"analytic numerical verification; no manufactured part or installation validation",
           "cases":{name:str((out/name/"result.json").resolve()) for name in results},
           "sources":["Euler fixed-free column Pcr=pi^2 EI/(4L^2)","Euler-Bernoulli beam end force/couple/uniform body weight", "CalculiX BUCKLE manual"]}
    write_json(out/"validation.json",proof)
    return proof
