"""Fixed-use CAD iteration and actual Agent modal check, with physical gaps."""
import argparse
import copy
import json
from pathlib import Path
from simplecae.api import analyze_case
from simplecae.case import write_json
from simplecae.signals import compare_results
from simplecae.task import start_task, run_task_check
from simplecae.workbench import create_session, RunRecorder, export_session, snapshot


def model(path, height):
    import gmsh
    from simplecae import gmsh_runtime
    gmsh_runtime.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("modal-reference")
        gmsh.model.occ.addBox(0, 0, 0, 100, 10, height)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh_runtime.finalize()


def case(path, height, revision):
    return {
        "schema_version": "modal-solid-1.0",
        "model": {"path": str(path), "units": "mm", "expected_bbox_mm": [[0, 0, 0], [100, 10, height]]},
        "material": {"name": "Mathematical polymer reference", "basis": "Constant isotropic analytical reference; not qualified print data",
                     "young_mpa": 2000., "poisson": .3, "density_kg_m3": 1200.},
        "support_mode": "supported",
        "supports": [{"name": "root", "target": "built-in end", "basis": "Ideal fixed end mathematical reference",
                      "selector": {"type": "plane", "axis": "x", "position_mm": 0.}}],
        "elastic_mode_count": 2,
        "mesh": {"sizes_mm": [6., 4.5, 3.3], "max_elements": 10000, "preserve_boundary_nodes": True},
        "criteria": [{"id": "motor_band", "type": "avoid_excitation_band", "target": "flexible bracket",
                      "basis": "Scenario-specified motor forcing band; no damping/amplitude data",
                      "band_hz": [110., 140.], "separation_ratio": .05}],
        "assumptions": ["Unprestressed small vibrations; constant isotropic properties; no attached sensor mass"],
        "not_assessed": ["Physical mounting, actual printed material and attached equipment", "Actual vibration amplitude"],
        "conditions": {"properties_verified": False, "mounting_verified": False},
        "provenance": {"task_id": "modal-cad-reference", "revision": revision}}


def task_manifest(path, cp):
    base = Path(__file__).resolve().parents[1]/"examples/tasks/bench-fixture.task.json"
    t = json.loads(base.read_text(encoding="utf-8"))
    t.update(task_id="modal-cad-reference",
             request="参考支架在110–140 Hz激励下避免固有频率冲突；只改变截面，不改变材料和激励条件。",
             scenarios=[{"id": "running", "use": "靠近电机的轻型支架", "success": "声明频段含5%隔离裕量不与固有频率重叠；实物另测"}],
             unknowns=["实际安装刚度、附加设备质量和打印材料未验证", "没有激励幅值和阻尼，不能计算真实振幅"],
             iteration_constraints=["保持激励频段、隔离裕量、材料和根部约束", "可增大截面；另查装配空间"],
             sources=[str(cp)], cases={"resonance": str(cp)})
    c, p = t["checks"][:2]
    c.update(id="resonance", scenario="running", method="fem", question="结构固有频率是否与给定激励频段冲突？",
             user_impact="频率冲突可能影响支架上设备的使用，但不等于已预测实际振幅。",
             targets=["支架"], reason="检查共振频段和主导振型，指导截面修改",
             acceptance="110–140 Hz激励频段，加5%隔离裕量，全部相关低阶模态需覆盖",
             assumptions=["无预应力，理想固定根部"], not_assessed=["实物阻尼", "实际安装和材料", "附加设备"],
             load_path="惯性与弹性恢复力形成模态", load_basis="110–140 Hz激励区间；无力幅值假设",
             support_basis="理想固定端数学参考", result_criteria=["motor_band"])
    p.update(id="physical", scenario="running", question="实际安装和振动是否满足使用要求？", targets=["实际支架和设备"],
             user_impact="安装柔度、附加质量和阻尼可能改变结果", reason="需实测补足模型适用性",
             acceptance="实际材料、设备安装及工作频段的独立振动测量")
    write_json(path, t)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    root = p.parse_args().out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    viewer = root/"viewer"
    create_session(viewer, "模态筛查 · 同一激励频段下的 CAD 迭代")
    results = {}
    for name, height in (("thin", 6.), ("thick", 8.)):
        model(root/(name+".step"), height)
        cp = root/(name+".case.json")
        write_json(cp, case(root/(name+".step"), height, name))
        recorder = RunRecorder(viewer, cp, root/name,
                   "01 薄截面 · 频段冲突" if name == "thin" else "02 增厚 · 重新筛查",
                   "110–140 Hz / 5%隔离裕量；固定根部和材料" if name == "thin" else
                   "只把高度6 mm改为8 mm；保留材料、激励频段和隔离裕量", None)
        r = analyze_case(cp, root/name, predict_capacity=False, progress=recorder)
        if error := recorder.finish():
            raise RuntimeError(error)
        results[name] = {"status": r["status"], "signal": r["evaluation_signal"],
                         "verification": r.get("verification"), "error": r.get("error")}
    missing = case(root/"thick.step", 8., "missing-excitation")
    missing["criteria"] = []
    cp = root/"missing.case.json"
    write_json(cp, missing)
    recorder = RunRecorder(viewer, cp, root/"missing", "03 缺少使用判据",
                           "独立信息缺失场景；有振型不代表已证明适用", None)
    r = analyze_case(cp, root/"missing", predict_capacity=False, progress=recorder)
    if error := recorder.finish():
        raise RuntimeError(error)
    results["missing"] = {"status": r["status"], "signal": r["evaluation_signal"]}
    comparison = compare_results([root/"thin/result.json", root/"thick/result.json"])
    tp = root/"agent.task.json"
    task_manifest(tp, root/"thick.case.json")
    start_task(tp, root/"agent")
    status = run_task_check(root/"agent", "resonance", budget_seconds=120)
    export_session(viewer)
    view = snapshot(viewer)
    checks = {"thin_conflict": results["thin"]["status"] == "fail_under_stated_model",
              "thick_pass": results["thick"]["status"] == "pass_under_stated_model",
              "missing_indeterminate": results["missing"]["status"] == "indeterminate",
              "same_task_cad_comparison": comparison["comparable"],
              "agent_check_pass": status["checks"][0]["outcome"] == "pass",
              "physical_pending": status["checks"][1]["outcome"] == "pending",
              "no_product_pass": not status["whole_product_pass_available"],
              "actual_stage_records": all(sum(e["stage"] == "modal" for e in r["events"]) == 3
                                          for r in view["runs"]),
              "viewer_fields": len(view["runs"]) == 3 and all(
                  r["datasets"] and r["datasets"][0]["physics"] == "modal" for r in view["runs"])}
    write_json(root/"verification.json", {"checks": checks, "results": results, "comparison": comparison})
    print(json.dumps(checks))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
