"""STEP section iteration + independently derived axial stress + data screens.

All material curves are mathematical references, never PETG/PLA material data.
"""
import argparse
import json
import math
from pathlib import Path

from simplecae.api import analyze_case
from simplecae.case import write_json, sha256
from simplecae.signals import compare_results
from simplecae.task import start_task, run_task_check
from simplecae.workbench import create_session, RunRecorder, export_session, snapshot


def evidence(path, basis):
    return {"path": str(path), "sha256": sha256(path), "basis": basis}


def source(root, name, value):
    p = root/(name+".json")
    write_json(p, value)
    return evidence(p, "可复算的数学参考数据；不构成真实材料标定")


def section(root, thickness):
    import gmsh
    from simplecae import gmsh_runtime
    p = root/"section.step"
    gmsh_runtime.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("uniform-axial-reference")
        tag = gmsh.model.occ.addBox(0, 0, 0, 100., 5., thickness)
        gmsh.model.occ.synchronize()
        volume = gmsh.model.occ.getMass(3, tag)
        gmsh.write(str(p))
    finally:
        gmsh_runtime.finalize()
    # This reference is an exact rectangular section, so F/A uses its declared
    # dimensions. OCC mass integration independently checks the generated solid.
    # Do not perturb a curve endpoint by numerical volume-integration roundoff.
    area = 5.*thickness
    cad_area = volume/100.
    if not math.isclose(cad_area, area, rel_tol=1e-12, abs_tol=0.):
        raise ValueError("Generated STEP volume contradicts the rectangular reference section")
    return p, area, cad_area


def make_case(root, mode, revised=False, missing=False):
    thickness = (8. if revised else 4.) if mode == "fatigue" else (4. if revised else 2.)
    model, area, cad_area = section(root, thickness)
    material = {"id": "mathematical-reference", "manufacture": "ideal homogeneous reference", "orientation": "axial X"}
    curve = {"material": material, "temperature_c": 20., "kind": "mathematical_reference",
             "stress_definition": "signed_uniaxial_local",
             "applicability_basis": "仅用于验证方程和工作流的数学数据；不能用于真实零件材料寿命"}
    point = {"id": "section", "target": "均匀轴向截面", "position_mm": [50., 2.5, thickness/2],
             "frame": "STEP part", "direction": [1, 0, 0]}
    if mode == "fatigue":
        curve["curves"] = [{"stress_ratio": -1., "amplitude_mpa": [100., 50., 25.],
                            "cycles_to_failure": [10000., 100000., 1000000.]}]
        service = [{"id": "normal", "cycles": 10000., "basis": "保持±1000 N、10000次的既定使用要求"},
                   {"id": "peak", "cycles": 2000., "basis": "保持±2000 N、2000次的既定使用要求"}]
        point["blocks"] = [{"service_id": name, "minimum_mpa": -force/area, "maximum_mpa": force/area}
                           for name, force in (("normal", 1000.), ("peak", 2000.))]
        criterion = {"id": "durability", "point": "section", "basis": "固定的数学参考验收限值", "max_damage": .2}
        extra, loads = {}, {"force_n": {"normal": [-1000., 1000.], "peak": [-2000., 2000.]}}
    else:
        curve.update(strain_measure="creep_only_magnitude", stress_levels_mpa=[10., 20.],
                     times_s=[0., 100., 1000.], strain=[[0., .001, .01], [0., .004, .04]])
        service = {"duration_s": 500., "history": "constant_from_unloaded", "basis": "保持200 N与500 s持续时间；理想恒定单轴应力"}
        point["stress_mpa"] = 200./area
        criterion = {"id": "durability", "point": "section", "basis": "固定的1%纯蠕变应变限值", "max_strain": .01}
        extra, loads = {"strain_measure": "creep_only_magnitude"}, {"force_n": 200.}
    curve["source"] = source(root, "material-curve", curve)
    stress_source = source(root, "stress-evidence", {
        "formula": "signed axial stress MPa = force N / exact rectangular width*thickness mm2",
        "model_sha256": sha256(model), "cad_volume_derived_area_mm2": cad_area,
        "analytic_area_mm2": area, "width_mm": 5., "thickness_mm": thickness,
        "cad_area_crosscheck_relative_tolerance": 1e-12,
        "length_mm": 100., "uniform_uniaxial_assumption": True, "point": point, **loads,
        "limits": "数学均匀杆截面，未计算端部夹持热点或真实材料；不是有限元场"})
    return {"schema_version": mode+"-data-1.0", "material": material, "temperature_c": 20.,
            "stress_definition": "signed_uniaxial_local", "material_curve": None if missing else curve,
            "geometry_source": evidence(model, "实际STEP均匀截面数学参考；不含真实端部连接"),
            "stress_source": stress_source, "service_source": source(root, "service", {"service": service, **loads}),
            "service": service, "points": [point], "criteria": [criterion], **extra,
            "assumptions": ["仅在理想均匀轴向截面采用F/A；材料曲线为数学参考", "只改变截面面积；温度、载荷、次数或时长及限值不变"],
            "not_assessed": ["端部连接及应力集中", "真实材料和制造数据", "整件或产品寿命与破断"],
            "conditions": dict.fromkeys(("material_data_verified", "stress_history_verified", "service_verified"), False),
            "provenance": {"task_id": mode+"-iteration-reference", "revision": root.name}}


