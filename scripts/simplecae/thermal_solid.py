"""Bounded linear single-solid conduction with spatial/time qualification."""
from __future__ import annotations
from .defaults import DEFAULT_NATIVE_TIMEOUT
from .defaults import DEFAULT_THERMAL_ELEMENTS, DEFAULT_THERMAL_FIELD_VALUES

import copy
import html
import json
import math
from pathlib import Path
import shutil

import numpy as np

from .case import sha256, write_json
from .geometry import make_mesh, select_faces
from .signals import digest
from .thermal_fields import region_history
from . import thermal_solid_solver as native

SCHEMA = "thermal-solid-1.0"
SPACE_TOLERANCE_C = .05
TIME_TOLERANCE_C = .05
GUARD_C = .10001
NOT_ASSESSED = ["Radiation and fluid flow; convection coefficient is supplied, not predicted.",
                "Thermal contact between separate bodies; anisotropic or temperature-dependent properties.",
                "Thermal stress, strength at temperature, hot creep, lifetime and product approval.",
                "Actual manufacturing properties, boundary conditions and physical temperature tests.",
                "Pointwise heat-flux accuracy or local flux limits; temperature qualification does not validate them."]


def schema():
    from .schemas import obj, arr, enum, S, P, N, B, V
    temp = {"type": "number", "minimum": -273.15}
    selector = {"oneOf": [
        obj({"type": {"const": "plane"}, "axis": enum("x", "y", "z"),
             "position_mm": N, "tolerance_mm": P}, ("type", "axis", "position_mm")),
        obj({"type": {"const": "face_ids"}, "ids": dict(arr({"type": "integer", "minimum": 1}, 1), uniqueItems=True),
             "geometry_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
            ("type", "ids", "geometry_sha256")),
        obj({"type":{"const":"interface"},"name":S}, ("type","name"))]}
    base = {"name": S, "target": S, "basis": S, "selector": selector}
    boundaries = []
    for kind, fields in (
            ("temperature", {"temperature_c": temp}),
            ("heat_flux", {"flux_w_m2": N}),
            ("heat_power", {"total_heat_w": N}),
            ("convection", {"ambient_temperature_c": temp, "coefficient_w_m2k": P})):
        fields = base | {"type": {"const": kind}} | fields
        boundaries.append(obj(fields, fields))
    region = {"oneOf": [obj({"type": {"const": "body"}}, ("type",)),
                         obj({"type": {"const": "surface"}, "selector": selector}, ("type", "selector"))]}
    criterion = obj({"id": S, "target": S, "region": region,
                     "min_temperature_c": temp, "max_temperature_c": temp}, ("id", "target", "region"))
    criterion["anyOf"] = [{"required": ["min_temperature_c"]}, {"required": ["max_temperature_c"]}]
    local_refinement = obj({"name": S, "selector": selector,
        "size_factor": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "distance_mm": P, "sampling": {"type": "integer", "minimum": 10, "maximum": 500}},
        ("name", "selector", "size_factor", "distance_mm"))
    return obj({
        "schema_version": {"const": SCHEMA}, "mode": enum("steady", "transient"),
        "model": obj({"path": S, "units": {"const": "mm"}, "interface_manifest":S,
                      "expected_bbox_mm": dict(arr(V, 2), maxItems=2)}, ("path", "units", "expected_bbox_mm")),
        "material": obj({"name": S, "basis": S, "conductivity_w_mk": P, "density_kg_m3": P,
                         "specific_heat_j_kgk": P, "temperature_range_c": dict(arr(temp, 2), maxItems=2)},
                        ("name", "basis", "conductivity_w_mk", "temperature_range_c")),
        "boundaries": dict(arr({"oneOf": boundaries}), maxItems=64),
        "volumetric_heat_w_m3": N, "initial_temperature_c": temp, "duration_s": P,
        "time_steps": {"type": "integer", "minimum": 4, "maximum": 200},
        "mesh": obj({"sizes_mm": dict(arr(P, 3), maxItems=3),
                     "max_elements": {"type": "integer", "minimum": 1},
                     "max_field_values": {"type": "integer", "minimum": 1},
                     "local_refinements": arr(local_refinement),
                     "preserve_boundary_nodes": B}, ("sizes_mm",)),
        "accuracy": obj({"temperature_tolerance_c": P, "basis": S},
                        ("temperature_tolerance_c", "basis")),
        "criteria": dict(arr(criterion, 1), maxItems=32),
        "assumptions": arr(S, 1), "not_assessed": arr(S),
        "conditions": obj({"properties_verified": B, "boundaries_verified": B},
                          ("properties_verified", "boundaries_verified")),
        "provenance": obj({"task_id": S, "revision": S, "generator": S}, ("task_id",)),
    }, ("schema_version", "mode", "model", "material", "boundaries", "mesh", "criteria",
        "assumptions", "not_assessed", "conditions", "provenance"))


def read_case(path):
    import jsonschema
    path = Path(path).resolve()
    case = json.loads(path.read_text(encoding="utf-8-sig"))
    try:
        jsonschema.Draft202012Validator(schema()).validate(case)
    except jsonschema.ValidationError as exc:
        raise ValueError("Solid thermal input: " + exc.message) from None
    def finite(x):
        if isinstance(x, float) and not math.isfinite(x):
            raise ValueError("Thermal inputs must be finite")
        if isinstance(x, dict):
            for v in x.values(): finite(v)
        if isinstance(x, list):
            for v in x: finite(v)
    finite(case)
    model = Path(case["model"]["path"])
    model = (path.parent/model).resolve() if not model.is_absolute() else model.resolve()
    if model.suffix.lower() not in (".step", ".stp") or not model.is_file():
        raise ValueError("Solid thermal analysis requires an existing STEP single solid")
    case["model"]["path"] = str(model)
    if 'interface_manifest' in case['model']:
        manifest = (path.parent/Path(case['model']['interface_manifest'])).resolve()
        if not manifest.is_file(): raise ValueError('interface_manifest does not exist')
        case['model']['interface_manifest'] = str(manifest)
    sizes = case["mesh"]["sizes_mm"]
    case["mesh"].setdefault("max_elements", DEFAULT_THERMAL_ELEMENTS)
    if any(not math.nextafter(.35, -math.inf) <= b/a <= math.nextafter(.85, math.inf)
           for a, b in zip(sizes, sizes[1:])):
        raise ValueError("Three mesh sizes require successive ratios in [0.35, 0.85]")
    from .local_mesh import validate_refinements
    validate_refinements(case["mesh"])
    if "accuracy" in case and not case["accuracy"]["basis"].strip():
        raise ValueError("Temperature accuracy needs a nonempty task-specific basis")
    lo, hi = case["material"]["temperature_range_c"]
    if lo >= hi:
        raise ValueError("Material temperature range must increase")
    for key in ("boundaries", "criteria"):
        ids = [x["name" if key == "boundaries" else "id"] for x in case[key]]
        if len(set(ids)) != len(ids):
            raise ValueError("Thermal region names/criterion IDs must be unique")
        if "__body__" in ids:
            raise ValueError("__body__ is reserved for whole-solid evidence")
    for c in case["criteria"]:
        if c.get("min_temperature_c", -273.15) > c.get("max_temperature_c", math.inf):
            raise ValueError("Contradictory temperature criterion")
    transient = case["mode"] == "transient"
    if not transient and not any(b['type'] in ('temperature','convection') for b in case['boundaries']):
        raise ValueError('Steady conduction requires a temperature reference or convection heat path before meshing; '
                         'mechanical fixation is not a thermal sink. Supply the actual heat boundary or use an explicitly justified transient model.')
    if transient:
        if not {"initial_temperature_c", "duration_s", "time_steps"} <= case.keys():
            raise ValueError("Transient analysis requires initial temperature, duration and time_steps")
        if not {"density_kg_m3", "specific_heat_j_kgk"} <= case["material"].keys():
            raise ValueError("Transient analysis requires density and specific heat")
        if any(b["type"] == "temperature" and b["temperature_c"] != case["initial_temperature_c"]
               for b in case["boundaries"]):
            raise ValueError("Initial state must match fixed temperatures; abrupt Dirichlet jumps are not yet qualified")
    elif any(k in case for k in ("initial_temperature_c", "duration_s", "time_steps")):
        raise ValueError("Steady analysis cannot silently ignore transient inputs")
    return case


def contract(case, realized_inputs):
    from .region_rules import region_contract
    value = copy.deepcopy(case)
    value.pop("mesh", None)
    value.pop("time_steps", None)
    value.pop("model", None)
    value["provenance"] = {"task_id": case["provenance"]["task_id"]}
    # Specified power survives permitted CAD edits. For prescribed flux/body
    # generation, changed total power is a changed task, not a cooling success.
    value["realized_heat_input_w"] = realized_inputs
    return value | region_contract(case)


def accuracy_policy(case):
    """Explicit task accuracy; defaults preserve historical strict evidence.

    Refinement differences are an engineering screen, not a proven error bound.
    A wider requested tolerance also widens the undecidable decision band.
    Numerical validity/energy/geometry gates never depend on this choice.
    """
    spec = case.get("accuracy")
    if spec is None:
        return {"spatial_tolerance_c": SPACE_TOLERANCE_C,
                "time_tolerance_c": TIME_TOLERANCE_C, "criterion_guard_c": GUARD_C}
    if not isinstance(spec, dict) or not isinstance(spec.get('basis'), str) or not spec['basis'].strip():
        raise ValueError("Temperature accuracy needs a nonempty task-specific basis")
    tol = spec.get("temperature_tolerance_c")
    if isinstance(tol, bool) or not isinstance(tol, (int, float)) or not math.isfinite(tol) or tol <= 0:
        raise ValueError("Temperature accuracy must be finite and positive")
    guard = max(GUARD_C, 2*tol+1e-5)
    if not math.isfinite(guard):
        raise ValueError("Temperature accuracy exceeds finite numerical range")
    return {"spatial_tolerance_c": tol, "time_tolerance_c": tol,
            "criterion_guard_c": guard}


def _level(case, directory, h, steps, ccx, timeout, progress=None):
    from .progress import emit
    emit(progress,'mesh',mesh_size_mm=h)
    directory.mkdir()
    mesh = make_mesh(case, h, directory, allow_free_body=True)
    count = steps if steps else 1
    field_values = (2*len(mesh[0])+12*len(mesh[1]))*(count+1)
    field_budget = case["mesh"].get("max_field_values", DEFAULT_THERMAL_FIELD_VALUES)
    if field_values > field_budget:
        write_json(directory/'resource-diagnostic.json', {'stage':'field_budget','status':'rejected',
            'geometry_sha256':mesh[-1]['geometry']['geometry_sha256'],'mesh_size_mm':h,
            'field_value_count':field_values,'max_field_values':field_budget})
        raise ValueError(f"Thermal field budget exceeded: {field_values} values > mesh.max_field_values={field_budget}; "
                         "choose local mesh allocation or an explicit resource budget after reviewing available memory; "
                         "do not drop required regions or time samples")
    patches, fixed = native.compile_boundaries(case, mesh, directory)
    for p in patches.values():
        if p["type"] == "heat_power":
            p.update(type="heat_flux", flux_w_m2=p["total_heat_w"]/p["area_m2"])
    deck = directory/"thermal.inp"
    native.write_deck(case, mesh, patches, fixed, deck, steps)
    from .solver import execute
    emit(progress,'thermal',mesh_size_mm=h)
    solver = execute(ccx, deck, timeout=timeout, analysis_type="thermal")
    emit(progress,'postprocess',mesh_size_mm=h)
    times = np.arange(1, steps+1)*case["duration_s"]/steps if steps else np.array([1.])
    frames = native.parse_fields(deck.with_suffix(".dat"), mesh[0], mesh[1], times)
    boundary_error = max([abs(f["temperature_c"][n]-t) for _, f in frames for n, t in fixed.items()] + [0.])
    boundary_tolerance = 1e-7 + max([abs(t) for t in fixed.values()] + [0.])*1e-6
    # DIRECT uses the requested fixed grid. DAT timestamps are rounded to seven
    # significant digits; differentiating those strings perturbs the heat rate.
    # Parsing has already required every native increment to match this grid.
    energy = native.energy_history(case, patches, fixed,
        [(float(t), fields) for t, (_, fields) in zip(times, frames)], directory)
    for entry, (printed_time, _) in zip(energy, frames):
        entry["printed_time_s"] = printed_time
    if not steps:
        times = np.array([0.])  # Steady native step time is not elapsed time.
        for entry in energy:
            entry["native_step_time"] = entry["time_s"]
            entry["time_s"] = None
    with np.load(directory/"mesh.npz", allow_pickle=False) as m:
        ids, xyz, elements = m["node_ids"].copy(), m["xyz"].copy(), m["element_ids"].copy()
        lookup = {int(n): i for i, n in enumerate(ids)}
        conn = np.array([[lookup[int(n)] for n in row] for row in m["connectivity"]])
        surface = np.array([[lookup[int(n)] for n in row] for row in m["surface_tri6"]])
        surface_ids = m["surface_face_ids"].copy()
    temperature = np.array([[f["temperature_c"][int(n)] for n in ids] for _, f in frames])
    rfl = np.array([[f["rfl_w"][int(n)] for n in ids] for _, f in frames])
    heat_flux = np.array([[f["flux_w_m2"][(int(e), ip)] for e in elements for ip in (1, 2, 3, 4)]
                         for _, f in frames])
    if steps:
        temperature = np.vstack((np.full(len(ids), case["initial_temperature_c"]), temperature))
        times = np.r_[0., times]
    np.savez_compressed(directory/"thermal-fields.npz", time_s=times, node_ids=ids,
                        temperature_c=temperature, conductive_rfl_w=rfl, flux_w_m2=heat_flux)
    histories = {"__body__": region_history(temperature, conn, xyz, elements, times)}
    prescribed = {}
    from .contact import surface_index
    owners = surface_index(mesh[1])
    surface_elements = np.array([owners[tuple(sorted(int(ids[i]) for i in tri[:3]))][0][0] for tri in surface])
    for criterion in case["criteria"]:
        if criterion["region"]["type"] == "body":
            histories[criterion["id"]] = histories["__body__"]
            region_nodes = set(map(int, ids))
        else:
            selected = select_faces(mesh[-1]["geometry"], criterion["region"]["selector"])
            mask = np.isin(surface_ids, selected)
            histories[criterion["id"]] = region_history(
                temperature, surface[mask], xyz, surface_elements[mask], times)
            region_nodes = set(map(int, ids[surface[mask]].ravel()))
        # Include shared-edge nodes, not merely identical face IDs: those
        # temperatures also belong to the requested full-face criterion.
        prescribed[criterion["id"]] = [
            {"boundary": p["name"], "temperature_c": p["temperature_c"]}
            for p in patches.values() if p["type"] == "temperature"
            and region_nodes.intersection(p["node_weights_m2"])]
    scale = max([abs(e["body_input_w"])+sum(abs(v) for v in e["surface_input_w"].values())
                 +e["reservoir_exchange_scale_w"]+abs(e["storage_rate_w"]) for e in energy] + [0.])
    tolerance = 1e-7+1e-5*scale  # Native DAT has seven significant digits.
    errors = {key: max(abs(e[key]) for e in energy) for key in (
        "balance_error_w", "max_free_node_residual_w", "max_conductive_field_excess_w")}
    volume = mesh[-1]["mesh_volume_mm3"]*1e-9
    volume_quadrature_error = max(e["independent_volume_integration_difference_m3"] for e in energy)/volume
    surface_quadrature_error = max((p['surface_quadrature_relative_error'] for p in patches.values()),default=0.)
    quadrature_error = max(volume_quadrature_error,surface_quadrature_error)
    realized = {p["name"]: float(f"{p['flux_w_m2']*p['area_m2']:.8g}")
                for p in patches.values() if p["type"] == "heat_flux" and "total_heat_w" not in p}
    if case.get("volumetric_heat_w_m3"):
        realized["__body__"] = float(f"{case['volumetric_heat_w_m3']*mesh[-1]['geometry']['volume_mm3']*1e-9:.8g}")
    return {"directory": directory.name, "mesh": mesh[-1], "solver": solver, "histories": histories,
            "energy": energy, "energy_errors_w": errors, "energy_tolerance_w": tolerance,
            "energy_passed": all(v <= tolerance for v in errors.values()),
            "boundary_temperature_error_c": boundary_error,
            "boundary_temperature_tolerance_c": boundary_tolerance,
            "boundary_temperature_passed": boundary_error <= boundary_tolerance,
            "quadrature_relative_error": quadrature_error, "quadrature_passed": quadrature_error <= .001,
            "volume_quadrature_relative_error":volume_quadrature_error,
            "surface_quadrature_relative_error":surface_quadrature_error,
            "realized_inputs": realized, "steps": steps, "time_s": times.tolist(),
            "prescribed_temperatures_in_regions": prescribed,
            "field_value_count": field_values, "field_value_budget": field_budget,
            "patches": [{k: v for k, v in p.items() if k not in ("face_mass_m2", "node_weights_m2", "element_sides")}
                        for p in patches.values()]}


def _assess(case, levels, time_differences):
    policy = accuracy_policy(case)
    space_tol, time_tol, guard = (policy[k] for k in
        ("spatial_tolerance_c", "time_tolerance_c", "criterion_guard_c"))
    spatial = []
    for a, b in zip(levels[:3], levels[1:3]):
        spatial.append(max(abs(x[k]-y[k]) for name in a["histories"]
                           for x, y in zip(a["histories"][name], b["histories"][name])
                           for k in ("min_temperature_c", "max_temperature_c")))
    all_extrema = [h for level in levels for h in level["histories"]["__body__"]]
    lo, hi = case["material"]["temperature_range_c"]
    verification = {
        "energy_balance_passed": all(x["energy_passed"] for x in levels),
        "boundary_temperature_passed": all(x["boundary_temperature_passed"] for x in levels),
        "quadrature_passed": all(x["quadrature_passed"] for x in levels),
        "spatial_refinement_passed": len(spatial) == 2 and max(spatial) <= space_tol,
        "spatial_extrema_differences_c": spatial, "spatial_tolerance_c": space_tol,
        "time_refinement_passed": (case["mode"] == "steady" or
            len(time_differences) == 2 and max(time_differences) <= time_tol),
        "time_field_differences_c": time_differences, "time_tolerance_c": time_tol,
        "property_range_passed": all(lo <= h["min_temperature_c"] and h["max_temperature_c"] <= hi
                                     for h in all_extrema)}
    valid = all(v for k, v in verification.items() if k.endswith("_passed"))
    criteria = {}
    for c in case["criteria"]:
        candidates = [h for level in levels for h in level["histories"][c["id"]]]
        cold = min(candidates, key=lambda h: h["min_temperature_c"])
        hot = max(candidates, key=lambda h: h["max_temperature_c"])
        lower_margin = cold["min_temperature_c"]-c.get("min_temperature_c", -math.inf)
        upper_margin = c.get("max_temperature_c", math.inf)-hot["max_temperature_c"]
        margin = min(lower_margin, upper_margin)
        bound, governing = ("min", cold) if lower_margin < upper_margin else ("max", hot)
        resolved = valid and abs(margin) > guard
        conflicts = [p for p in levels[0].get("prescribed_temperatures_in_regions", {}).get(c["id"], [])
                     if (c.get("min_temperature_c", -math.inf)-p["temperature_c"] > guard
                         or p["temperature_c"]-c.get("max_temperature_c", math.inf) > guard)]
        criteria[c["id"]] = dict(c, min_temperature_c=cold["min_temperature_c"],
            max_temperature_c=hot["max_temperature_c"], margin_c=margin,
            limits_c={k: c[k] for k in ("min_temperature_c", "max_temperature_c") if k in c},
            min_location_mm=cold["min_location_mm"], max_location_mm=hot["max_location_mm"],
            peak_time_s=hot["time_s"] if case["mode"] == "transient" else None, peak_element=hot["max_element"],
            peak_mesh_directory=next(x["directory"] for x in levels if hot in x["histories"][c["id"]]),
            governing_bound=bound,
            governing_temperature_c=governing[f"{bound}_temperature_c"],
            governing_location_mm=governing[f"{bound}_location_mm"],
            governing_element=governing[f"{bound}_element"],
            governing_time_s=governing["time_s"] if case["mode"] == "transient" else None,
            governing_mesh_directory=next(x["directory"] for x in levels if governing in x["histories"][c["id"]]),
            prescribed_boundary_conflicts=conflicts,
            status=("pass_under_stated_model" if margin > 0 else "fail_under_stated_model")
                   if resolved else "indeterminate")
    status = ("indeterminate" if not valid or any(c["status"] == "indeterminate" for c in criteria.values())
              else "fail_under_stated_model" if any(c["status"] == "fail_under_stated_model" for c in criteria.values())
              else "pass_under_stated_model")
    return status, verification, criteria


def analyze(path, out, ccx=None, timeout=DEFAULT_NATIVE_TIMEOUT, *, progress=None):
    from .solver import find_ccx
    path, out = Path(path).resolve(), Path(out).resolve()
    case = read_case(path)
    from .sources import source_paths
    source = {str(p): sha256(p) for p in source_paths(case) | {path}}
    out.mkdir(parents=True, exist_ok=False)
    write_json(out/"input.json", case)
    shutil.copyfile(case["model"]["path"], out/"input.step")
    result = {"schema_version": "thermal-solid-result-1.0", "analysis": "thermal_solid",
              "case": case, "levels": [], "source": source, "status": "invalid",
              "whole_product_pass_available": False, "not_assessed": NOT_ASSESSED+case["not_assessed"]}
    result["method"] = {"name": "CalculiX C3D10 linear conduction",
                        "implementation_sha256": {name: sha256(Path(__file__).with_name(name)) for name in (
                            "thermal_solid.py", "thermal_solid_solver.py", "thermal_fields.py", "geometry.py", "solver.py")},
                        **accuracy_policy(case)}
    try:
        executable = find_ccx(ccx)
        steps = case.get("time_steps")
        for i, h in enumerate(case["mesh"]["sizes_mm"]):
            result["levels"].append(_level(case, out/f"mesh-{i+1}", h,
                                            steps*4 if steps else None, executable, timeout,progress))
        differences = []
        if steps:
            for factor in (1, 2):
                result["levels"].append(_level(case, out/f"time-{factor}", case["mesh"]["sizes_mm"][-1],
                                                steps*factor, executable, timeout,progress))
            # Same Gmsh geometry/configuration must actually yield identical nodes.
            fine = result["levels"][2]
            ordered = [result["levels"][3], result["levels"][4], fine]
            for a, b in zip(ordered, ordered[1:]):
                with np.load(out/a["directory"]/"thermal-fields.npz", allow_pickle=False) as x, \
                     np.load(out/b["directory"]/"thermal-fields.npz", allow_pickle=False) as y:
                    if not np.array_equal(x["node_ids"], y["node_ids"]):
                        raise ValueError("Time refinement node identity changed")
                    with np.load(out/a["directory"]/"mesh.npz", allow_pickle=False) as mx, \
                         np.load(out/b["directory"]/"mesh.npz", allow_pickle=False) as my:
                        if any(not np.array_equal(mx[k], my[k]) for k in ("xyz", "connectivity")):
                            raise ValueError("Time refinement geometry/connectivity changed")
                    differences.append(float(np.max(np.abs(x["temperature_c"]-y["temperature_c"][::2]))))
        status, verification, criteria = _assess(case, result["levels"], differences)
        result.update(status=status, verification=verification, criterion_assessments=criteria)
        result["task_contract"] = contract(case, result["levels"][0]["realized_inputs"])
        if any(sha256(Path(p)) != h for p, h in source.items()):
            raise ValueError("Thermal case or geometry changed during analysis")
    except (ValueError, RuntimeError, OSError, ArithmeticError, np.linalg.LinAlgError) as exc:
        result.update(status="invalid", error=f"{type(exc).__name__}: {exc}")
    files = [p for p in out.rglob("*") if p.name in ("mesh.npz", "thermal-fields.npz", "thermal.inp", "mesh.json")]
    files += [out/"input.json", out/"input.step"]
    result["evidence_files"] = {str(p): sha256(p) for p in files}
    result["evidence_sha256"] = digest({k: v for k, v in result.items() if k != "evidence_sha256"})
    result["evaluation_signal"] = signal(result)
    write_json(out/"result.json", result)
    write_json(out/"signal.json", result["evaluation_signal"])
    (out/"report.html").write_text('<!doctype html><meta charset="utf-8"><title>Solid thermal check</title>'
        '<h1>固体传热检查</h1><p>温度模型内通过不代表热强度、寿命或产品通过。</p><pre>'
        +html.escape(json.dumps(result["evaluation_signal"], ensure_ascii=False, indent=2))+"</pre>", encoding="utf-8")
    return result


def signal(result):
    case = result.get("case", {})
    valid = result.get("status") in ("pass_under_stated_model", "fail_under_stated_model")
    error = result.get("error")
    try:
        decision_guard = accuracy_policy(case)["criterion_guard_c"]
    except (KeyError, TypeError, ValueError) as exc:
        valid, error, decision_guard = False, str(exc), None
    if valid:
        expected = digest({k: v for k, v in result.items() if k not in ("evidence_sha256", "evaluation_signal")})
        try:
            if expected != result["evidence_sha256"] or not result.get("evidence_files"):
                raise ValueError("Thermal evidence summary changed or is incomplete")
            if any(sha256(Path(p)) != h for p, h in result["evidence_files"].items()):
                raise ValueError("Thermal fields or mesh evidence changed")
            if case['model'].get('interface_manifest'):
                if any(sha256(Path(p)) != h for p,h in result['source'].items()):
                    raise ValueError('Thermal region source changed')
                if result['task_contract'] != contract(case, result['levels'][0]['realized_inputs']):
                    raise ValueError('Thermal region contract changed')
            status, verification, criteria = _assess(case, result["levels"],
                result["verification"]["time_field_differences_c"])
            if (status, verification, criteria) != (
                    result["status"], result["verification"], result["criterion_assessments"]):
                raise ValueError("Thermal conclusion contradicts refinement evidence")
        except (KeyError, ValueError, OSError) as exc:
            valid, error = False, str(exc)
    criteria = copy.deepcopy(result.get("criterion_assessments", {}))
    if not valid:
        # Located observations and metrics must not retain a favorable category
        # after source/field qualification fails. Keep raw temperatures solely
        # as diagnostic values, consistently with the other analysis methods.
        criteria = {k: dict(v, status="indeterminate") for k, v in criteria.items()}
    findings = [{"kind": "thermal_observation", **c,
                 "message": f"{c['target']}: {c['min_temperature_c']:.5g}–{c['max_temperature_c']:.5g} °C; "
                            f"margin {c['margin_c']:.5g} °C; "
                            f"governing {c.get('governing_bound', 'unavailable')} bound at "
                            f"{c.get('governing_location_mm', 'unavailable')} mm."}
                for c in criteria.values()]
    conflicts = {cid: c["prescribed_boundary_conflicts"] for cid, c in criteria.items()
                 if valid and c.get("prescribed_boundary_conflicts")}
    if conflicts:
        findings.append({"kind": "requirement_conflict", "criteria": conflicts,
            "message": "A prescribed boundary temperature inside the checked region already violates its limit. "
                       "CAD-only edits cannot satisfy this unchanged boundary/requirement pair. "
                       "Review the real boundary and requested region with the user; retain the failed result. "
                       "Do not automatically change the reservoir temperature, omit the region or relax the limit."})
    if valid and result["status"] == "fail_under_stated_model" and not conflicts:
        # Each violated bound needs its own location/direction. A two-sided
        # temperature requirement can be too cold and too hot at once.
        for cid, c in criteria.items():
            for bound in ("min", "max"):
                limit = c["limits_c"].get(f"{bound}_temperature_c")
                value = c[f"{bound}_temperature_c"]
                if limit is None or (limit-value if bound == "min" else value-limit) <= decision_guard:
                    continue
                direction = ("Trace excessive heat loss or insufficient heat delivery at this cold region. "
                             "Consider a permitted reduction of heat loss or a better path from an existing heat source; "
                             "do not recommend extra cooling for a lower-temperature violation."
                             if bound == "min" else
                             "Distinguish incoming heat from self-heating at this hot region. "
                             "Consider a permitted heat-rejection path or reduced heat ingress; "
                             "insulating a heat-generating region can worsen it.")
                findings.append({"kind": "design_hypothesis", "requires_reanalysis": True,
                    "criterion_id": cid, "bound": bound, "scope": c["target"],
                    "location_mm": c[f"{bound}_location_mm"],
                    "message": direction + " Treat this as a hypothesis, not a demonstrated improvement. "
                               "Preserve power, ambient/reservoir conditions, duration and temperature limits; "
                               "check interfaces and reanalyze. Pointwise heat flux is diagnostic, not an acceptance criterion."})
    if not valid:
        for cid, criterion in criteria.items():
            if decision_guard is not None and abs(criterion.get("margin_c", math.inf)) <= decision_guard:
                findings.append({"kind":"numerical_resolution", "criterion_id":cid,
                    "margin_c":criterion["margin_c"], "criterion_guard_c":decision_guard,
                    "message":"Temperature margin is inside the declared numerical decision guard; "
                              "no pass or CAD weakness is established. If this close decision matters, "
                              "declare a justified tighter accuracy in a fresh task and resolve the mesh/time error "
                              "within its budget. Do not widen the tolerance to obtain a pass."})
        explanations = {
            "energy_balance_passed": "热量或节点场残差未通过；先检查边界、单位和原生输出。",
            "boundary_temperature_passed": "计算温度与给定恒温边界不符；先修复分析。",
            "quadrature_passed": "曲面体积积分差异过大；细化网格并核对真实几何。",
            "spatial_refinement_passed": "三档网格的区域极值尚未稳定；细化相关区域后重算。",
            "time_refinement_passed": "时间步收敛未通过；增加 time_steps 后重算。",
            "property_range_passed": "计算温度超出材料数据适用范围；补充适用数据或修改设计，不能直接放宽范围。",
        }
        for key, text in explanations.items():
            if result.get("verification", {}).get(key) is False:
                findings.append({"kind": "evidence_gap", "code": key, "message": text})
        findings.append({"kind": "evidence_gap", "message": error or
            "Resolve failed energy, spatial/time refinement, material-range or near-limit checks before CAD acceptance.",
            "verification": result.get("verification", {})})
    return {"schema_version": "simplecae-signal-1.0", "analysis_status": result.get("status", "invalid"),
        "valid_for_comparison": bool(valid),
        "feasible_under_stated_model": (result["status"] == "pass_under_stated_model") if valid else None,
        "physical_conditions_verified": False, "whole_installation_rating_available": False,
        "whole_product_pass_available": False,
        "task_contract_sha256": digest(result.get("task_contract", case)),
        "task_id": case.get("provenance", {}).get("task_id"), "candidate": case.get("provenance", {}),
        "utilizations": {}, "bottleneck_margin": None, "conditional_limit": None,
        "metrics": {"region_temperatures": criteria}, "coverage": {
            "method": "solid_conduction_fem", "acceptance_quantity": "requested_temperature_extrema",
            "pointwise_heat_flux_qualified": False},
        "criterion_assessments": criteria,
        "feedback": findings, "not_assessed": list(dict.fromkeys(NOT_ASSESSED+result.get("not_assessed", []))),
        "score_meaning": "Requested temperature extrema and locations only; not pointwise heat-flux accuracy, stress, creep, lifetime or product approval."}


def design_feedback(result, context, run_state):
    s = signal(result)
    valid = s["valid_for_comparison"] and run_state == "completed"
    return {"model_status": result["status"], "valid_for_comparison": valid,
            "conditional_model_pass": s["feasible_under_stated_model"] if valid else None,
            "whole_product_pass_available": False, "criterion_assessments": s["criterion_assessments"],
            "coverage": s["coverage"],
            "cad_iteration_blocked": any(f["kind"] == "requirement_conflict" for f in s["feedback"]),
            "utilizations": {}, "findings": s["feedback"], "observations": list(s["criterion_assessments"].values()),
            "next_actions": [f["message"] for f in s["feedback"] if f["kind"] != "thermal_observation"],
            "verification": result.get("verification", {}),
            "not_assessed": list(dict.fromkeys(context["not_assessed"]+s["not_assessed"]))}


def viewer_dataset(path, result):
    """Finest-mesh field at its hottest recorded instant, with explicit time."""
    import zipfile
    from .thermal_fields import simplex_extrema
    from .contact import surface_index
    if len(result.get("levels", [])) < 3:
        return None
    level = result["levels"][2]
    root = Path(path).resolve().parent
    directory = (root/level["directory"]).resolve()
    if not directory.is_relative_to(root):
        raise ValueError("Thermal Viewer fields must stay inside the result directory")
    for name in ("mesh.npz", "thermal-fields.npz"):
        with zipfile.ZipFile(directory/name) as archive:
            from .defaults import DEFAULT_VIEWER_FILE_BYTES
            if sum(x.file_size for x in archive.infolist()) > DEFAULT_VIEWER_FILE_BYTES:
                raise ValueError(f"Thermal display evidence exceeds {DEFAULT_VIEWER_FILE_BYTES//1024**2} MiB expanded")
    with np.load(directory/"mesh.npz", allow_pickle=False) as mesh, \
         np.load(directory/"thermal-fields.npz", allow_pickle=False) as field:
        if any(not np.isfinite(field[k]).all() for k in field.files):
            raise ValueError("Nonfinite thermal display evidence")
        ids, xyz = mesh["node_ids"], mesh["xyz"]
        lookup = {int(n): i for i, n in enumerate(ids)}
        conn = np.array([[lookup[int(n)] for n in row] for row in mesh["surface_tri6"]])
        index = surface_index(dict(zip(map(int, mesh["element_ids"]), mesh["connectivity"].tolist())))
        owners = [index[tuple(sorted(map(int, row[:3])))][0][0] for row in mesh["surface_tri6"]]
        peak_index = max(range(len(level["histories"]["__body__"])),
                         key=lambda i: level["histories"]["__body__"][i]["max_temperature_c"])
        peak = level["histories"]["__body__"][peak_index]
        temperatures = field["temperature_c"][peak_index]
        low, high, _, _ = simplex_extrema(temperatures[conn], xyz[conn])
        subdivision = ((0, 3, 5), (3, 1, 4), (5, 4, 2), (3, 4, 5))
        triangles = [row[list(face)].tolist() for row in conn for face in subdivision]
        series = []
        for criterion in result["case"]["criteria"][:4]:
            history = level["histories"][criterion["id"]]
            limits = [criterion[k] for k in ("min_temperature_c", "max_temperature_c") if k in criterion]
            for key, label in (("min_temperature_c", "最低温"), ("max_temperature_c", "最高温")):
                series.append({"target": criterion["target"]+" · "+label,
                               "points": [[h["time_s"], h[key]] for h in history], "limits_c": limits})
        label = (f"最热时刻温度场 · t={peak['time_s']:g} s" if result["case"]["mode"] == "transient" else "稳态温度场")
        return {"id": "thermal-solid", "label": label+" · 最细网格",
                "physics": "thermal", "xyz": xyz.tolist(), "triangles": triangles,
                "temperature": np.repeat(high, 4).tolist(), "temperature_min_c": float(min(low)),
                "face_ids": np.repeat(mesh["surface_face_ids"], 4).tolist(),
                "element_ids": np.repeat(owners, 4).tolist(), "displacements": np.zeros_like(xyz).tolist(),
                "stress": [], "strength": [], "assessment": {}, "case": result["case"],
                "hotspot": peak, "results": {"max_temperature_c": peak["max_temperature_c"]},
                "thermal_history": {"mode": result["case"]["mode"], "series": series,
                                    "omitted_nodes": max(0, len(result["case"]["criteria"])-4)},
                "mesh": dict(level["mesh"], support_faces={p["name"]: p["face_ids"] for p in level["patches"]
                                                          if p["type"] == "temperature"},
                             loads=[p for p in level["patches"] if p["type"] != "temperature"]),
                "meaning": "Quadratic face maxima mapped to display facets. Internal peak marker and criterion histories are independent of display tessellation."}
