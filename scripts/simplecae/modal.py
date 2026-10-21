"""Scoped single-solid modal checks: frequencies, shapes and exclusion bands."""
from __future__ import annotations
import copy
import html
import json
import math
from pathlib import Path
import shutil
import numpy as np

from .case import sha256, write_json
from .geometry import make_mesh
from .signals import digest
from . import modal_solver as native
from .modal_matching import compare_meshes

SCHEMA = "modal-solid-1.0"
GUARD = .02
NOT_ASSESSED = [
    "Forced-response amplitude, damping, noise, comfort and vibration fatigue.",
    "Prestress, rotation/gyroscopic effects, contact and nonlinear joints.",
    "Added payloads, multi-body assemblies or elastic supports not present in this single solid.",
    "Actual material/manufacturing and mounting conditions; physical modal tests and product approval."]


def schema():
    from .schemas import obj, arr, enum, S, P, N, B
    from .thermal_solid import schema as thermal_schema
    thermal = thermal_schema()["properties"]
    selector = thermal["boundaries"]["items"]["oneOf"][0]["properties"]["selector"]
    local_refinement = obj({
        "name": S, "selector": selector,
        "size_factor": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "distance_mm": P, "sampling": {"type": "integer", "minimum": 10, "maximum": 500}},
        ("name", "selector", "size_factor", "distance_mm"))
    support = obj({"name": S, "target": S, "basis": S, "selector": selector,
                   "dofs": dict(arr({"type": "integer", "enum": [1, 2, 3]}, 1), maxItems=3, uniqueItems=True)},
                  ("name", "target", "basis", "selector"))
    criteria = {"oneOf": [
        obj({"id": S, "type": {"const": "minimum_elastic_frequency"}, "target": S, "basis": S,
             "minimum_hz": P}, ("id", "type", "target", "basis", "minimum_hz")),
        obj({"id": S, "type": {"const": "avoid_excitation_band"}, "target": S, "basis": S,
             "band_hz": dict(arr({"type": "number", "minimum": 0}, 2), maxItems=2),
             "separation_ratio": {"type": "number", "exclusiveMinimum": 0, "maximum": 1}},
            ("id", "type", "target", "basis", "band_hz", "separation_ratio"))]}
    return obj({
        "schema_version": {"const": SCHEMA}, "model": thermal["model"],
        "material": obj({"name": S, "basis": S, "young_mpa": P, "density_kg_m3": P,
                         "poisson": {"type": "number", "exclusiveMinimum": -1, "exclusiveMaximum": .49}},
                        ("name", "basis", "young_mpa", "density_kg_m3", "poisson")),
        "support_mode": enum("supported", "free_body"), "supports": dict(arr(support), maxItems=32),
        "elastic_mode_count": {"type": "integer", "minimum": 2, "maximum": 30},
        "mesh": obj({"sizes_mm": thermal["mesh"]["properties"]["sizes_mm"],
                     "max_elements": {"type": "integer", "minimum": 1, "maximum": 10000},
                     "local_refinements": arr(local_refinement),
                     "preserve_boundary_nodes": B}, ("sizes_mm",)),
        "criteria": dict(arr(criteria), maxItems=32),
        "assumptions": arr(S, 1), "not_assessed": arr(S),
        "conditions": obj({"properties_verified": B, "mounting_verified": B},
                          ("properties_verified", "mounting_verified")),
        "provenance": thermal["provenance"],
    }, ("schema_version", "model", "material", "support_mode", "supports", "elastic_mode_count",
        "mesh", "criteria", "assumptions", "not_assessed", "conditions", "provenance"))


