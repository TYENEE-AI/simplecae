"""Public analytic verification cases, not experimental load-capacity evidence."""
from __future__ import annotations
from .defaults import DEFAULT_NATIVE_TIMEOUT
import copy
from pathlib import Path
import numpy as np

from .case import CONDITIONS, write_json
from .geometry import session
from .workflow import analyze


def bar_case(name, force, sizes):
    return {"schema_version": "1.0", "model": {"path": f"{name}.step", "expected_bbox_mm": [[0,-5,-5],[100,5,5]]},
            "material": {"name": "analytic_isotropic_reference", "youngs_modulus_mpa": 200000., "poisson_ratio": .3,
                         "yield_strength_mpa": 200., "failure_criterion": "von_mises_yield", "source": "Prescribed mathematical benchmark parameters; not a material certificate."},
            "supports": [{"name": "clamp", "selector": {"type": "plane", "axis": "x", "position_mm": 0.}}],
            "loads": [{"name": "end_face", "selector": {"type": "plane", "axis": "x", "position_mm": 100.}, "total_force_n": force}],
            "criteria": {"yield_safety_factor": 2., "max_displacement_mm": .3},
            "mesh": {"sizes_mm": sizes}, "conditions": {k: True for k in CONDITIONS},
            "notes": "Known synthetic model. Full clamp includes Poisson end effects; compare stress away from both ends."}


def generate_examples(out: Path):
    out.mkdir(parents=True, exist_ok=False)
    with session() as g:
        g.model.occ.addBox(0, -5, -5, 100, 10, 10)
        g.model.occ.synchronize()
        g.write(str(out / "axial.step"))
        g.write(str(out / "cantilever.step"))
    axial = bar_case("axial", [1000.,0.,0.], [5.,4.,3.])
    beam = bar_case("cantilever", [0.,0.,-100.], [5.,4.,3.])
    write_json(out / "axial.case.json", axial)
    write_json(out / "cantilever.case.json", beam)
    doubled = copy.deepcopy(beam)
    doubled["loads"][0]["total_force_n"] = [0.,0.,-200.]
    write_json(out / "cantilever-double.case.json", doubled)
    with session() as g:
        wall = g.model.occ.addBox(0, -10, 0, 4, 20, 44)
        shelf = g.model.occ.addBox(0, -10, 0, 44, 20, 4)
        shape, _ = g.model.occ.fuse([(3, wall)], [(3, shelf)])
        g.model.occ.synchronize()
        root_edges = [e for d, e in g.model.getEntities(1)
                      if np.allclose(g.model.occ.getCenterOfMass(1,e), [4,0,4], atol=1e-6)]
        if len(root_edges) != 1:
            raise RuntimeError("demo inner fillet edge was not uniquely identified")
        g.model.occ.fillet([shape[0][1]], root_edges, [2.])
        g.model.occ.synchronize()
        g.write(str(out / "bracket.step"))
    bracket = {"schema_version": "1.0", "model": {"path": "bracket.step", "expected_bbox_mm": [[0,-10,0],[44,10,44]]},
               "material": {"name": "assumed_aluminum_example", "youngs_modulus_mpa": 69000., "poisson_ratio": .33,
                            "yield_strength_mpa": 200., "failure_criterion": "von_mises_yield", "source": "Illustrative assumed values; replace with verified material data."},
               "supports": [{"name": "ideal_back_clamp", "selector": {"type": "plane", "axis": "x", "position_mm": 0.}}],
               "loads": [{"name": "shelf_traction", "selector": {"type": "plane", "axis": "z", "position_mm": 4.}, "total_force_n": [0.,0.,-50.]}],
               "criteria": {"yield_safety_factor": 2., "max_displacement_mm": .2},
               "mesh": {"sizes_mm": [3.,2.4,1.8]},
               "conditions": {"material_verified": False, "dimensions_verified": True,
                              "supports_represent_actual_mounting": False, "load_pattern_verified": False,
                              "self_weight_negligible": True},
               "notes": "Illustrative rounded L-bracket with ideal full-back support and uniform shelf traction. Actual mounting and material not supplied; capacity must be withheld."}
    write_json(out / "bracket.case.json", bracket)
    return out


def load_final_fields(result):
    directory = Path(result["levels"][-1]["directory"])
    return np.load(directory / "mesh.npz"), np.load(directory / "fields.npz")


