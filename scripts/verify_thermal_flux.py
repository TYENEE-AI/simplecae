"""Nine bounded native solves: report flux errors, never certify flux accuracy.

References are ideal homogeneous conduction, not product material data.
Original 1e-4 C / 1e-3 W/m² reference targets are retained in every row.
Run through the public analysis API so temperature gates/compact storage apply.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from simplecae.api import analyze_case
from simplecae.case import sha256, write_json
from simplecae.loads import tetra10_basis
from simplecae.thermal_solid import signal


def reference(name, xyz):
    """Independent analytic T and vector q, coordinates in mm."""
    q = np.zeros_like(xyz, dtype=float)
    if name == "slab_source":
        x = xyz[..., 0] * .001
        t = 20. + 1e6 / 4. * x * (.02 - x)
        q[..., 0] = 1e6 * (x - .01)
    elif name == "cylinder_axial":
        t = 20. + 1.6 * xyz[..., 2]
        q[..., 2] = -3200.
    elif name == "cylinder_power":
        # Fixed total 0.25 W over the exact CAD disk, r=8 mm.
        flux = .25 / (np.pi * .008**2)
        t = 20. + flux / 2. * xyz[..., 0] * .001
        q[..., 0] = -flux
    else:
        raise ValueError(name)
    return t, q


def build_case(root, name):
    import gmsh
    from simplecae import gmsh_runtime
    step = root / (name + ".step")
    gmsh_runtime.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(name)
        if name == "slab_source":
            gmsh.model.occ.addBox(0, 0, 0, 20, 10, 10)
            bbox, sizes, axis, length = [[0, 0, 0], [20, 10, 10]], [5., 3.5, 2.5], "x", 20.
        elif name == "cylinder_axial":
            gmsh.model.occ.addCylinder(0, 0, 0, 0, 0, 50, 5)
            bbox, sizes, axis, length = [[-5, -5, 0], [5, 5, 50]], [3., 2.4, 1.8], "z", 50.
        elif name == "cylinder_power":
            gmsh.model.occ.addCylinder(0, 0, 0, 20, 0, 0, 8)
            bbox, sizes, axis, length = [[0, -8, -8], [20, 8, 8]], [4., 3., 2.25], "x", 20.
        else:
            raise ValueError(name)
        gmsh.model.occ.synchronize()
        gmsh.write(str(step))
    finally:
        gmsh_runtime.finalize()
    ends = [{"name": label, "target": label, "basis": "Ideal analytic boundary",
             "type": "temperature", "temperature_c": 20.,
             "selector": {"type": "plane", "axis": axis, "position_mm": at}}
            for label, at in (("cold", 0.), ("input", length))]
    if name == "cylinder_axial":
        ends[1]["temperature_c"] = 100.
    if name == "cylinder_power":
        ends[1].pop("temperature_c")
        ends[1].update(type="heat_power", total_heat_w=.25)
    # Exercise fail, unresolved near-limit and pass without changing any gate.
    limit = {"slab_source": 42., "cylinder_axial": 100.05, "cylinder_power": 35.}[name]
    c = {
        "schema_version": "thermal-solid-1.0", "mode": "steady",
        "model": {"path": str(step), "units": "mm", "expected_bbox_mm": bbox},
        "mesh": {"sizes_mm": sizes, "max_elements": 20000, "preserve_boundary_nodes": True},
        "material": {"name": "Analytic reference", "basis": "Constant k=2, not product material data",
                     "conductivity_w_mk": 2., "temperature_range_c": [0., 200.]},
        "boundaries": ends,
        "criteria": [{"id": "temperature", "target": "selected body",
                      "region": {"type": "body"}, "max_temperature_c": limit}],
        "assumptions": ["Constant homogeneous isotropic conductivity; other faces insulated"],
        "not_assessed": ["Physical properties, mounting and environment"],
        "conditions": {"properties_verified": False, "boundaries_verified": False},
        "provenance": {"task_id": name, "revision": "reference"},
    }
    if name == "slab_source":
        c["volumetric_heat_w_m3"] = 1e6
    return c


def error_row(name, directory, level, h):
    with np.load(directory / "mesh.npz", allow_pickle=False) as m, \
         np.load(directory / "thermal-fields.npz", allow_pickle=False) as f:
        lookup = {int(n): i for i, n in enumerate(m["node_ids"])}
        conn = np.array([[lookup[int(n)] for n in row] for row in m["connectivity"]])
        ip = np.einsum("qi,eia->eqa", tetra10_basis(m["native_volume_quadrature_points"]), m["xyz"][conn])
        t_exact, _ = reference(name, m["xyz"])
        _, q_exact = reference(name, ip)
        q = f["flux_w_m2"][-1].reshape(q_exact.shape)
        error = q - q_exact
        # Retain component maxima (same metric as the original reference),
        # vector error, RMS and worst location. No percentiles discard peaks.
        index = np.unravel_index(np.argmax(np.abs(error)), error.shape)
        scale = {"slab_source": 10000., "cylinder_axial": 3200.,
                 "cylinder_power": .25 / (np.pi * .008**2)}[name]
        maximum = float(np.max(np.abs(error)))
        temperature_error = float(np.max(np.abs(f["temperature_c"][-1] - t_exact)))
        weights = m["native_volume_quadrature_measures_mm3"]
        rms = float(np.sqrt(np.sum(np.sum(error**2, axis=-1) * weights) / np.sum(weights)))
        return {
            "mesh_mm": h, "elements": len(conn), "nodes": len(lookup),
            "temperature_error_c": temperature_error,
            "temperature_limit_c": 1e-4, "temperature_reference_passed": temperature_error < 1e-4,
            "flux_error_w_m2": maximum, "flux_limit_w_m2": 1e-3,
            "pointwise_flux_passed": maximum < 1e-3,
            "reference_flux_scale_w_m2": scale, "relative_to_reference_scale": maximum / scale,
            "max_vector_error_w_m2": float(np.max(np.linalg.norm(error, axis=-1))),
            "volume_weighted_vector_rms_w_m2": rms,
            "worst_location_mm": ip[index[0], index[1]].tolist(),
            "worst_element": int(m["element_ids"][index[0]]),
            "worst_integration_point": int(index[1]) + 1,
            "worst_component": "xyz"[index[2]],
            "energy_passed": level["energy_passed"], "energy_errors_w": level["energy_errors_w"],
            "energy_tolerance_w": level["energy_tolerance_w"],
            "quadrature_passed": level["quadrature_passed"],
            "field_sha256": sha256(directory / "thermal-fields.npz"),
            "mesh_sha256": sha256(directory / "mesh.npz"),
        }


def run(root, names=None, mesh_scale=1.):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    study = {"meaning": "Small analytic sensitivity study; no general local-flux accuracy qualification.",
             "original_flux_limit_w_m2": .001, "flux_acceptance_claim": False, "cases": {}}
    expected = {"slab_source": "fail_under_stated_model", "cylinder_axial": "indeterminate",
                "cylinder_power": "pass_under_stated_model"}
    for name in (names or expected):
        c = build_case(root, name)
        c["mesh"]["sizes_mm"] = [h * mesh_scale for h in c["mesh"]["sizes_mm"]]
        cp = root / (name + ".case.json")
        write_json(cp, c)
        result = analyze_case(cp, root / name, predict_capacity=False)
        rows = [error_row(name, root / name / level["directory"], level, h)
                for level, h in zip(result["levels"], c["mesh"]["sizes_mm"])]
        s = signal(result)
        gates = result.get("verification", {})
        qualified = bool(gates) and all(v for k, v in gates.items() if k.endswith("_passed"))
        safe_expected = expected[name] if qualified else "indeterminate"
        entry = {"case_sha256": sha256(cp), "model_sha256": sha256(Path(c["model"]["path"])),
                 "rows": rows, "status": result["status"], "expected_temperature_status": expected[name],
                 "expected_status_after_numerical_gates": safe_expected,
                 "temperature_decision_correct": result["status"] == safe_expected,
                 "no_product_pass": result["whole_product_pass_available"] is False,
                 "design_hypothesis_present": any(f["kind"] == "design_hypothesis" for f in s["feedback"]),
                 "signal": s, "verification": result.get("verification"), "error": result.get("error")}
        if len(rows) == 3:
            entry["max_flux_error_decreases_each_refinement"] = all(
                b["flux_error_w_m2"] <= a["flux_error_w_m2"] for a, b in zip(rows, rows[1:]))
            entry["rms_error_decreases_each_refinement"] = all(
                b["volume_weighted_vector_rms_w_m2"] <= a["volume_weighted_vector_rms_w_m2"]
                for a, b in zip(rows, rows[1:]))
        study["cases"][name] = entry
        write_json(root / "study.json", study)
        print(json.dumps({"case": name, "status": result["status"], "rows": rows}), flush=True)
    study["workflow_checks_passed"] = all(
        len(e["rows"]) == 3 and e["temperature_decision_correct"] and e["no_product_pass"]
        and e["design_hypothesis_present"] == (e["status"] == "fail_under_stated_model")
        for e in study["cases"].values())
    write_json(root / "study.json", study)
    return study


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case", choices=("slab_source", "cylinder_axial", "cylinder_power"), action="append")
    parser.add_argument("--mesh-scale", type=float, default=1.)
    args = parser.parse_args()
    if not np.isfinite(args.mesh_scale) or args.mesh_scale <= 0:
        parser.error("--mesh-scale must be finite and positive")
    if not run(args.out, args.case, args.mesh_scale)["workflow_checks_passed"]:
        raise SystemExit(1)