def task_manifest(cp, mode, out):
    t = json.loads((Path(__file__).resolve().parents[1]/"examples/tasks/bench-fixture.task.json").read_text(encoding="utf-8"))
    title = "反复轴向使用的累积疲劳损伤" if mode == "fatigue" else "持续轴向承载的蠕变应变"
    t.update(task_id=mode+"-iteration-reference", request="检查"+title+"，只改变均匀截面",
             scenarios=[{"id": "service", "use": title, "success": "给定材料曲线范围内满足固定损伤/应变限值，实物另测"}],
             unknowns=["数学参考曲线不能替代真实材料数据", "端部连接、应力集中及其他位置未核验"],
             iteration_constraints=["保持材料数据、温度、载荷、次数/时长和判据", "只改变均匀截面并重新计算应力"],
             sources=[str(cp)], cases={"durability": str(cp)})
    check, physical = t["checks"][:2]
    check.update(id="durability", scenario="service", method="calculation", result_criteria=["durability"],
                 question="所选截面是否满足声明的耐久判据？", user_impact="重复使用或长时承载可能先于静力强度限制使用",
                 targets=["均匀轴向截面"], reason="选择与使用历程相关的材料曲线，判断几何改动方向",
                 acceptance="声明位置的损伤或应变低于固定限值",
                 assumptions=["理想均匀轴向应力，数学材料曲线"], not_assessed=["真实材料", "端部连接", "整件寿命"],
                 load_path="轴向力 -> 均匀截面", load_basis="来源绑定的固定载荷历程", support_basis="F/A均匀截面数学假设；端部另查")
    physical.update(id="physical", scenario="service", question="实际材料、端部连接和整件耐久性是否满足要求？",
                    targets=["完整零件"], user_impact="局部数学模型通过不能证明实际寿命",
                    reason="需要实际数据及未建模部位验证", acceptance="实际制造材料、完整载荷路径和实物验证")
    write_json(out, t)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    root = p.parse_args().out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    viewer = root/"viewer"
    create_session(viewer, "耐久检查 · 固定使用条件，改变截面")
    records, checks = {}, {}
    for mode, label in (("fatigue", "疲劳"), ("creep", "蠕变")):
        for revision, revised, missing in (("original", False, False), ("revised", True, False), ("missing", True, True)):
            name = mode+"-"+revision
            folder = root/name
            folder.mkdir()
            cp = folder/"case.json"
            write_json(cp, make_case(folder, mode, revised, missing))
            caption = label+" · "+{"original": "原截面失败", "revised": "加大截面重算", "missing": "缺少材料曲线"}[revision]
            recorder = RunRecorder(viewer, cp, folder/"run", caption,
                                   "数学参考；只改变截面面积，保留原载荷、使用历程、温度、材料曲线和限值", None)
            result = analyze_case(cp, folder/"run", progress=recorder, predict_capacity=False)
            if error := recorder.finish():
                raise RuntimeError(error)
            records[name] = {"status": result["status"], "points": result["points"],
                             "criteria": result["criterion_assessments"]}
        comparison = compare_results([root/(mode+"-original")/"run/result.json", root/(mode+"-revised")/"run/result.json"])
        checks[mode+"_same_service_comparison"] = comparison["comparable"]
        for revision, status in (("original", "fail_under_stated_model"), ("revised", "pass_under_stated_model"),
                                 ("missing", "indeterminate")):
            checks[mode+"_"+revision] = records[mode+"-"+revision]["status"] == status
        tp = root/(mode+".task.json")
        task_manifest(root/(mode+"-revised")/"case.json", mode, tp)
        start_task(tp, root/(mode+"-agent"), viewer_session=viewer)
        status = run_task_check(root/(mode+"-agent"), "durability", budget_seconds=40)
        checks[mode+"_agent_pass_physical_pending"] = status["checks"][0]["outcome"] == "pass" and status["checks"][1]["outcome"] == "pending"
        checks[mode+"_no_product_pass"] = not status["whole_product_pass_available"]
    export_session(viewer)
    view = snapshot(viewer)
    checks["viewer_bound_points"] = all(r.get("durability_display", {}).get("points") for r in view["runs"])
    checks["actual_stages"] = all(sum(e["stage"] == "durability" for e in r["events"]) == 1 for r in view["runs"])
    write_json(root/"verification.json", {"checks": checks, "results": records})
    print(json.dumps(checks))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