def read_case(path):
    import jsonschema
    path = Path(path).resolve()
    c = json.loads(path.read_text(encoding="utf-8-sig"))
    try:
        jsonschema.Draft202012Validator(schema()).validate(c)
        json.dumps(c, allow_nan=False)
    except (jsonschema.ValidationError, ValueError) as exc:
        raise ValueError("Modal input: "+str(exc)) from None
    model = Path(c["model"]["path"])
    model = (path.parent/model).resolve() if not model.is_absolute() else model.resolve()
    if not model.is_file() or model.suffix.lower() not in (".step", ".stp"):
        raise ValueError("Modal analysis requires one existing STEP solid")
    c["model"]["path"] = str(model)
    if (c["support_mode"] == "free_body") != (not c["supports"]):
        raise ValueError("Free body needs no supports; supported analysis needs actual restraints")
    sizes = c["mesh"]["sizes_mm"]
    if any(not .35 <= b/a <= .85 for a, b in zip(sizes, sizes[1:])):
        raise ValueError("Three mesh sizes require successive ratios in [0.35, 0.85]")
    c["mesh"].setdefault("max_elements", 10000)
    from .local_mesh import validate_refinements
    validate_refinements(c["mesh"])
    for key, field in (("supports", "name"), ("criteria", "id")):
        values = [s[field] for s in c[key]]
        if len(set(values)) != len(values):
            raise ValueError("Support names and criterion IDs must be unique")
    for criterion in c["criteria"]:
        if criterion["type"] == "avoid_excitation_band":
            a, b = criterion["band_hz"]
            if not a < b:
                raise ValueError("Excitation band must increase")
    return c


def assess(case, levels, matches):
    numerical = (len(levels) == 3 and len(matches) == 2
                 and all(x["audit"]["passed"] for x in levels)
                 and all(x["passed"] for x in matches))
    criteria = {}
    if len(levels) != 3 or len(matches) != 2:
        return "invalid", {}, {"numerical_evidence_passed": False}
    # Correspondence maps the same coarse mode to its successors. For
    # repeated spaces, use all member frequencies instead of arbitrary vectors.
    groups = []
    for group in matches[0]["groups"]:
        coarse = group["coarse_modes"]
        middle = group["fine_modes"]
        latest = sorted({j for g in matches[1]["groups"] if set(g["coarse_modes"]) & set(middle)
                         for j in g["fine_modes"]})
        # Require the same eigenspace dimension across both refinements.
        if len(latest) != len(coarse):
            numerical = False
        values = ([levels[0]["elastic_frequencies_hz"][i] for i in coarse]
                  +[levels[1]["elastic_frequencies_hz"][i] for i in middle]
                  +[levels[2]["elastic_frequencies_hz"][i] for i in latest])
        groups.append({"mesh_mode_indices": [coarse, middle, latest],
                       "lower_hz": min(values)*(1-GUARD), "upper_hz": max(values)*(1+GUARD),
                       "computed_hz": values})
    coverage = min(l["elastic_frequencies_hz"][-1] for l in levels)*(1-GUARD)
    for spec in case["criteria"]:
        entry = dict(spec, status="indeterminate")
        if spec["type"] == "minimum_elastic_frequency":
            first = min(groups, key=lambda g: g["lower_hz"])
            entry.update(frequency_interval_hz=[first["lower_hz"], first["upper_hz"]],
                         mode_group=first["mesh_mode_indices"])
            if numerical:
                if first["lower_hz"] > spec["minimum_hz"]:
                    entry["status"] = "pass_under_stated_model"
                elif first["upper_hz"] < spec["minimum_hz"]:
                    entry["status"] = "fail_under_stated_model"
        else:
            lo, hi = spec["band_hz"]
            lo *= 1-spec["separation_ratio"]
            hi *= 1+spec["separation_ratio"]
            overlap = [g for g in groups if g["upper_hz"] >= lo and g["lower_hz"] <= hi]
            contained = [g for g in overlap if g["lower_hz"] >= lo and g["upper_hz"] <= hi]
            entry.update(exclusion_band_hz=[lo, hi], mode_groups=overlap,
                         covered_upper_hz=coverage, band_coverage_passed=coverage > hi)
            if numerical:
                if contained:
                    entry["status"] = "fail_under_stated_model"
                elif not overlap and coverage > hi:
                    entry["status"] = "pass_under_stated_model"
        criteria[spec["id"]] = entry
    statuses = [c["status"] for c in criteria.values()]
    status = ("indeterminate" if not numerical or not statuses or "indeterminate" in statuses else
              "fail_under_stated_model" if "fail_under_stated_model" in statuses else "pass_under_stated_model")
    return status, criteria, {"numerical_evidence_passed": bool(numerical),
                              "frequency_guard_ratio": GUARD, "covered_upper_hz": coverage,
                              "shape_correspondence": matches}


