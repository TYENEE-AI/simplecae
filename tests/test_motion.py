import copy
import json
from pathlib import Path

import numpy as np
import pytest

from simplecae.api import analyze_case, check_case
from simplecae.case import write_json
from simplecae.motion import signal, mount_load_cases
from simplecae.signals import compare_results
from simplecae.schemas import check_contract
from simplecae.task import start_task, run_task_check, task_status
from simplecae.workbench import snapshot
from test_motion_solver import link, joint


def case(tmp_path, length=.4, limit=6.):
    model = tmp_path/"mechanism.urdf"
    model.write_text('<robot name="motion-reference"><link name="base"/>'+
                     link("a", 1., (.2, 0, 0))+link("payload", 1., (.1, 0, 0))+
                     joint("drive", "base", "a")+
                     joint("attachment", "a", "payload", "fixed", xyz=(length, 0, 0))+
                     '</robot>', encoding="utf-8")
    c = {"schema_version": "motion-loads-1.0",
         "model": {"path": str(model), "units": "m"}, "massless_links": ["base"], "base": "fixed",
         "base_pose": {"xyz_m": [0, 0, 0], "rpy_rad": [0, 0, 0]}, "gravity_m_s2": [0, -9.81, 0],
         "states": [{"id": name, "basis": "Explicit mathematical test state; not a continuous trajectory",
                     "positions": {"drive": 0.}, "velocities": {"drive": speed},
                     "accelerations": {"drive": acceleration}, "loads": []}
                    for name, speed, acceleration in [("hold", 0., 0.), ("accelerate", 2., 3.), ("brake", 2., -3.)]],
         "criteria": [{"id": "drive", "type": "joint_effort", "target": "drive output",
                       "basis": "Mathematical reference allowable torque over 0-3 rad/s; not a motor catalog rating",
                       "joint": "drive", "max_abs_effort": limit, "rating_max_abs_speed": 3.}],
         "coverage_basis": "Three explicit states, no full-trajectory or RMS assertion",
         "assumptions": ["Rigid links, stationary fixed base, lossless ideal joints"],
         "not_assessed": ["Physical drive, link strength, workspace, impact and thermal duty"],
         "conditions": dict.fromkeys(("inertials_verified", "motion_states_verified", "ratings_verified", "mount_verified"), False),
         "provenance": {"task_id": "motion-reference", "revision": "reference"}}
    return c


def run(tmp_path, c, name="run"):
    path = tmp_path/(name+".json")
    write_json(path, c)
    events = []
    r = analyze_case(path, tmp_path/name, progress=events.append, predict_capacity=False)
    return r, events


def test_api_failure_located_complete_states_and_schemas(tmp_path):
    c = case(tmp_path)
    r, events = run(tmp_path, c)
    assert r["status"] == "fail_under_stated_model"
    criterion = r["criterion_assessments"]["drive"]
    assert criterion["observed"] == pytest.approx(1*.2*9.81+.5*9.81+3*(.004+.004+.2**2+.5**2))
    assert criterion["governing_state"] == "accelerate"
    assert len(criterion["all_state_values"]) == 3
    assert r["evaluation_signal"]["feedback"][-1]["requires_reanalysis"]
    assert r["evaluation_signal"]["coverage"]["component_strength"] is False
    assert len([e for e in events if e["stage"] == "motion"]) == 3
    check_contract(r, "result")
    check_contract(r["evaluation_signal"], "signal")
    assert not list((tmp_path/"run").rglob("*.npz"))
    assert (tmp_path/"run/input.urdf").exists()


@pytest.mark.parametrize("defect", ["absent_criteria", "speed_range", "threshold"])
def test_insufficient_not_a_design_failure(tmp_path, defect):
    c = case(tmp_path)
    if defect == "absent_criteria":
        c["criteria"] = []
    elif defect == "speed_range":
        c["criteria"][0]["rating_max_abs_speed"] = 1.
    else:
        c["criteria"][0]["max_abs_effort"] = 7.761
    r, _ = run(tmp_path, c)
    assert r["status"] == "indeterminate"
    s = r["evaluation_signal"]
    assert not s["valid_for_comparison"]
    assert s["feasible_under_stated_model"] is None
    assert not any(f["kind"] == "design_hypothesis" for f in s["feedback"])


@pytest.mark.parametrize("field", ["states", "criterion_assessments", "robot"])
def test_mutated_results_cannot_pass_or_drive_cad(tmp_path, field):
    r, _ = run(tmp_path, case(tmp_path))
    r[field] = {}
    s = signal(r)
    assert not s["valid_for_comparison"]
    assert all(c["status"] == "indeterminate" for c in s["criterion_assessments"].values())
    assert not any(f["kind"] == "design_hypothesis" for f in s["feedback"])
    with pytest.raises(ValueError):
        mount_load_cases(r, np.eye(4), {"type": "plane", "axis": "x", "position_mm": 0.},
                         name="robot port", separate_mount_basis="A separate fixed bracket")


def test_cad_origin_change_comparable_but_mass_motion_or_limit_change_not(tmp_path):
    paths = []
    for index, length in enumerate([.4, .15]):
        root = tmp_path/str(index)
        root.mkdir()
        run(root, case(root, length))
        paths.append(root/"run/result.json")
    comparison = compare_results(paths)
    assert comparison["comparable"]
    assert json.loads(paths[0].read_text())["status"] == "fail_under_stated_model"
    assert json.loads(paths[1].read_text())["status"] == "pass_under_stated_model"
    for index, defect in enumerate(["mass", "acceleration", "limit"]):
        root = tmp_path/("changed-"+str(index))
        root.mkdir()
        c = case(root, .15)
        if defect == "mass":
            m = Path(c["model"]["path"])
            m.write_text(m.read_text().replace('mass value="1.0"', 'mass value="0.9"'), encoding="utf-8")
        elif defect == "acceleration":
            c["states"][1]["accelerations"]["drive"] = 1.
        else:
            c["criteria"][0]["max_abs_effort"] = 100.
        run(root, c)
        assert not compare_results([paths[0], root/"run/result.json"])["comparable"]


