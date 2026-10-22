"""Small reproducible thermal references and a fixed-requirement CAD iteration."""
import argparse
import copy
import json
from pathlib import Path

from simplecae.api import analyze_case
from simplecae.case import write_json
from simplecae.signals import compare_results
from simplecae.task import start_task, run_task_check
from simplecae.workbench import create_session, add_result, snapshot, export_session


def model(path, width):
    import gmsh
    from simplecae import gmsh_runtime
    gmsh_runtime.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("conduction-reference")
        gmsh.model.occ.addBox(0, 0, 0, 20, width, 10)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh_runtime.finalize()


def case(step, width, revision):
    return {
        "schema_version": "thermal-solid-1.0", "mode": "steady",
        "model": {"path": str(step), "units": "mm", "expected_bbox_mm": [[0, 0, 0], [20, width, 10]]},
        "material": {"name": "Mathematical reference", "basis": "Constant k=2 W/(m K), analytical slab reference; not a product material",
                     "conductivity_w_mk": 2., "temperature_range_c": [0., 200.]},
        "boundaries": [
            {"name": "sink", "target": "sink end", "basis": "Ideal prescribed reservoir",
             "selector": {"type": "plane", "axis": "x", "position_mm": 0.},
             "type": "temperature", "temperature_c": 20.},
            {"name": "input", "target": "heat-source end", "basis": "Fixed total input power",
             "selector": {"type": "plane", "axis": "x", "position_mm": 20.},
             "type": "heat_power", "total_heat_w": .1}],
        "mesh": {"sizes_mm": [5., 3.5, 2.5], "max_elements": 20000, "preserve_boundary_nodes": True},
        "criteria": [{"id": "temperature", "target": "conduction body", "region": {"type": "body"},
                      "max_temperature_c": 28.}],
        "assumptions": ["Constant homogeneous conductivity; all unspecified faces insulated",
                        "Ideal reservoir; no interface resistance or radiation"],
        "not_assessed": ["Manufacturing, real thermal interfaces, thermal stress and lifetime"],
        "conditions": {"properties_verified": False, "boundaries_verified": False},
        "provenance": {"task_id": "thermal-solid-cad-reference", "revision": revision},
    }


def task_manifest(path, case_path):
    data = json.loads((Path(__file__).resolve().parents[1]/"examples/tasks/bench-fixture.task.json").read_text(encoding="utf-8"))
    data.update(task_id="thermal-solid-cad-reference",
                request="数学参考：热功率0.1W、冷端20°C，保持实体最高温度低于28°C；只允许改变导热截面。",
                scenarios=[{"id": "hold", "use": "恒定发热经单体导热到理想冷端", "success": "温度上限28°C；真实界面和物性另测"}],
                unknowns=["无实物物性、热接触和环境标定；不是产品认证"],
                iteration_constraints=["总热功率、材料、温度上限和冷端温度不变", "只改变截面；复核接口"],
                sources=[str(case_path)], cases={"temperature": str(case_path)})
    check = data["checks"][0]
    check.update(id="temperature", question="当前导热截面是否导致超温？", user_impact="超温可能影响接触表面或附近零件的使用。",
                 targets=["导热实体"], reason="有解析解的局部三维传热检查",
                 acceptance="0.1W、20°C冷端、28°C实体最高温度上限保持不变",
                 assumptions=["理想恒温冷端、均匀热输入、常物性"], not_assessed=["实物界面与物性", "热强度和蠕变"],
                 load_path="发热端 → 实体导热 → 冷端", load_basis="明确的0.1W总功率",
                 support_basis="明确的20°C理想恒温冷端", result_criteria=["temperature"])
    physical = data["checks"][1]
    physical.update(id="physical", question="实际物性、界面和温度是否符合假设？",
                    user_impact="这些差异可能推翻理想模型温度", targets=["材料和实际热界面"],
                    reason="仿真不能代替实测", acceptance="材料与安装温度有独立实测依据")
    write_json(path, data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    model(root/"narrow.step", 10.)
    model(root/"wide.step", 20.)
    narrow = case(root/"narrow.step", 10., "narrow")
    wide = case(root/"wide.step", 20., "wide")
    insufficient = copy.deepcopy(wide)
    insufficient["material"]["temperature_range_c"] = [0., 24.]
    transient = copy.deepcopy(wide)
    transient.update(mode="transient", boundaries=[], duration_s=10., time_steps=4,
                     initial_temperature_c=20., volumetric_heat_w_m3=1e6)
    transient["material"].update(density_kg_m3=1000., specific_heat_j_kgk=1000.)
    transient["criteria"][0]["max_temperature_c"] = 35.
    viewer = root/"viewer"
    create_session(viewer, "固体传热 · 保持功率与判据的 CAD 迭代")
    results = {}
    for name, c, label, note in (
        ("narrow", narrow, "01 截面较小 · 超温", "0.1 W / 20 °C 冷端 / 28 °C 上限"),
        ("wide", wide, "02 增大截面 · 模型内通过", "仅把宽度10 mm改为20 mm；功率、材料和判据不变"),
        ("insufficient", insufficient, "03 物性范围不足", "独立失败场景；不是相同条件的 CAD 改进"),
        ("transient", transient, "04 瞬态升温参考", "独立绝热体发热参考；不是前两版的 CAD 比较"),
    ):
        cp = root/(name+".case.json")
        write_json(cp, c)
        r = analyze_case(cp, root/name, predict_capacity=False)
        results[name] = {"status": r["status"], "criteria": r.get("criterion_assessments"),
                         "verification": r.get("verification"), "error": r.get("error")}
        add_result(viewer, root/name/"result.json", label=label, change_note=note)
    comparison = compare_results([root/"narrow/result.json", root/"wide/result.json"])
    task_path = root/"agent.task.json"
    task_manifest(task_path, root/"wide.case.json")
    start_task(task_path, root/"agent")
    status = run_task_check(root/"agent", "temperature", budget_seconds=120)
    export_session(viewer)
    snap = snapshot(viewer)
    checks = {
        "narrow_failed": results["narrow"]["status"] == "fail_under_stated_model",
        "wide_passed": results["wide"]["status"] == "pass_under_stated_model",
        "range_insufficient": results["insufficient"]["status"] == "indeterminate",
        "transient_passed": results["transient"]["status"] == "pass_under_stated_model",
        "cad_comparable": comparison["comparable"],
        "agent_passed": status["checks"][0]["outcome"] == "pass",
        "physical_pending": status["checks"][1]["outcome"] == "pending",
        "no_product_pass": not status["whole_product_pass_available"],
        "viewer_four_fields": len(snap["runs"]) == 4 and all(x["datasets"] for x in snap["runs"]),
    }
    write_json(root/"verification.json", {"checks": checks, "results": results, "comparison": comparison,
                                        "meaning": "Analytical/tool qualification references; no physical product certification."})
    print(json.dumps({"all_passed": all(checks.values()), "checks": checks, "out": str(root)}, ensure_ascii=True))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