def analyze(path, out, ccx=None, timeout=300, *, progress=None):
    from .solver import execute, find_ccx
    from .progress import emit
    path, out = Path(path).resolve(), Path(out).resolve()
    c = read_case(path)
    source = {str(p): sha256(p) for p in (path, Path(c["model"]["path"]))}
    out.mkdir(parents=True, exist_ok=False)
    write_json(out/"input.json", c)
    shutil.copyfile(c["model"]["path"], out/"input.step")
    contract = copy.deepcopy(c)
    contract.pop("model"); contract.pop("mesh"); contract.pop("elastic_mode_count")
    contract["provenance"] = {"task_id": c["provenance"]["task_id"]}
    r = {"schema_version": "modal-solid-result-1.0", "analysis": "modal",
         "case": c, "source": source, "levels": [], "status": "invalid", "task_contract": contract,
         "whole_product_pass_available": False, "not_assessed": NOT_ASSESSED+c["not_assessed"],
         "method": {"name": "Unprestressed isotropic C3D10 normal modes",
                    "implementation_sha256": {n: sha256(Path(__file__).with_name(n)) for n in
                        ("modal.py", "modal_solver.py", "modal_matching.py", "geometry.py", "probes.py", "solver.py")}}}
    fields = []
    free = c["support_mode"] == "free_body"
    rigid = 6 if free else 0
    count = c["elastic_mode_count"]+rigid+2
    matches = []
    try:
        executable = find_ccx(ccx)
        for i, h in enumerate(c["mesh"]["sizes_mm"]):
            directory = out/f"mesh-{i+1}"
            directory.mkdir()
            emit(progress, "mesh", level=i+1, mesh_size_mm=h)
            mesh = make_mesh(c, h, directory, allow_free_body=free)
            deck = directory/"modes.inp"
            native.write_deck(c, mesh, deck, count)
            emit(progress, "modal", level=i+1, requested_modes=count)
            solver = execute(executable, deck, timeout=timeout, analysis_type="frequency")
            parsed = native.parse_dat(deck.with_suffix(".dat"), mesh[0], count)
            emit(progress, "modal_audit", level=i+1)
            audit = native.audit(directory, c["material"], mesh, parsed, free_body=free)
            ids, eigenvalues, frequencies, shapes = parsed
            np.savez_compressed(directory/"modes.npz", node_ids=ids, eigenvalues=eigenvalues,
                                frequencies_hz=frequencies, shapes=shapes)
            # A nodal antinode is a location cue, not a claimed continuous maximum.
            peaks = np.argmax(np.linalg.norm(shapes, axis=2), axis=1)
            r["levels"].append({"directory": directory.name, "mesh_size_mm": h, "solver": solver,
                "audit": audit, "node_count": len(ids), "element_count": len(mesh[1]),
                "eigenvalues_rad2_s2": eigenvalues.tolist(), "frequencies_hz": frequencies.tolist(),
                "elastic_frequencies_hz": frequencies[rigid:].tolist(),
                "nodal_antinodes_mm": [mesh[0][int(ids[j])].tolist() for j in peaks]})
            fields.append(parsed)
            if i:
                emit(progress, "modal_match", level=i+1)
                matches.append(compare_meshes(out/f"mesh-{i}", directory, fields[-2], fields[-1],
                                              rigid, rigid))
        emit(progress, "assessment")
        status, criteria, verification = assess(c, r["levels"], matches)
        r.update(status=status, criterion_assessments=criteria, verification=verification)
        if any(sha256(Path(p)) != h for p, h in source.items()):
            raise ValueError("Modal source changed during analysis")
    except (ValueError, RuntimeError, OSError, ArithmeticError, np.linalg.LinAlgError) as exc:
        r.update(status="invalid", error=f"{type(exc).__name__}: {exc}")
    files = [p for p in out.rglob("*") if p.name in ("mesh.npz", "modes.npz", "modes.inp", "mesh.json")]
    files += [out/"input.json", out/"input.step"]
    r["evidence_files"] = {str(p): sha256(p) for p in files}
    r["evidence_sha256"] = digest(r)
    r["evaluation_signal"] = signal(r)
    emit(progress, "report", status=r["status"])
    write_json(out/"result.json", r)
    write_json(out/"signal.json", r["evaluation_signal"])
    (out/"report.html").write_text('<!doctype html><meta charset="utf-8"><h1>模态与共振频段筛查</h1>'
        '<p>振型幅度任意；本结果不提供真实振幅、噪声、寿命或产品通过结论。</p><pre>'
        +html.escape(json.dumps(r["evaluation_signal"], ensure_ascii=False, indent=2))+"</pre>", encoding="utf-8")
    return r