def test_mount_load_transfer_frame_units_and_state_pairing(tmp_path):
    c = case(tmp_path)
    c["criteria"] = []  # Complete numerical loads can be transferred without invented motor limits.
    r, _ = run(tmp_path, c)
    from simplecae.robot import transform
    matrix = transform([.3, -.2, .1], [.2, .7, -.5])
    transferred = mount_load_cases(r, matrix, {"type": "plane", "axis": "x", "position_mm": 0.},
                                   name="robot port", separate_mount_basis="Separate bracket not included in URDF mass")
    assert len(transferred["load_cases"]) == 3
    for lc, state in zip(transferred["load_cases"], r["states"]):
        load = lc["loads"][0]
        assert lc["name"] == state["id"]
        w = np.array(state["base"]["robot_on_base_world"])
        assert matrix[:3, :3]@load["total_force_n"] == pytest.approx(w[:3])
        assert matrix[:3, :3]@np.array(load["total_moment_n_mm"])/1000. == pytest.approx(w[3:])
        assert matrix[:3, :3]@np.array(load["application_point_mm"])/1000.+matrix[:3, 3] == pytest.approx(
            state["base"]["point_world_m"], abs=1e-12)
        assert load["scalable"] is False


def manifest(tmp_path, c):
    base = Path(__file__).resolve().parents[1]/"examples/tasks/bench-fixture.task.json"
    t = json.loads(base.read_text(encoding="utf-8"))
    t.update(task_id=c["provenance"]["task_id"], request="Check the declared robot drive motion states")
    check, physical = t["checks"][:2]
    check.update(id="drive", method="calculation", result_criteria=["drive"],
                 question="Does the drive meet the three explicit load states?", targets=["drive output"],
                 load_path="Payload and link inertia -> joints -> fixed base",
                 load_basis="Explicit q, qd and qdd; no universal dynamic factor",
                 support_basis="Stationary fixed base")
    physical.update(id="physical", question="Are real drive behavior, reach and structure verified?")
    t["checks"] = [check, physical]
    cp = tmp_path/"case.json"
    write_json(cp, c)
    t["cases"], t["sources"] = {"drive": str(cp)}, [str(cp)]
    p = tmp_path/"task.json"
    write_json(p, t)
    return p


@pytest.mark.parametrize("length,outcome,trigger", [
    (.4, "fail", "after_design_change"), (.15, "pass", "none_for_this_check")])
def test_real_task_and_viewer(tmp_path, length, outcome, trigger):
    start_task(manifest(tmp_path, case(tmp_path, length)), tmp_path/"task")
    status = run_task_check(tmp_path/"task", "drive", budget_seconds=40)
    row = status["checks"][0]
    assert row["outcome"] == outcome, row
    assert row["latest"]["analysis"]["reanalysis_trigger"] == trigger
    assert status["checks"][1]["outcome"] == "pending"
    assert not status["whole_product_pass_available"]
    view = snapshot(tmp_path/"task/viewer")
    r = view["runs"][-1]
    assert len(r["motion_display"]["states"]) == 3
    assert r["datasets"] == []
    assert len([e for e in r["events"] if e["stage"] == "motion"]) == 3
    model = tmp_path/"mechanism.urdf"
    model.write_text(model.read_text()+"\n", encoding="utf-8")
    changed = task_status(tmp_path/"task")
    assert changed["status"] == "insufficient_evidence"
    assert str(model.resolve()) in changed["changed_inputs"]
    with pytest.raises(ValueError, match="changed"):
        run_task_check(tmp_path/"task", "drive", budget_seconds=40)


@pytest.mark.parametrize("fault", ["missing_speed", "unknown_force_link", "bad_units", "unknown_criterion_joint", "duplicate_state"])
def test_bad_inputs_preflight_before_workspace(tmp_path, fault):
    c = case(tmp_path)
    if fault == "missing_speed":
        c["states"][0]["velocities"] = {}
    elif fault == "unknown_force_link":
        c["states"][0]["loads"] = [{"link": "missing", "force_n": [1, 0, 0], "moment_n_m": [0, 0, 0],
                                   "position_m": [0, 0, 0], "frame": "link", "position_frame": "link"}]
    elif fault == "bad_units":
        c["model"]["units"] = "mm"
    elif fault == "unknown_criterion_joint":
        c["criteria"][0]["joint"] = "attachment"
    else:
        c["states"][1]["id"] = c["states"][0]["id"]
    p = manifest(tmp_path, c)
    with pytest.raises(ValueError):
        start_task(p, tmp_path/"task")
    assert not (tmp_path/"task").exists()


def test_force_and_moment_envelopes_keep_different_controlling_states(tmp_path):
    c = case(tmp_path)
    c["states"][1]["velocities"]["drive"] = 10.
    c["criteria"] = [
        {"id": "mount_force", "type": "base_force", "target": "mount force", "basis": "Reference", "limit": 1000.},
        {"id": "mount_moment", "type": "base_moment", "target": "mount moment", "basis": "Reference", "limit": 100.}]
    c["states"][2]["accelerations"]["drive"] = -100.
    r, _ = run(tmp_path, c)
    assert r["criterion_assessments"]["mount_force"]["governing_state"] == "accelerate"
    assert r["criterion_assessments"]["mount_moment"]["governing_state"] == "brake"
    assert len(r["states"]) == 3
