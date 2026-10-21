"""Bounded prescribed-motion checks and transferable installation wrenches.

The public contract has a stationary fixed base and independent URDF joints.
Only explicitly listed states are assessed; no interpolated trajectory envelope.
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
from .robot import read_urdf, transform
from .motion_solver import solve

SCHEMA = "motion-loads-1.0"
RESULT_SCHEMA = "motion-loads-result-1.0"
NOT_ASSESSED = [
    "Only the listed motion states are checked; unsampled trajectory extrema are not bounded.",
    "Rigid-body loads do not establish link strength, stiffness, fatigue or product acceptance.",
    "Flexible dynamics, resonance amplification, impact, backlash, drive friction and controller response are not modeled.",
    "Motor thermal duty, electrical power, gearbox losses and speed-dependent rating data require separate evidence.",
    "Changed joint locations can change workspace/reach even when the same joint motion states are compared.",
]


def schema():
    from .schemas import obj, arr, enum
    text, number = {"type": "string", "minLength": 1}, {"type": "number"}
    positive = {"type": "number", "exclusiveMinimum": 0}
    vec = dict(arr(number, 3), maxItems=3)
    mapping = {"type": "object", "additionalProperties": number}
    load = obj({"link": text, "force_n": vec, "moment_n_m": vec, "position_m": vec,
                "frame": enum("world", "link"), "position_frame": enum("world", "link")})
    load["required"] = list(load["properties"])
    state = obj({"id": text, "basis": text, "positions": mapping, "velocities": mapping,
                 "accelerations": mapping, "loads": dict(arr(load), maxItems=128)})
    state["required"] = list(state["properties"])
    common = {"id": text, "target": text, "basis": text}
    effort = obj(common | {"type": {"const": "joint_effort"}, "joint": text,
                           "max_abs_effort": positive, "rating_max_abs_speed": positive})
    effort["required"] = list(effort["properties"])
    base = obj(common | {"type": enum("base_force", "base_moment"), "limit": positive})
    base["required"] = list(base["properties"])
    return obj({
        "schema_version": {"const": SCHEMA},
        "model": obj({"path": text, "units": {"const": "m"},
                      "package_roots": {"type": "object", "additionalProperties": text}}, ("path", "units")),
        "massless_links": dict(arr(text), uniqueItems=True),
        "base": {"const": "fixed"},
        "base_pose": obj({"xyz_m": vec, "rpy_rad": vec}, ("xyz_m", "rpy_rad")),
        "gravity_m_s2": vec,
        "states": dict(arr(state, 1), maxItems=128),
        "criteria": dict(arr({"oneOf": [effort, base]}), maxItems=128),
        "coverage_basis": text,
        "assumptions": arr(text, 1), "not_assessed": arr(text),
        "conditions": obj({k: {"type": "boolean"} for k in
            ("inertials_verified", "motion_states_verified", "ratings_verified", "mount_verified")},
            ("inertials_verified", "motion_states_verified", "ratings_verified", "mount_verified")),
        "provenance": obj({"task_id": text, "revision": text, "generator": text}, ("task_id",)),
    }, ("schema_version", "model", "massless_links", "base", "base_pose", "gravity_m_s2",
         "states", "criteria", "coverage_basis", "assumptions", "not_assessed", "conditions", "provenance"))


def validate(case):
    import jsonschema
    try:
        jsonschema.Draft202012Validator(schema()).validate(case)
    except jsonschema.ValidationError as exc:
        raise ValueError("Motion input: "+exc.message) from None
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Motion inputs must be finite")
        if isinstance(value, str) and not value.strip():
            raise ValueError("Motion text must be nonempty")
        if isinstance(value, dict):
            for v in value.values():
                finite(v)
        if isinstance(value, list):
            for v in value:
                finite(v)
    finite(case)
    for key in ("states", "criteria"):
        if len({s["id"] for s in case[key]}) != len(case[key]):
            raise ValueError("Duplicate motion "+key+" id")
    return case


def read_case(path):
    path = Path(path).resolve()
    case = validate(json.loads(path.read_text(encoding="utf-8-sig")))
    case["model"]["path"] = str((path.parent/case["model"]["path"]).resolve())
    if Path(case["model"]["path"]).suffix.lower() != ".urdf":
        raise ValueError("Motion loads require an explicit URDF tree with SI inertials")
    case["model"]["package_roots"] = {k: str((path.parent/v).resolve())
                                     for k, v in case["model"].get("package_roots", {}).items()}
    robot = read_urdf(case["model"]["path"], case["model"]["package_roots"], case["massless_links"])
    # Cheap preflight includes all coordinates and links, before creating outputs.
    from .motion_solver import kinematics
    for state in case["states"]:
        kinematics(robot, state["positions"], state["velocities"], state["accelerations"])
        if any(load["link"] not in robot["links"] for load in state["loads"]):
            raise ValueError("Motion load references an unknown link")
    for c in case["criteria"]:
        if c["type"] == "joint_effort" and (
                c["joint"] not in robot["joints"] or robot["joints"][c["joint"]]["type"] == "fixed"):
            raise ValueError("Effort criterion needs a movable joint")
    if len(robot["links"]) > 128:
        raise ValueError("Motion checks are bounded to 128 links; select an explicit subtask")
    return case


def plain(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def robot_snapshot(robot):
    return plain({k: v for k, v in robot.items() if k not in ("assets", "path", "sha256")} |
                 {"links": {k: {n: v for n, v in d.items() if n != "visuals"} for k, d in robot["links"].items()}})


def restore_robot(value):
    r = copy.deepcopy(value)
    for link in r["links"].values():
        for key in ("com_m", "inertia_kg_m2"):
            link[key] = np.array(link[key], dtype=float)
    for joint in r["joints"].values():
        for key in ("axis", "origin"):
            joint[key] = np.array(joint[key], dtype=float)
    return r


def contract(case, robot):
    value = copy.deepcopy(case)
    value.pop("model")
    value["provenance"] = {"task_id": case["provenance"]["task_id"]}
    value["inertials"] = plain({n: {k: d[k] for k in ("mass_kg", "com_m", "inertia_kg_m2")}
                                for n, d in robot["links"].items()})
    value["topology"] = plain({n: {k: j[k] for k in ("type", "parent", "child", "axis", "mimic")}
                               for n, j in robot["joints"].items()})
    return value


def calculate(case, robot, progress=None):
    validate(case)
    base = transform(case["base_pose"]["xyz_m"], case["base_pose"]["rpy_rad"])
    states = []
    for spec in case["states"]:
        if progress:
            progress({"stage": "motion", "pose": spec["id"]})
        result = solve(robot, spec["positions"], spec["velocities"], spec["accelerations"],
                       case["gravity_m_s2"], base_pose=base, loads=spec["loads"])
        states.append({"id": spec["id"], **plain(result)})
    criteria = {}
    for c in case["criteria"]:
        if c["type"] == "joint_effort":
            entries = [s["joints"][c["joint"]] for s in states]
            values = [abs(e["effort"]) for e in entries]
            limit = c["max_abs_effort"]
            applicable = all(abs(e["speed"]) <= c["rating_max_abs_speed"] for e in entries)
            unit = entries[0]["effort_unit"]
            position = lambda i: entries[i]["point_world_m"]
        else:
            part = slice(0, 3) if c["type"] == "base_force" else slice(3, 6)
            values = [float(np.linalg.norm(s["base"]["robot_on_base_world"][part])) for s in states]
            limit, applicable = c["limit"], True
            unit = "N" if c["type"] == "base_force" else "N m"
            position = lambda i: states[i]["base"]["point_world_m"]
        i = int(np.argmax(values))
        margin, guard = limit-values[i], 1e-10*max(1., limit, values[i])
        status = ("pass_under_stated_model" if margin > guard else
                  "fail_under_stated_model" if margin < -guard else "indeterminate") if applicable else "indeterminate"
        criteria[c["id"]] = {"status": status, "target": c["target"], "type": c["type"],
                            "governing_state": states[i]["id"], "observed": values[i], "limit": limit,
                            "units": unit, "margin": margin, "utilization": values[i]/limit,
                            "position_world_m": position(i), "rating_speed_applicable": applicable,
                            "all_state_values": dict(zip((s["id"] for s in states), values))}
    resolved = bool(criteria) and all(c["status"] != "indeterminate" for c in criteria.values())
    failed = any(c["status"] == "fail_under_stated_model" for c in criteria.values())
    status = ("fail_under_stated_model" if failed else "pass_under_stated_model") if resolved else "indeterminate"
    return {"schema_version": RESULT_SCHEMA, "analysis": "motion_loads", "status": status,
            "case": copy.deepcopy(case), "robot": robot_snapshot(robot),
            "states": states, "criterion_assessments": criteria,
            "verification": {"momentum_balance_passed": all(s["verification"]["momentum_balance_passed"] for s in states)},
            "evidence_gaps": [k for k, v in case["conditions"].items() if not v],
            "whole_product_pass_available": False,
            "not_assessed": list(dict.fromkeys(NOT_ASSESSED+case["not_assessed"]))}


def _seal(result):
    return digest({k: v for k, v in result.items() if k not in ("evaluation_signal", "evidence_sha256")})


def verify_evidence(result):
    if result["evidence_sha256"] != _seal(result):
        raise ValueError("Motion evidence changed")
    robot = restore_robot(result["robot"])
    if result["task_contract"] != contract(result["case"], robot):
        raise ValueError("Motion contract contradicts the snapshot")
    expected = calculate(result["case"], robot)
    for key in ("states", "criterion_assessments", "status", "verification"):
        if digest(result[key]) != digest(expected[key]):
            raise ValueError("Motion results contradict reconstructed dynamics: "+key)


def signal(result):
    criteria = copy.deepcopy(result.get("criterion_assessments", {}))
    error = None
    try:
        verify_evidence(result)
        valid = result["status"] in ("pass_under_stated_model", "fail_under_stated_model")
    except (ValueError, KeyError, TypeError, ArithmeticError, IndexError) as exc:
        error, valid = str(exc), False
    if not valid:
        for c in criteria.values():
            c["status"] = "indeterminate"
    failed = [c for c in criteria.values() if c["status"] == "fail_under_stated_model"]
    findings = [{"kind": "located_result", "message":
                 f'{c["target"]}: {c["observed"]:.6g} {c["units"]}, limit {c["limit"]:.6g}; '
                 f'listed state {c["governing_state"]}. This is a load/drive check, not a stress hotspot.',
                 "criterion": name, "position_world_m": c["position_world_m"]}
                for name, c in criteria.items()]
    if failed and valid:
        findings.append({"kind": "design_hypothesis", "requires_reanalysis": True,
            "scope": [c["target"] for c in failed],
            "message": "Inspect the governing state's gravity, inertial force and angular-inertia terms. A permitted shorter load arm or mass placement change may reduce demand; merely thickening a link can increase drive loads. Recheck unchanged motion and ratings, plus reach/clearance and structural checks. A lower speed/acceleration is a changed operating requirement, not an automatic CAD improvement."})
    if not valid:
        gaps = [c["target"] for c in criteria.values() if not c["rating_speed_applicable"]]
        findings.append({"kind": "evidence_gap", "message": error or
                         ("Obtain applicable drive ratings at the requested speeds: "+", ".join(gaps) if gaps else
                          "Specify acceptance criteria or resolve a threshold-boundary result before CAD acceptance.")})
    return {"schema_version": "simplecae-signal-1.0", "analysis_status": result.get("status", "invalid"),
            "valid_for_comparison": bool(valid), "feasible_under_stated_model": (not failed) if valid else None,
            "physical_conditions_verified": False, "whole_installation_rating_available": False,
            "task_contract_sha256": digest(result.get("task_contract", {})),
            "task_id": result.get("case", {}).get("provenance", {}).get("task_id"),
            "candidate": result.get("case", {}).get("provenance", {}),
            "utilizations": {k: c["utilization"] for k, c in criteria.items()},
            "bottleneck_margin": None, "conditional_limit": None, "metrics": {},
            "coverage": {"method": "prescribed_rigid_motion", "state_ids": [s["id"] for s in result.get("states", [])],
                         "whole_trajectory": False, "component_strength": False},
            "criterion_assessments": criteria, "feedback": findings,
            "not_assessed": result.get("not_assessed", NOT_ASSESSED)+result.get("evidence_gaps", []),
            "score_meaning": "Loads only at listed states; no trajectory envelope, strength or product rating."}


def analyze(path, out, progress=None):
    from .sources import SourceGuard, source_paths
    path, out = Path(path).resolve(), Path(out).resolve()
    case = read_case(path)
    guard = SourceGuard(source_paths(case) | {path})
    robot = read_urdf(case["model"]["path"], case["model"]["package_roots"], case["massless_links"])
    out.mkdir(parents=True, exist_ok=False)
    write_json(out/"input.json", case)
    (out/"input.urdf").write_bytes(Path(case["model"]["path"]).read_bytes())
    result = calculate(case, robot, progress)
    guard.check()
    result["source_hashes"] = guard.hashes
    result["method"] = {"name": "prescribed rigid-tree Newton-Euler",
                        "implementation_sha256": {p: sha256(Path(__file__).parent/p) for p in
                            ("motion.py", "motion_solver.py", "robot.py")}}
    result["task_contract"] = contract(case, robot)
    result["evidence_sha256"] = _seal(result)
    result["evaluation_signal"] = signal(result)
    write_json(out/"result.json", result)
    write_json(out/"signal.json", result["evaluation_signal"])
    text = html.escape(json.dumps(result["evaluation_signal"], ensure_ascii=False, indent=2))
    (out/"report.html").write_text('<!doctype html><meta charset="utf-8"><title>SimpleCAE motion</title>'
        '<style>body{font:15px/1.6 system-ui;max-width:1000px;margin:32px auto}pre{white-space:pre-wrap}</style>'
        '<h1>运动状态载荷检查</h1><p>仅覆盖列出的状态；载荷或驱动通过不代表强度或产品通过。</p>'
        '<a href="result.json">全部状态、反力与惯性分量</a><pre>'+text+'</pre>', encoding="utf-8")
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
            "verification": result.get("verification", {}),
            "meaning": s["score_meaning"]}


def mount_load_cases(result, world_from_mount, selector, *, name, separate_mount_basis):
    """Existing solid `load_cases` fragment for a separate stationary mount.

    Keeps every simultaneous state. It does not transfer moving-link inertia as
    a point load or certify mount distribution, resonance, or local stress.
    """
    verify_evidence(result)
    if not isinstance(separate_mount_basis, str) or not separate_mount_basis.strip():
        raise ValueError("Explain why the stationary mount is separate from all URDF masses")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Mount port requires a nonempty name")
    from .case import selector as validate_selector
    validate_selector(selector)
    from .motion_solver import kinematics
    matrix = np.asarray(world_from_mount, dtype=float)
    # Reuse the proper-transform checks; the supplied pose has metres of translation.
    robot = restore_robot(result["robot"])
    state = result["case"]["states"][0]
    kinematics(robot, state["positions"], state["velocities"], state["accelerations"], matrix)
    rotation, origin = matrix[:3, :3], matrix[:3, 3]
    cases = []
    for s in result["states"]:
        w = np.array(s["base"]["robot_on_base_world"])
        point = rotation.T@(np.array(s["base"]["point_world_m"])-origin)*1000.
        cases.append({"name": s["id"], "loads": [{
            "name": name, "selector": copy.deepcopy(selector),
            "total_force_n": (rotation.T@w[:3]).tolist(),
            "total_moment_n_mm": (rotation.T@w[3:]*1000.).tolist(),
            "application_point_mm": point.tolist(), "scalable": False}] if np.any(w) else []})
    return {"load_cases": cases, "motion_transfer": {
        "source_evidence_sha256": result["evidence_sha256"], "separate_mount_basis": separate_mount_basis,
        "world_from_mount": matrix.tolist(), "selected_port": copy.deepcopy(selector),
        "meaning": "Robot-on-mount action at the robot root, converted to mount mm/N/Nmm. Keep mount self-weight and other loads separately. Port load distribution is a declared idealization; local mounting/contact and dynamic amplification are not verified."}}
