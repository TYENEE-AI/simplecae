"""Bounded material-data screens, not automatic fatigue/creep FEM.

S-N amplitudes use log/log interpolation and Palmgren--Miner damage.
Creep uses explicit constant-stress, constant-temperature tabulated strains.
No extrapolation, invented endurance limit, automatic mean-stress correction,
or use of a von Mises maximum as a signed uniaxial stress history.
"""
from __future__ import annotations

import copy
import html
import json
import math
from pathlib import Path

import numpy as np

from .case import sha256, write_json
from .signals import digest

VERSIONS = ("fatigue-data-1.0", "creep-data-1.0")
SOURCE_KEYS = ("geometry_source", "stress_source", "service_source")
NOT_ASSESSED = [
    "Stress values and material-curve transcription are declared inputs; file hashes bind evidence but do not independently validate those declarations.",
    "Only the named locations and declared service are assessed, not every point or the whole product.",
    "Multiaxial/nonproportional fatigue, crack growth, low-cycle plasticity and load-sequence effects are not modeled.",
    "Creep redistribution, variable stress/temperature, relaxation, recovery, rupture and fatigue-creep interaction are not modeled.",
    "Physical material/manufacture variability, environmental aging and product acceptance require separate evidence.",
]


def schema(mode):
    from .schemas import obj, arr, enum
    text, num = {"type": "string", "minLength": 1}, {"type": "number"}
    positive, nonnegative = {"type": "number", "exclusiveMinimum": 0}, {"type": "number", "minimum": 0}
    vec = dict(arr(num, 3), maxItems=3)
    temp = {"type": "number", "exclusiveMinimum": -273.15}
    evidence = obj({"path": text, "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}, "basis": text},
                   ("path", "sha256", "basis"))
    material = obj({"id": text, "manufacture": text, "orientation": text}, ("id", "manufacture", "orientation"))
    strain = enum("creep_only_magnitude", "total_axial_strain_magnitude")
    curve_common = {"material": material, "temperature_c": temp, "source": evidence,
                    "kind": enum("mathematical_reference", "literature", "coupon_tests"),
                    "stress_definition": {"const": "signed_uniaxial_local"}, "applicability_basis": text}
    point_common = {"id": text, "target": text, "position_mm": vec, "frame": text, "direction": vec}
    if mode == "fatigue":
        sn = obj({"stress_ratio": num, "amplitude_mpa": dict(arr(positive, 2), maxItems=1000),
                  "cycles_to_failure": dict(arr(positive, 2), maxItems=1000)},
                 ("stress_ratio", "amplitude_mpa", "cycles_to_failure"))
        curve = obj(curve_common | {"curves": dict(arr(sn, 1), maxItems=128)})
        curve["required"] = list(curve["properties"])
        service = dict(arr(obj({"id": text, "cycles": positive, "basis": text}, ("id", "cycles", "basis")), 1), maxItems=4096)
        block = obj({"service_id": text, "minimum_mpa": num, "maximum_mpa": num},
                    ("service_id", "minimum_mpa", "maximum_mpa"))
        point = obj(point_common | {"blocks": dict(arr(block, 1), maxItems=4096)})
        limit = {"max_damage": {"type": "number", "exclusiveMinimum": 0, "maximum": 1}}
        extra = {}
    elif mode == "creep":
        curve = obj(curve_common | {"strain_measure": strain,
            "stress_levels_mpa": dict(arr(num, 1), maxItems=256),
            "times_s": dict(arr(nonnegative, 2), maxItems=4096),
            "strain": dict(arr(dict(arr(nonnegative, 2), maxItems=4096), 1), maxItems=256)})
        curve["required"] = list(curve["properties"])
        service = obj({"duration_s": positive, "history": {"const": "constant_from_unloaded"}, "basis": text},
                      ("duration_s", "history", "basis"))
        point = obj(point_common | {"stress_mpa": num})
        limit = {"max_strain": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1}}
        extra = {"strain_measure": strain}
    else:
        raise ValueError("Unknown durability mode")
    point["required"] = list(point["properties"])
    criterion = obj({"id": text, "point": text, "basis": text} | limit)
    criterion["required"] = list(criterion["properties"])
    props = {"schema_version": {"const": mode+"-data-1.0"}, "material": material,
             "temperature_c": temp, "stress_definition": {"const": "signed_uniaxial_local"},
             **dict.fromkeys(SOURCE_KEYS, evidence),
             "material_curve": {"oneOf": [{"type": "null"}, curve]},
             "service": service, "points": dict(arr(point, 1), maxItems=256),
             "criteria": dict(arr(criterion), maxItems=256), **extra,
             "assumptions": arr(text, 1), "not_assessed": arr(text),
             "conditions": obj({k: {"type": "boolean"} for k in
                ("material_data_verified", "stress_history_verified", "service_verified")},
                ("material_data_verified", "stress_history_verified", "service_verified")),
             "provenance": obj({"task_id": text, "revision": text, "generator": text}, ("task_id",))}
    return obj(props, tuple(props))