def signal(result):
    c = result.get("case", {})
    valid = result.get("status") in ("pass_under_stated_model", "fail_under_stated_model")
    error = result.get("error")
    if valid:
        try:
            expected = digest({k: v for k, v in result.items() if k not in ("evidence_sha256", "evaluation_signal")})
            if expected != result["evidence_sha256"] or not result.get("evidence_files"):
                raise ValueError("Modal evidence changed or is incomplete")
            if any(sha256(Path(p)) != h for p, h in result["evidence_files"].items()):
                raise ValueError("Modal native/field evidence changed")
            status, criteria, verification = assess(c, result["levels"], result["verification"]["shape_correspondence"])
            if (status, criteria, verification) != (result["status"], result["criterion_assessments"], result["verification"]):
                raise ValueError("Modal conclusion contradicts numerical evidence")
        except (KeyError, ValueError, OSError) as exc:
            valid, error = False, str(exc)
    criteria = copy.deepcopy(result.get("criterion_assessments", {}))
    if not valid:
        criteria = {k: dict(v, status="indeterminate") for k, v in criteria.items()}
    findings = []
    if valid and result["status"] == "fail_under_stated_model":
        rigid = 6 if c["support_mode"] == "free_body" else 0
        finest = result["levels"][-1]
        for criterion in criteria.values():
            if criterion["status"] != "fail_under_stated_model":
                continue
            groups = ([criterion["mode_group"]] if "mode_group" in criterion else
                      [g["mesh_mode_indices"] for g in criterion.get("mode_groups", [])])
            indices = sorted({i for g in groups for i in g[2]})
            locations = "; ".join(
                f"{i+1}阶 {finest['elastic_frequencies_hz'][i]:.5g} Hz，节点振幅较大处 "
                f"{finest['nodal_antinodes_mm'][i+rigid]} mm" for i in indices)
            findings.append({"kind": "modal_observation", "criterion": criterion["id"],
                "target": criterion["target"],
                "modes": [{"elastic_mode": i+1, "frequency_hz": finest["elastic_frequencies_hz"][i],
                           "nodal_antinode_mm": finest["nodal_antinodes_mm"][i+rigid]} for i in indices],
                "message": f"{criterion['target']}：{locations}。这些振型与声明判据冲突，请查看变形方向与安装。坐标仅用于定位节点振动形态，不代表应力热点或损伤位置。"})
        findings.append({"kind": "design_hypothesis", "requires_reanalysis": True,
            "message": "Inspect the conflicting mode shape and actual mounting. For a permitted stiffness increase, shorten unsupported spans or increase section inertia along the flexing direction; adding mass can lower frequency. A frequency-band conflict may require moving the mode above or below the band. Preserve excitation bands, density/material and criteria; recheck clearance and static load paths."})
    elif not valid:
        gaps = []
        if not c.get("criteria"):
            gaps.append("缺少使用判据：请提供实际激励频段及隔离要求，或有依据的最低弹性频率；有振型不代表满足用途。")
        for criterion in result.get("criterion_assessments", {}).values():
            if criterion.get("band_coverage_passed") is False:
                gaps.append(f"{criterion['id']}: 模态数量不足以覆盖声明频段；增加 elastic_mode_count 后复查。")
        if result.get("verification", {}).get("numerical_evidence_passed") is False:
            gaps.append("特征对、质量积分或跨网格振型对应未通过；先检查各档 audit 与 shape_correspondence，不应据此判断 CAD 太弱。")
        if error:
            gaps.insert(0, error)
        if not gaps:
            gaps.append("频率不确定区间触及判据边界；需要进一步细化或补充实测，不能直接作有利判定。")
        findings.extend({"kind": "evidence_gap", "message": message} for message in gaps)
    return {"schema_version": "simplecae-signal-1.0", "analysis_status": result.get("status", "invalid"),
            "valid_for_comparison": bool(valid),
            "feasible_under_stated_model": (result["status"] == "pass_under_stated_model") if valid else None,
            "whole_installation_rating_available": False, "physical_conditions_verified": False,
            "task_contract_sha256": digest(result.get("task_contract", c)),
            "task_id": c.get("provenance", {}).get("task_id"), "candidate": c.get("provenance", {}),
            "utilizations": {}, "bottleneck_margin": None, "conditional_limit": None,
            "criterion_assessments": criteria, "coverage": {"method": "single_solid_normal_modes"},
            "metrics": {"elastic_frequencies_hz": result["levels"][-1]["elastic_frequencies_hz"] if result.get("levels") else [],
                        "nodal_antinodes_mm": result["levels"][-1]["nodal_antinodes_mm"] if result.get("levels") else []},
            "feedback": findings, "not_assessed": result.get("not_assessed", NOT_ASSESSED),
            "score_meaning": "Frequency separation and located mode shapes, not vibration amplitude or product approval."}


