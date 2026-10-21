"""Strict input contract. All internal units are mm, N, MPa."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

CONDITIONS = (
    "material_verified", "dimensions_verified", "supports_represent_actual_mounting",
    "load_pattern_verified", "self_weight_negligible",
)
NOT_ASSESSED = [
    "Buckling and stability (including local plate buckling)",
    "Bolts, anchors, wall/substrate, welds, adhesive and mounting failure",
    "Contact, separation, slip, bolt preload and unspecified joint compliance",
    "Plastic redistribution, fracture and ultimate collapse",
    "Fatigue, impact, vibration and dynamic amplification",
    "Creep, sustained-load duration and temperature effects",
    "Unresolved infill details, layer damage, delamination and manufacturing defects",
    "Directional material properties unless explicitly calibrated",
    "Material/manufacturing variability outside the declared calibration",
    "Self-weight when not explicitly modeled",
    "Residual stress and other unspecified non-scaling loads",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


JSON_PRETTY_LIMIT = 8 * 1024 * 1024  # Formatting only; never discard result data.


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if len(encoded) > JSON_PRETTY_LIMIT:
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    path.write_text(encoded + "\n", encoding="utf-8")


def keys(obj, allowed, required=(), label="object"):
    if not isinstance(obj, dict):
        raise ValueError(f"{label} must be an object")
    if set(obj) - set(allowed):
        raise ValueError(f"{label}: unknown keys {sorted(set(obj) - set(allowed))}")
    if set(required) - set(obj):
        raise ValueError(f"{label}: missing keys {sorted(set(required) - set(obj))}")


def number(x, name, positive=False):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(f"{name} must be a finite number")
    if positive and x <= 0:
        raise ValueError(f"{name} must be positive")
    return float(x)


def vector(x, name):
    if not isinstance(x, list) or len(x) != 3:
        raise ValueError(f"{name} must have three components")
    return [number(v, name) for v in x]


def selector(s):
    keys(s, ["type", "axis", "position_mm", "tolerance_mm", "ids", "geometry_sha256","name"], ["type"], "selector")
    if s["type"] == "plane":
        keys(s, ["type", "axis", "position_mm", "tolerance_mm"], ["axis", "position_mm"], "plane selector")
        if s["axis"] not in ("x", "y", "z"):
            raise ValueError("selector axis must be x/y/z")
        number(s["position_mm"], "position_mm")
        number(s.get("tolerance_mm", 1e-4), "tolerance_mm", True)
    elif s["type"] == "face_ids":
        keys(s, ["type", "ids", "geometry_sha256"], ["ids", "geometry_sha256"], "face_ids selector")
        ids = s["ids"]
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i <= 0 for i in ids):
            raise ValueError("face ids must be a nonempty list of positive integers")
        if len(ids) != len(set(ids)) or not isinstance(s["geometry_sha256"], str) or len(s["geometry_sha256"]) != 64:
            raise ValueError("face_ids require unique ids and an inspection geometry SHA-256")
    elif s['type']=='interface':
        keys(s,['type','name'],['name'],'interface selector')
        if not isinstance(s['name'],str) or not s['name']:
            raise ValueError('interface selector name must be nonempty')
    else:
        raise ValueError("selector type must be plane or face_ids; partial face patches require upstream partitioning")


def validate_case(c,*,allow_unloaded=False):
    version = c.get("schema_version") if isinstance(c, dict) else None
    extras = ["buckling", "gravity", "provenance", "load_cases", "probes", "reference_only", "stress_regions"] if version == "2.0" else []
    keys(c, ["schema_version", "model", "material", "supports", "loads", "criteria", "mesh", "conditions", "notes"] + extras,
         ["schema_version", "model", "material", "supports", "loads", "criteria", "mesh", "conditions"], "case")
    if version not in ("1.0", "2.0"):
        raise ValueError("schema_version must be 1.0 or 2.0")
    if 'reference_only' in c and type(c['reference_only']) is not bool:raise ValueError('reference_only must be boolean')
    if 'probes' in c:
        from .probes import validate_probes
        validate_probes(c)
    if 'stress_regions' in c:
        from .stress_regions import validate_regions
        validate_regions(c)
    keys(c["model"], ["path", "expected_bbox_mm"] + (["units","scene_node","source_up_axis","pose","interface_manifest","solid_id"] if version=='2.0' else []), ["path"], "model")
    if not isinstance(c["model"]["path"], str) or not c["model"]["path"]:
        raise ValueError("model.path must be a path string")
    for field,allowed in [('units',('m','mm','cm')),('source_up_axis',('y','z')),('pose',('rest',))]:
        if field in c['model'] and c['model'][field] not in allowed:
            raise ValueError(f"model.{field} must be one of {allowed}")
    if 'scene_node' in c['model'] and (not isinstance(c['model']['scene_node'],str) or not c['model']['scene_node']):
        raise ValueError('model.scene_node must be a nonempty occurrence name')
    if 'solid_id' in c['model']:
        keys(c['model']['solid_id'],['id','geometry_sha256'],['id','geometry_sha256'],'solid_id')
        if type(c['model']['solid_id']['id']) is not int or c['model']['solid_id']['id']<=0:
            raise ValueError('solid_id.id must be a positive integer')
        if not isinstance(c['model']['solid_id']['geometry_sha256'],str) or len(c['model']['solid_id']['geometry_sha256'])!=64:
            raise ValueError('solid_id requires the current inspection hash')
    bbox = c["model"].get("expected_bbox_mm")
    if bbox is not None:
        if not isinstance(bbox, list) or len(bbox) != 2:
            raise ValueError("expected_bbox_mm must be [min_xyz, max_xyz]")
        a, b = vector(bbox[0], "bbox min"), vector(bbox[1], "bbox max")
        if any(bi <= ai for ai, bi in zip(a, b)):
            raise ValueError("expected bbox must have positive extents")
    m = c["material"]
    from .materials import validate_material
    validate_material(m,version)
    for field in ("supports", "loads"):
        items = c[field]
        if not isinstance(items, list) or (not items and not (field == "loads" and version == "2.0" and ("gravity" in c or allow_unloaded))):
            raise ValueError(f"{field} must be a nonempty list")
        names = []
        for item in items:
            reference=field=='supports' and c.get('reference_only',False)
            allowed = ["name", "selector"] + (["total_force_n"] if field == "loads" else ["dofs"])
            if reference:allowed=['name','point_mm','dofs','geometry_sha256']
            if field == "loads" and version == "2.0":
                allowed += ["total_moment_n_mm", "application_point_mm", "scalable"]
            keys(item, allowed, ["name", "selector", "total_force_n"] if field == "loads" else ['name','point_mm','dofs','geometry_sha256'] if reference else ["name", "selector"], field)
            if not isinstance(item["name"], str) or not item["name"].strip():
                raise ValueError("support/load names must be nonempty strings")
            names.append(item["name"])
            if not reference:selector(item["selector"])
            if field=='supports':
                from .constraints import support_dofs
                support_dofs(item)
            if field == "loads":
                force = vector(item["total_force_n"], "total_force_n")
                moment = vector(item.get("total_moment_n_mm", [0,0,0]), "total_moment_n_mm")
                if not any(force) and not any(moment):
                    raise ValueError("each force/moment load must be nonzero")
                if "application_point_mm" in item:
                    vector(item["application_point_mm"], "application_point_mm")
                if "scalable" in item and type(item["scalable"]) is not bool:
                    raise ValueError("scalable must be a boolean")
        if len(names) != len(set(names)):
            raise ValueError(f"{field} names must be unique")
    cr = c["criteria"]
    keys(cr, ["yield_safety_factor", "max_displacement_mm", "max_small_displacement_ratio", "max_strain_norm"]+(['strength_safety_factor'] if version=='2.0' else []), label="criteria")
    if cr.get("yield_safety_factor") is not None and number(cr["yield_safety_factor"], "yield safety factor") < 1:
        raise ValueError("yield safety factor must be >= 1")
    if cr.get('strength_safety_factor') is not None and number(cr['strength_safety_factor'],'strength safety factor')<1:
        raise ValueError('strength safety factor must be >=1')
    if cr.get('strength_safety_factor') is not None and cr.get('yield_safety_factor') is not None and cr['strength_safety_factor']!=cr['yield_safety_factor']:
        raise ValueError('strength/yield safety factor aliases must agree')
    for field in ("max_displacement_mm", "max_small_displacement_ratio", "max_strain_norm"):
        if cr.get(field) is not None:
            number(cr[field], field, True)
    mesh = c["mesh"]
    keys(mesh, ["sizes_mm", "displacement_relative_tolerance", "stress_relative_tolerance", "balance_relative_tolerance", "max_elements", "local_refinements", "preserve_boundary_nodes"],
         ["sizes_mm"], "mesh")
    sizes = mesh["sizes_mm"]
    if not isinstance(sizes, list) or len(sizes) < 3:
        raise ValueError("at least three mesh sizes are required")
    for h in sizes:
        number(h, "mesh size", True)
    if any(b / a > 0.8 for a, b in zip(sizes, sizes[1:])):
        raise ValueError("mesh sizes must decrease by at least 20% at every level")
    for field in ("displacement_relative_tolerance", "stress_relative_tolerance", "balance_relative_tolerance"):
        if field in mesh and not 0 < number(mesh[field], field) < 1:
            raise ValueError(f"{field} must be in (0, 1)")
    if "max_elements" in mesh and (type(mesh["max_elements"]) is not int or mesh["max_elements"] < 1):
        raise ValueError("max_elements must be a positive integer")
    if 'preserve_boundary_nodes' in mesh and type(mesh['preserve_boundary_nodes']) is not bool:
        raise ValueError('preserve_boundary_nodes must be boolean')
    from .local_mesh import validate_refinements
    validate_refinements(mesh)
    keys(c["conditions"], CONDITIONS, CONDITIONS, "conditions")
    if any(type(c["conditions"][k]) is not bool for k in CONDITIONS):
        raise ValueError("conditions must be explicitly true or false")
    if "gravity" in c:
        keys(c["gravity"], ["acceleration_m_s2"], ["acceleration_m_s2"], "gravity")
        if not any(vector(c["gravity"]["acceleration_m_s2"], "gravity acceleration")):
            raise ValueError("gravity vector must be nonzero")
        if "density_kg_m3" not in m:
            raise ValueError("gravity requires density_kg_m3")
    if "buckling" in c:
        b = c["buckling"]
        keys(b, ["enabled", "modes", "safety_factor", "eigenvalue_relative_tolerance"], ["enabled"], "buckling")
        if type(b["enabled"]) is not bool:
            raise ValueError("buckling.enabled must be boolean")
        if type(b.get("modes", 3)) is not int or not 1 <= b.get("modes", 3) <= 20:
            raise ValueError("buckling modes must be 1..20")
        if number(b.get("safety_factor", 2.), "buckling safety_factor") < 1:
            raise ValueError("buckling safety_factor must be >=1")
        if not 0 < number(b.get("eigenvalue_relative_tolerance", .05), "buckling tolerance") < 1:
            raise ValueError("buckling tolerance must be in (0,1)")
    if "provenance" in c:
        keys(c["provenance"], ["generator", "model_id", "revision", "parameters", "task_id", "source_file", "generator_version"], label="provenance")
    if "load_cases" in c:
        if not isinstance(c["load_cases"], list) or not c["load_cases"]:
            raise ValueError("load_cases must be a nonempty list")
        names = []
        for load_case in c["load_cases"]:
            keys(load_case, ["name", "loads", "gravity"], ["name", "loads"], "load_case")
            if not isinstance(load_case['name'],str) or not load_case['name'].strip():
                raise ValueError('load-case name must be a nonempty string')
            names.append(load_case["name"])
            child = dict(c)
            child.pop("load_cases")
            child["loads"] = load_case["loads"]
            if "gravity" in load_case:
                child["gravity"] = load_case["gravity"]
            validate_case(child)
        if len(set(names)) != len(names):
            raise ValueError("load-case names must be unique")
    from .reference_support import validate
    validate(c)
    return c


def load_case(path: Path):
    c = validate_case(json.loads(path.read_text(encoding="utf-8-sig")))
    model = Path(c["model"]["path"])
    model = (path.parent / model).resolve() if not model.is_absolute() else model.resolve()
    formats=(".step", ".stp", ".glb", ".stl", ".obj") if c['schema_version']=='2.0' else (".step", ".stp")
    if model.suffix.lower() not in formats or not model.is_file():
        raise ValueError("model.path must reference an existing supported solid/mesh file")
    if model.suffix.lower() in ('.stl','.obj') and 'units' not in c['model']:
        raise ValueError('STL/OBJ require explicit model.units')
    if model.suffix.lower() in ('.step','.stp'):
        if c['model'].get('units','mm')!='mm':
            raise ValueError('model.units: STEP carries its own units and is imported into mm; omit this field or use "mm" as the analysis-unit annotation. Do not rescale STEP as a mesh.')
        invalid=[k for k in ('scene_node','source_up_axis','pose') if k in c['model']]
        if invalid:raise ValueError('STEP model: remove mesh-only field(s) '+', '.join(invalid)+'; inspect STEP solid_id for multi-body selection instead')
    if model.suffix.lower() not in ('.step','.stp') and 'solid_id' in c['model']:
        raise ValueError('solid_id applies to STEP; mesh scenes use scene_node')
    c["model"]["path"] = str(model)
    if 'interface_manifest' in c['model']:
        interface=Path(c['model']['interface_manifest'])
        interface=(path.parent/interface).resolve() if not interface.is_absolute() else interface.resolve()
        if not interface.is_file(): raise ValueError('interface_manifest does not exist')
        c['model']['interface_manifest']=str(interface)
    return c
