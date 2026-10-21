"""Located raw-integration-point checks; supplement, never replace global peaks."""
import numpy as np
from .case import keys, vector


def validate_regions(case):
    specs = case.get("stress_regions", [])
    if not isinstance(specs, list):
        raise ValueError("stress_regions must be a list")
    names = set()
    bodies = {b["name"] for b in case.get("bodies", [])}
    for spec in specs:
        keys(spec, ["name", "min_mm", "max_mm", "body"],
             ["name", "min_mm", "max_mm"], "stress region")
        name = spec["name"]
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("stress region names must be nonempty and unique")
        names.add(name)
        low = np.array(vector(spec["min_mm"], "stress region min_mm"))
        high = np.array(vector(spec["max_mm"], "stress region max_mm"))
        if not np.all(high > low):
            raise ValueError("stress region must have positive extent on all three axes")
        if "body" in spec and (not isinstance(spec["body"],str) or spec["body"] not in bodies):
            raise ValueError("stress region body must name an assembly body; omit it for a single solid")


def region_context(case, mesh, point_keys):
    coords, tets, _, _, meta = mesh
    result = []
    if not case.get("stress_regions"):
        return result
    element_ids = list(tets)
    points = np.array([[coords[n] for n in tets[e]] for e in element_ids])
    lower, upper = points.min(axis=1), points.max(axis=1)
    centroids = dict(zip(element_ids, points[:, :4].mean(axis=1).tolist()))
    labels = meta.get("element_material", {})
    body_materials = {b["name"]: b["material_id"] for b in meta.get("body_reports", [])}
    for spec in case["stress_regions"]:
        mask = np.all(upper >= spec["min_mm"], axis=1) & np.all(lower <= spec["max_mm"], axis=1)
        selected = {e for e, keep in zip(element_ids, mask) if keep and (
            "body" not in spec or labels[str(e)] == body_materials[spec["body"]])}
        if not selected:
            raise ValueError(f"Stress region {spec['name']!r} contains no intersecting material elements")
        indices = [i for i, key in enumerate(point_keys) if key[0] in selected]
        if {point_keys[i] for i in indices} != {(e, ip) for e in selected for ip in range(1, 5)}:
            raise ValueError(f"Stress region {spec['name']!r} lacks complete C3D10 integration-point coverage")
        result.append({"spec": spec, "indices": indices, "element_count": len(selected),
                       "centroids": {e: centroids[e] for e in selected}})
    return result


def summarize_regions(stresses, point_keys, strength_context, regions):
    from .materials import strength_summary
    stress = np.asarray(stresses)
    results = []
    for region in regions:
        selected = stress[region["indices"]]
        selected_keys = [point_keys[i] for i in region["indices"]]
        vm = np.sqrt(.5 * ((selected[:, 0] - selected[:, 1])**2
                          + (selected[:, 1] - selected[:, 2])**2
                          + (selected[:, 2] - selected[:, 0])**2)
                     + 3 * np.sum(selected[:, 3:]**2, axis=1))
        peak = int(np.argmax(vm))
        element, ip = selected_keys[peak]
        strength = strength_summary(selected, selected_keys, strength_context)
        if strength["strength_peak"]:
            strength["strength_peak"]["element_centroid_mm"] = region["centroids"][strength["strength_peak"]["element"]]
        results.append({
            **region["spec"], "selected_elements": region["element_count"],
            "integration_point_count": len(selected_keys), "max_von_mises_mpa": float(vm[peak]),
            "peak": {"element": int(element), "integration_point": int(ip),
                     "element_centroid_mm": region["centroids"][element]},
            **strength,
            "selection": "All four raw integration points of every C3D10 whose 10-node bounding box intersects the declared box; no averaging or peak clipping. Coordinates use the analysis frame; reported locations are element corner centroids.",
        })
    return results


def compare_regions(previous, current, expected, tolerance):
    old = {r["name"]: r for r in previous}
    new = {r["name"]: r for r in current}
    if set(old) != expected or set(new) != expected or len(old) != len(previous) or len(new) != len(current):
        raise ValueError("Solved stress region coverage does not match this case")
    changes = {}
    for name in sorted(expected):
        metrics = {}
        for field in ("max_von_mises_mpa", "strength_utilization"):
            a, b = old[name].get(field), new[name].get(field)
            if a is None or b is None:
                if field == "max_von_mises_mpa" or (a is None) != (b is None):
                    raise ValueError("Missing or inconsistent stress region metric")
                metrics[field] = None
            else:
                if not np.isfinite([a, b]).all() or min(a, b) < 0:
                    raise ValueError("Stress region metrics must be finite and nonnegative")
                metrics[field] = abs(b - a) / max(b, 1e-30)
        changes[name] = {"relative_changes": metrics,
                         "converged": all(v is None or v <= tolerance for v in metrics.values()),
                         "current_peak": new[name]["peak"]}
    return changes


def unresolved_findings(result):
    """Same located feedback for direct CLI/API, the design wrapper and Viewer."""
    findings=[]
    stages=result.get('stage_assessments',{'service':result.get('assessment',{})})
    for stage,assessment in stages.items():
        pairs=assessment.get('verification',{}).get('stress_region_mesh_comparisons',[])
        for region in assessment.get('stress_regions',[]):
            name=region['name']
            if len(pairs)>=2 and all(p.get(name,{}).get('converged') is True for p in pairs[-2:]):
                continue
            findings.append({'kind':'unresolved_local_stress','stage':stage,'region':name,
                'peak':region['peak'],'strength_peak':region.get('strength_peak'),
                'mesh_comparisons':[p.get(name) for p in pairs[-2:]],
                'message':f"Local stress convergence is unresolved in {stage}/{name}, near element centroid {region['peak']['element_centroid_mm']} mm. A stable global maximum does not qualify this region.",
                'suggestion':'Inspect mesh quality, load/support edges and the actual CAD transition at this region. A nonconverging peak is not proof of weak geometry or mathematical singularity; preserve the hotspot and original criteria.'})
    return findings