def validate(case):
    import jsonschema
    mode = case.get("schema_version", "").split("-")[0]
    try:
        jsonschema.Draft202012Validator(schema(mode)).validate(case)
    except jsonschema.ValidationError as exc:
        raise ValueError("Durability input: "+exc.message) from None
    def finite(v):
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError("Durability numbers must be finite")
        if isinstance(v, str) and not v.strip():
            raise ValueError("Durability text must be nonempty")
        if isinstance(v, dict):
            for a in v.values():
                finite(a)
        if isinstance(v, list):
            for a in v:
                finite(a)
    finite(case)
    for key in ("points", "criteria"):
        if len({v["id"] for v in case[key]}) != len(case[key]):
            raise ValueError("Duplicate durability "+key+" id")
    ids = {p["id"] for p in case["points"]}
    if any(c["point"] not in ids for c in case["criteria"]):
        raise ValueError("Criterion references an unknown material point")
    for p in case["points"]:
        if abs(np.linalg.norm(p["direction"])-1) > 1e-9:
            raise ValueError("Local uniaxial stress direction must be a unit vector in the declared frame")
    curve = case["material_curve"]
    if mode == "fatigue":
        services = [s["id"] for s in case["service"]]
        if len(set(services)) != len(services):
            raise ValueError("Duplicate fatigue service id")
        if len(services)*len(case["points"]) > 32768:
            raise ValueError("Fatigue evidence exceeds 32768 point-blocks; select a bounded subtask")
        for p in case["points"]:
            blocks = p["blocks"]
            if len(blocks) != len(services) or {b["service_id"] for b in blocks} != set(services):
                raise ValueError("Every named point must cover every service block exactly once")
            if any(b["minimum_mpa"] > b["maximum_mpa"] for b in blocks):
                raise ValueError("Fatigue minimum stress exceeds maximum stress")
        if curve:
            ratios = [c["stress_ratio"] for c in curve["curves"]]
            if any(abs(r-1) <= 1e-9 for r in ratios) or any(
                    abs(a-b) <= 1e-9 for i, a in enumerate(ratios) for b in ratios[i+1:]):
                raise ValueError("S-N curves require distinct, nonconstant stress ratios")
            for c in curve["curves"]:
                a, n = c["amplitude_mpa"], c["cycles_to_failure"]
                if len(a) != len(n) or any(x <= y for x, y in zip(a, a[1:])) or any(x >= y for x, y in zip(n, n[1:])):
                    raise ValueError("S-N arrays must have equal length, descending amplitude and ascending cycle life")
    elif curve:
        stress, times, strains = np.array(curve["stress_levels_mpa"]), np.array(curve["times_s"]), np.array(curve["strain"])
        if len(stress)*len(times) > 65536 or len(case["points"])*len(times) > 32768:
            raise ValueError("Creep table/history exceeds the bounded task size; select fewer locations or a justified data subset")
        if np.any(stress == 0) or np.any(np.sign(stress) != np.sign(stress[0])) or np.any(np.diff(np.abs(stress)) <= 0):
            raise ValueError("Creep stress grid must have one sign and increasing nonzero magnitudes")
        if times[0] != 0 or np.any(np.diff(times) <= 0):
            raise ValueError("Creep times must begin at zero and strictly increase")
        if strains.shape != (len(stress), len(times)) or np.any(np.diff(strains, axis=1) < 0) or np.any(np.diff(strains, axis=0) < 0):
            raise ValueError("Creep strain grid must be complete and monotone in time and stress magnitude; do not silently smooth data")
        if np.any(strains >= 1):
            raise ValueError("Finite-strain creep is outside this local-strain screen")
        if curve["strain_measure"] == "creep_only_magnitude" and np.any(strains[:, 0] != 0):
            raise ValueError("Creep-only strain must be zero at the unloaded time origin")
    return case