def validate_benchmarks(out: Path, ccx=None, timeout=DEFAULT_NATIVE_TIMEOUT):
    out.mkdir(parents=True, exist_ok=False)
    examples = generate_examples(out / "inputs")
    results = {}
    for name in ("axial", "cantilever", "cantilever-double"):
        results[name] = analyze(examples / f"{name}.case.json", out / name, ccx, timeout, preview=name != "cantilever-double")
        if results[name]["status"] == "invalid":
            report = {"passed": False, "failed_case": name, "error": results[name]["error"], "evidence_kind": "analytic numerical verification"}
            write_json(out / "validation.json", report)
            return report
    checks = []
    def check(name, actual, expected, tolerance, description):
        error = abs(actual-expected)/max(abs(expected), 1e-30)
        checks.append({"name": name, "actual": actual, "expected": expected,
                       "relative_error": error, "relative_tolerance": tolerance,
                       "passed": error <= tolerance, "description": description})
    for name, result in results.items():
        for i, level in enumerate(result["levels"]):
            r = level["results"]
            check(f"{name} force equilibrium level {i+1}", r["force_balance_relative_error"], 0., 0., "See absolute threshold field below")
            checks[-1].update(passed=r["force_balance_relative_error"] <= 5e-4, relative_error=None,
                              relative_tolerance=None, absolute_tolerance=5e-4)
            check(f"{name} moment equilibrium level {i+1}", r["moment_balance_relative_error"], 0., 0., "Normalized by sum |F| times body diagonal")
            checks[-1].update(passed=r["moment_balance_relative_error"] <= 5e-4, relative_error=None,
                              relative_tolerance=None, absolute_tolerance=5e-4)
    for name in ("axial", "cantilever"):
        mesh, fields = load_final_fields(results[name])
        ids, xyz, disp = mesh["node_ids"], mesh["xyz"], fields["displacements"]
        displacement = {int(n): u for n, u in zip(fields["node_ids"], disp)}
        tips = [int(n) for n, p in zip(ids, xyz) if abs(p[0]-100.) < 1e-6]
        component = 0 if name == "axial" else 2
        actual = abs(float(np.mean([displacement[n][component] for n in tips])))
        expected = .005 if name == "axial" else .2
        check(f"{name} end mean displacement", actual, expected, .05,
              "PL/EA" if name == "axial" else "PL^3/(3EI), L=100 mm, b=h=10 mm, I=833.333 mm^4; slender beam approximation")
        point = {int(n): p for n, p in zip(ids, xyz)}
        stresses = {}
        for (e, _), s in zip(fields["stress_ids"], fields["stresses"]):
            stresses.setdefault(int(e), []).append(s)
        errors = []
        for e, conn in zip(mesh["element_ids"], mesh["connectivity"]):
            p = np.mean([point[int(n)] for n in conn[:4]], axis=0)
            if 30 < p[0] < 70 and (name == "axial" or abs(p[2]) > 3.5):
                sx = abs(float(np.mean(stresses[int(e)], axis=0)[0]))
                target = 10. if name == "axial" else abs(100.*(100.-p[0])*p[2]/(10000./12.))
                errors.append(abs(sx-target)/target)
        if not errors:
            raise RuntimeError("benchmark has no eligible interior stress samples")
        check(f"{name} mean interior stress relative error", float(np.mean(errors)), 0., 0., "Interior element means; omit constrained-end singularities and loading end effects")
        checks[-1].update(passed=float(np.mean(errors)) <= .08, relative_error=None, relative_tolerance=None, absolute_tolerance=.08)
        ulevels = [l["results"]["max_displacement_mm"] for l in results[name]["levels"]]
        changes = [abs(b-a)/b for a, b in zip(ulevels, ulevels[1:])]
        checks.append({"name": f"{name} displacement mesh convergence", "relative_changes": changes,
                       "relative_tolerance": .05, "passed": all(v <= .05 for v in changes)})
    a = results["cantilever"]["levels"][-1]["results"]
    b = results["cantilever-double"]["levels"][-1]["results"]
    for metric in ("max_displacement_mm", "max_von_mises_mpa"):
        check(f"load doubling {metric}", b[metric]/a[metric], 2., 1e-4, "Same STEP and mesh; verify proportional linear response")
    checks.append({"name": "axial conditional body limit available", "passed": results["axial"]["assessment"]["conditional_body_limit"]["available"]})
    checks.append({"name": "whole installation explicitly unassessed", "passed": all(r["assessment"]["whole_installation_status"] == "not_assessed" for r in results.values())})
    report = {"passed": all(x["passed"] for x in checks), "checks": checks,
              "evidence_kind": "analytic numerical verification; not experimental material or product validation",
              "scope": "C3D10 straight-sided STEP bars: axial and bending displacements, interior stress, equilibrium and load scaling",
              "not_validated": ["General STEP geometry robustness", "Physical bracket load capacity", "Buckling", "Connections", "Printed materials"],
              "cases": {k: str((out / k / "result.json").resolve()) for k in results}}
    write_json(out / "validation.json", report)
    return report