def design_feedback(result, context, run_state):
    s = signal(result)
    valid = s["valid_for_comparison"] and run_state == "completed"
    return {"model_status": result["status"], "valid_for_comparison": valid,
            "conditional_model_pass": s["feasible_under_stated_model"] if valid else None,
            "whole_product_pass_available": False, "criterion_assessments": s["criterion_assessments"],
            "utilizations": {}, "findings": s["feedback"], "observations": list(s["criterion_assessments"].values()),
            "next_actions": [f["message"] for f in s["feedback"]],
            "verification": result.get("verification", {}),
            "not_assessed": list(dict.fromkeys(context["not_assessed"]+s["not_assessed"]))}


def viewer_dataset(path, result):
    """One geometry plus all elastic modes, avoiding duplicated mesh payloads."""
    import zipfile
    from .contact import surface_index
    if len(result.get("levels", [])) < 3:
        return None
    root = Path(path).resolve().parent
    directory = (root/result["levels"][2]["directory"]).resolve()
    if not directory.is_relative_to(root):
        raise ValueError("Modal field directory must stay inside result root")
    for name in ("mesh.npz", "modes.npz"):
        with zipfile.ZipFile(directory/name) as z:
            if sum(i.file_size for i in z.infolist()) > 128*1024**2:
                raise ValueError("Modal display evidence exceeds expanded size limit")
    with np.load(directory/"mesh.npz", allow_pickle=False) as d, \
         np.load(directory/"modes.npz", allow_pickle=False) as f:
        if any(not np.isfinite(f[k]).all() for k in f.files):
            raise ValueError("Nonfinite modal display")
        ids, xyz = d["node_ids"], d["xyz"]
        lookup = {int(n): i for i, n in enumerate(ids)}
        field_rows = {int(n): i for i, n in enumerate(f["node_ids"])}
        rows = [field_rows[int(n)] for n in ids]
        conn = np.array([[lookup[int(n)] for n in ns] for ns in d["surface_tri6"]])
        index = surface_index(dict(zip(map(int, d["element_ids"]), d["connectivity"].tolist())))
        owners = [index[tuple(sorted(map(int, row[:3])))][0][0] for row in d["surface_tri6"]]
        sub = ((0, 3, 5), (3, 1, 4), (5, 4, 2), (3, 4, 5))
        triangles = [ns[list(face)].tolist() for ns in conn for face in sub]
        span = float(np.linalg.norm(np.ptp(xyz, axis=0)))
        rigid = 6 if result["case"]["support_mode"] == "free_body" else 0
        modes = []
        for i in range(rigid, len(f["frequencies_hz"])):
            shape = f["shapes"][i, rows]
            magnitude = np.linalg.norm(shape, axis=1)
            normalizer = float(np.max(magnitude))
            if normalizer <= 0:
                raise ValueError("Zero modal display field")
            modes.append({"native_mode": i+1, "elastic_mode": i-rigid+1,
                          "frequency_hz": float(f["frequencies_hz"][i]),
                          "normalized_shape": (shape/normalizer).tolist(),
                          "nodal_magnitude": (magnitude/normalizer).tolist()})
        mesh = json.loads((directory/"mesh.json").read_text(encoding="utf-8"))
        return {"id": "modal-solid", "label": "弹性振型 · 最细网格", "physics": "modal",
                "xyz": xyz.tolist(), "triangles": triangles,
                "face_ids": np.repeat(d["surface_face_ids"], 4).tolist(),
                "element_ids": np.repeat(owners, 4).tolist(),
                "displacements": np.zeros_like(xyz).tolist(),
                "modal_modes": modes, "display_amplitude_mm": .02*span,
                "rigid_mode_count": rigid, "stress": [], "strength": [], "assessment": {},
                "results": {}, "mesh": mesh, "case": result["case"],
                "meaning": "All elastic eigenvectors; nodal normalization and slow animation are arbitrary display choices. Not physical vibration displacement or playback frequency."}