def evidence_sources(case):
    return [case[k] for k in SOURCE_KEYS]+([case["material_curve"]["source"]] if case["material_curve"] else [])


def read_case(path):
    path = Path(path).resolve()
    case = validate(json.loads(path.read_text(encoding="utf-8-sig")))
    for source in evidence_sources(case):
        p = (path.parent/source["path"]).resolve()
        if not p.is_file() or sha256(p) != source["sha256"]:
            raise ValueError("Durability source missing or hash differs: "+str(p))
        source["path"] = str(p)
    return case


def _applicability(case):
    curve = case["material_curve"]
    if not curve:
        return ["missing_material_curve"]
    gaps = []
    if curve["material"] != case["material"]:
        gaps.append("material_manufacture_or_orientation_mismatch")
    if abs(curve["temperature_c"]-case["temperature_c"]) > 1e-9:
        gaps.append("temperature_not_covered")
    if case["schema_version"].startswith("creep") and curve["strain_measure"] != case["strain_measure"]:
        gaps.append("creep_strain_measure_mismatch")
    return gaps


def fatigue_point(case, point, global_gaps):
    records = []
    counts = {s["id"]: s["cycles"] for s in case["service"]}
    known_damage = 0.
    gaps = list(global_gaps)
    for b in point["blocks"]:
        amplitude = (b["maximum_mpa"]-b["minimum_mpa"])/2
        ratio = b["minimum_mpa"]/b["maximum_mpa"] if b["maximum_mpa"] else None
        if not math.isfinite(amplitude) or (ratio is not None and not math.isfinite(ratio)):
            raise ValueError("Nonfinite derived fatigue amplitude/ratio")
        record = {**b, "cycles": counts[b["service_id"]], "amplitude_mpa": amplitude,
                  "mean_mpa": (b["maximum_mpa"]+b["minimum_mpa"])/2, "stress_ratio": ratio,
                  "cycles_to_failure": None, "damage": None}
        local = list(global_gaps)
        if amplitude == 0:
            local.append("constant_stress_needs_static_or_creep_check")
        if ratio is None:
            local.append("undefined_stress_ratio")
        sn = next((c for c in (case["material_curve"] or {}).get("curves", [])
                   if ratio is not None and abs(c["stress_ratio"]-ratio) <= 1e-9), None)
        if not global_gaps and not sn and ratio is not None:
            local.append("stress_ratio_not_covered")
        if sn and not sn["amplitude_mpa"][-1] <= amplitude <= sn["amplitude_mpa"][0]:
            local.append("stress_amplitude_outside_curve")
        if not local:
            life = float(np.exp(np.interp(np.log(amplitude),
                np.log(sn["amplitude_mpa"][::-1]), np.log(sn["cycles_to_failure"][::-1]))))
            damage = counts[b["service_id"]]/life
            if not math.isfinite(damage):
                raise ValueError("Nonfinite fatigue damage")
            record.update(cycles_to_failure=life, damage=damage)
            known_damage += damage
            if not math.isfinite(known_damage):
                raise ValueError("Nonfinite cumulative fatigue damage")
        record["gaps"] = local
        gaps.extend(local)
        records.append(record)
    return {"damage": known_damage if not gaps else None, "known_damage_lower_bound": known_damage,
            "blocks": records, "gaps": sorted(set(gaps))}


def creep_point(case, point, global_gaps):
    curve = case["material_curve"]
    gaps = list(global_gaps)
    strain, history = None, []
    if curve:
        stress, times = curve["stress_levels_mpa"], curve["times_s"]
        requested, duration = point["stress_mpa"], case["service"]["duration_s"]
        magnitudes = np.abs(stress)
        if np.sign(requested) != np.sign(stress[0]) or not magnitudes[0] <= abs(requested) <= magnitudes[-1]:
            gaps.append("constant_stress_outside_curve")
        if not times[0] <= duration <= times[-1]:
            gaps.append("duration_outside_curve")
        if not gaps:
            time_grid = [t for t in times if t < duration]+[duration]
            for t in time_grid:
                per_stress = [np.interp(t, times, row) for row in curve["strain"]]
                history.append([t, float(np.interp(abs(requested), magnitudes, per_stress))])
            strain = history[-1][1]
    return {"strain": strain, "strain_measure": case["strain_measure"],
            "history": history, "stress_mpa": point["stress_mpa"], "gaps": sorted(set(gaps))}


