"""Small rigid-robot iteration reference; no physical motor/product claim."""
import argparse
import copy
import json
from pathlib import Path

from simplecae.api import analyze_case
from simplecae.case import write_json
from simplecae.signals import compare_results
from simplecae.task import start_task, run_task_check
from simplecae.workbench import create_session, RunRecorder, export_session, snapshot


def make_case(root, length):
    model = root/"mechanism.urdf"
    links = "".join(f'<link name="{name}"><inertial><origin xyz="{com} 0 0"/>'
                    '<mass value="1"/><inertia ixx=".001" iyy=".004" izz=".004" '
                    'ixy="0" ixz="0" iyz="0"/></inertial></link>' for name, com in (("arm", .2), ("payload", .1)))
    model.write_text('<robot name="motion-reference"><link name="base"/>'+links+
        '<joint name="drive" type="revolute"><parent link="base"/><child link="arm"/>'
        '<axis xyz="0 0 1"/><limit lower="-3" upper="3" effort="100" velocity="20"/></joint>'
        f'<joint name="attachment" type="fixed"><parent link="arm"/><child link="payload"/><origin xyz="{length} 0 0"/>'
        '</joint></robot>', encoding="utf-8")
    return {"schema_version": "motion-loads-1.0", "model": {"path": str(model), "units": "m"},
            "massless_links": ["base"], "base": "fixed",
            "base_pose": {"xyz_m": [0, 0, 0], "rpy_rad": [0, 0, 0]}, "gravity_m_s2": [0, -9.81, 0],
            "states": [{"id": name, "basis": "明确的数学参考状态；未声称覆盖完整运动轨迹",
                        "positions": {"drive": 0.}, "velocities": {"drive": speed},
                        "accelerations": {"drive": acceleration}, "loads": []}
                       for name, speed, acceleration in [("保持", 0., 0.), ("加速", 2., 3.), ("制动", 2., -3.)]],
            "criteria": [{"id": "drive", "type": "joint_effort", "joint": "drive", "target": "驱动输出轴",
                          "basis": "数学参考：0–3 rad/s范围允许6 N·m；不是实物电机额定数据",
                          "max_abs_effort": 6., "rating_max_abs_speed": 3.}],
            "coverage_basis": "仅比较保持、加速、制动三个明确状态；不声称轨迹包络或热占空比",
            "assumptions": ["刚体、固定基座、理想无损关节；载荷通过URDF惯性连杆建模"],
            "not_assessed": ["实物驱动额定值、连杆强度和刚度、完整轨迹、工作空间与碰撞"],
            "conditions": dict.fromkeys(("inertials_verified", "motion_states_verified", "ratings_verified", "mount_verified"), False),
            "provenance": {"task_id": "motion-iteration-reference", "revision": root.name}}


def task_manifest(cp, out):
    template = Path(__file__).resolve().parents[1]/"examples/tasks/bench-fixture.task.json"
    task = json.loads(template.read_text(encoding="utf-8"))
    task.update(task_id="motion-iteration-reference",
                request="核对同一组运动状态下的驱动需求；允许缩短负载安装悬臂，另查工作空间和实际结构",
                scenarios=[{"id": "operation", "use": "固定基座机构按指定状态保持、加速和制动",
                            "success": "在额定速度适用范围内满足6 N·m驱动限值；实物与结构另查"}],
                unknowns=["实物驱动、打印/制造数据尚未核验", "未覆盖完整运动轨迹"],
                iteration_constraints=["保持所有质量、惯量、重力、速度、加速度和6 N·m限值", "仅改变负载安装位置；需另查可达范围"],
                sources=[str(cp)], cases={"drive": str(cp)})
    check, physical = task["checks"][:2]
    check.update(id="drive", scenario="operation", method="calculation", result_criteria=["drive"],
                 question="驱动输出轴能否满足三个已声明的运动状态？", user_impact="驱动需求过高可能使动作无法按计划执行",
                 reason="先判断惯性和重力对驱动需求的影响", targets=["驱动输出轴"],
                 acceptance="声明速度范围内，所需输出力矩绝对值小于6 N·m",
                 assumptions=["固定基座、刚体连杆、理想无损关节"], not_assessed=["真实电机和结构", "可达范围"],
                 load_path="连杆与负载惯性及重力 -> 驱动轴 -> 基座",
                 load_basis="每状态显式q、qd和qdd，不添加任意动载系数", support_basis="静止固定基座")
    physical.update(id="physical", scenario="operation", question="实际驱动、工作空间和结构是否满足要求？",
                    user_impact="较短悬臂可能影响可达范围；力矩通过不能代替结构或实物验收",
                    targets=["整机"], reason="补足运动载荷模型以外的证据", acceptance="独立的结构、空间及实物检查")
    write_json(out, task)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    root = p.parse_args().out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    viewer = root/"viewer"
    create_session(viewer, "运动载荷 · 缩短悬臂，保持运动与判据")
    records = {}
    for name, length, title in [
        ("long", .4, "01 长悬臂 · 驱动力矩超限"),
        ("short", .15, "02 缩短安装悬臂 · 重算"),
        ("missing", .15, "03 缺少驱动判据"),
        ("speed-gap", .15, "04 额定速度适用范围不足"),
    ]:
        folder = root/name
        folder.mkdir()
        case = make_case(folder, length)
        if name == "missing":
            case["criteria"] = []
        if name == "speed-gap":
            case["criteria"][0].update(rating_max_abs_speed=1., basis="仅提供0–1 rad/s额定范围，缺少2 rad/s证据")
        cp = folder/"case.json"
        write_json(cp, case)
        recorder = RunRecorder(viewer, cp, folder/"run", title,
                               "数学参考；固定质量/惯量和声明运动状态；实物与工作空间另查", None)
        r = analyze_case(cp, folder/"run", progress=recorder, predict_capacity=False)
        if error := recorder.finish():
            raise RuntimeError(error)
        records[name] = {"status": r["status"], "criteria": r["criterion_assessments"],
                         "whole_product_pass_available": r["whole_product_pass_available"]}
    comparison = compare_results([root/"long/run/result.json", root/"short/run/result.json"])
    task_manifest(root/"short/case.json", root/"agent.task.json")
    start_task(root/"agent.task.json", root/"agent", viewer_session=viewer)
    status = run_task_check(root/"agent", "drive", budget_seconds=40)
    export_session(viewer)
    view = snapshot(viewer)
    plan = json.loads((root/"agent/inputs/plan.json").read_text(encoding="utf-8"))
    checks = {"long_fail": records["long"]["status"] == "fail_under_stated_model",
              "short_pass": records["short"]["status"] == "pass_under_stated_model",
              "missing_indeterminate": records["missing"]["status"] == "indeterminate",
              "speed_range_indeterminate": records["speed-gap"]["status"] == "indeterminate",
              "unchanged_motion_comparison": comparison["comparable"],
              "agent_pass": status["checks"][0]["outcome"] == "pass",
              "physical_pending": status["checks"][1]["outcome"] == "pending",
              "no_product_pass": not status["whole_product_pass_available"],
              "viewer_all_states": all(len(r["motion_display"]["states"]) == 3 for r in view["runs"]),
              "actual_stages": all(sum(e["stage"] == "motion" for e in r["events"]) == 3 for r in view["runs"]),
              "usage_scenario_bound": all(c["scenario"] == "operation" for c in plan["checks"]) and
                                     "6 N·m" in plan["scenarios"][0]["success"]}
    write_json(root/"verification.json", {"checks": checks, "results": records, "comparison": comparison})
    print(json.dumps(checks))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