def calculate(case, progress=None):
    validate(case)
    mode = case["schema_version"].split("-")[0]
    gaps = _applicability(case)
    points = {}
    for p in case["points"]:
        if progress:
            progress({"stage": "durability", "pose": p["id"]})
        observation = fatigue_point(case, p, gaps) if mode == "fatigue" else creep_point(case, p, gaps)
        points[p["id"]] = {k: copy.deepcopy(p[k]) for k in ("target", "position_mm", "frame", "direction")} | observation
    criteria = {}
    value_key, limit_key = ("damage", "max_damage") if mode == "fatigue" else ("strain", "max_strain")
    for c in case["criteria"]:
        point = points[c["point"]]
        value, limit = point[value_key], c[limit_key]
        margin = limit-value if value is not None else None
        guard = 1e-10*max(1e-12, limit, value or 0)
        status = ("pass_under_stated_model" if margin > guard else
                  "fail_under_stated_model" if margin < -guard else "indeterminate") if margin is not None else "indeterminate"
        criteria[c["id"]] = {"status": status, "point": c["point"], "target": point["target"],
            "position_mm": point["position_mm"], "frame": point["frame"], "value": value,
            "quantity": value_key, "limit": limit, "margin": margin, "numerical_guard": guard,
            "utilization": value/limit if value is not None else None, "gaps": point["gaps"]}
    resolved = bool(criteria) and all(c["status"] != "indeterminate" for c in criteria.values())
    # Unsupported unselected points also remain visible and prevent an overall favorable result.
    resolved = resolved and all(not p["gaps"] for p in points.values())
    failed = any(c["status"] == "fail_under_stated_model" for c in criteria.values())
    status = ("fail_under_stated_model" if failed else "pass_under_stated_model") if resolved else "indeterminate"
    return {"schema_version": mode+"-data-result-1.0", "analysis": mode+"_data",
            "case": copy.deepcopy(case), "status": status, "points": points,
            "criterion_assessments": criteria, "whole_product_pass_available": False,
            "physical_conditions_verified": False, "not_assessed": list(dict.fromkeys(NOT_ASSESSED+case["not_assessed"])),
            "evidence_gaps": [k for k, v in case["conditions"].items() if not v],
            "verification": {"curve_input_validated": True, "all_locations_within_data": all(not p["gaps"] for p in points.values())}}


def contract(case):
    c = copy.deepcopy(case)
    # Numerical stress and CAD locations may change; service/data/criteria cannot.
    c.pop("geometry_source")
    c.pop("stress_source")
    c["points"] = [{k: p[k] for k in ("id", "target", "frame", "direction")} for p in c["points"]]
    c["service_source"].pop("path")
    if c["material_curve"]:
        c["material_curve"]["source"].pop("path")
    c["provenance"] = {"task_id": case["provenance"]["task_id"]}
    return c


def seal(result):
    return digest({k: v for k, v in result.items() if k not in ("evaluation_signal", "evidence_sha256")})


def signal(result):
    criteria = copy.deepcopy(result.get("criterion_assessments", {}))
    valid, error = False, None
    try:
        if result["evidence_sha256"] != seal(result) or result["task_contract"] != contract(result["case"]):
            raise ValueError("Durability evidence or contract changed")
        expected = calculate(result["case"])
        for key in ("status", "points", "criterion_assessments", "verification"):
            if digest(result[key]) != digest(expected[key]):
                raise ValueError("Durability results contradict bound input data: "+key)
        valid = result["status"] in ("pass_under_stated_model", "fail_under_stated_model")
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as exc:
        error = str(exc)
    if not valid:
        for c in criteria.values():
            c["status"] = "indeterminate"
    failed = [c for c in criteria.values() if c["status"] == "fail_under_stated_model"]
    findings = [{"kind": "located_result", "criterion": key, "target": c["target"],
                 "position_mm": c["position_mm"], "frame": c["frame"],
                 "message": f'{c["target"]}: {c["quantity"]}={c["value"]}, limit={c["limit"]}; only the named location and supplied data are assessed.'}
                for key, c in criteria.items()]
    if failed and valid:
        findings.append({"kind": "design_hypothesis", "requires_reanalysis": True,
            "scope": [c["target"] for c in failed],
            "message": "Trace the failed location to the load path. A permitted larger load-carrying section, smoother transition or shorter lever arm may reduce local stress; verify this with fresh signed stress evidence, then recheck every required location. Preserve service counts/duration, temperature, material data and criteria. A material, speed, temperature or duty change is a different scenario."})
    if not valid:
        gap_codes = sorted({gap for p in result.get("points", {}).values() for gap in p.get("gaps", [])})
        findings.append({"kind": "evidence_gap", "codes": gap_codes, "message": error or
            ("Obtain applicable material/stress evidence for: "+", ".join(gap_codes) if gap_codes else
             "Supply explicit acceptance criteria or resolve the near-limit result. Do not extrapolate life or discard missing blocks.")})
    return {"schema_version": "simplecae-signal-1.0", "analysis_status": result.get("status", "invalid"),
        "valid_for_comparison": bool(valid), "feasible_under_stated_model": (not failed) if valid else None,
        "physical_conditions_verified": False, "whole_installation_rating_available": False,
        "task_contract_sha256": digest(result.get("task_contract", {})),
        "task_id": result.get("case", {}).get("provenance", {}).get("task_id"),
        "candidate": result.get("case", {}).get("provenance", {}), "utilizations": {
            k: c["utilization"] for k, c in criteria.items() if c["utilization"] is not None},
        "bottleneck_margin": None, "conditional_limit": None, "metrics": {},
        "coverage": {"method": result.get("analysis"), "whole_product": False, "named_points": list(result.get("points", {}))},
        "criterion_assessments": criteria, "feedback": findings,
        "not_assessed": result.get("not_assessed", NOT_ASSESSED)+result.get("evidence_gaps", []),
        "score_meaning": "Data-bounded named-location screen; no infinite life, rupture prediction, whole-part or product rating."}


def analyze(path, out, progress=None):
    from .sources import SourceGuard
    path, out = Path(path).resolve(), Path(out).resolve()
    case = read_case(path)
    guard = SourceGuard({path} | {Path(s["path"]) for s in evidence_sources(case)})
    out.mkdir(parents=True, exist_ok=False)
    write_json(out/"input.json", case)
    result = calculate(case, progress)
    guard.check()
    result["source_hashes"] = guard.hashes
    result["task_contract"] = contract(case)
    result["method"] = {"name": result["analysis"], "implementation_sha256": sha256(Path(__file__)),
                        "interpolation": "log-log S-N / linear time-and-stress creep; no extrapolation"}
    result["evidence_sha256"] = seal(result)
    result["evaluation_signal"] = signal(result)
    write_json(out/"result.json", result)
    write_json(out/"signal.json", result["evaluation_signal"])
    text = html.escape(json.dumps(result["evaluation_signal"], ensure_ascii=False, indent=2))
    (out/"report.html").write_text('<!doctype html><meta charset="utf-8"><title>SimpleCAE durability</title>'
        '<style>body{font:15px/1.6 system-ui;max-width:1000px;margin:32px auto}pre{white-space:pre-wrap}</style>'
        '<h1>材料数据适用范围内的耐久检查</h1><p>仅限所选位置和给定使用条件；不代表整件或产品寿命。</p>'
        '<a href="result.json">应力、材料数据、累积损伤或应变历程</a><pre>'+text+'</pre>', encoding="utf-8")
    if progress:
        progress({"stage": "report"})
    return result


def design_feedback(result, context, run_state):
    s = signal(result)
    if run_state != "completed":
        s.update(valid_for_comparison=False, feasible_under_stated_model=None)
    return {"model_status": result.get("status", "invalid"), "valid_for_comparison": s["valid_for_comparison"],
        "conditional_model_pass": s["feasible_under_stated_model"], "whole_product_pass_available": False,
        "governing_criterion": None, "criterion_assessments": s["criterion_assessments"],
        "utilizations": s["utilizations"], "findings": s["feedback"],
        "observations": list(s["criterion_assessments"].values()),
        "next_actions": [f["message"] for f in s["feedback"] if f["kind"] != "located_result"],
        "not_assessed": list(dict.fromkeys(context["not_assessed"]+s["not_assessed"])),
        "verification": result.get("verification", {}), "meaning": s["score_meaning"]}
