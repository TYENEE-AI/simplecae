import copy
import json
from pathlib import Path
import numpy as np
import pytest

from test_thermal_solid_solver import solid
from simplecae.thermal_fields import simplex_extrema
from simplecae.thermal_solid import analyze, read_case, signal
from simplecae.case import write_json
from simplecae.api import analyze_case, check_case
from simplecae.schemas import check_contract


def thermal_case(solid):
    c = copy.deepcopy(solid[0])
    c["model"]["units"] = "mm"
    c["mesh"]["sizes_mm"] = [5., 3.5, 2.5]
    c["material"].update(name="Analytical material", basis="Mathematical reference, not product evidence",
                         temperature_range_c=[0., 200.])
    c["boundaries"][1] = dict(name="input", type="heat_power",
                              selector=c["boundaries"][1]["selector"], total_heat_w=.1)
    for b in c["boundaries"]:
        b.update(target=b["name"], basis="Prescribed analytical reference")
    c.update(criteria=[{"id": "body_temperature", "target": "body", "region": {"type": "body"},
                        "max_temperature_c": 40.}],
             assumptions=["Homogeneous constant isotropic conductivity; all other surfaces insulated"],
             not_assessed=["Physical manufacturing and boundary verification"],
             conditions={"properties_verified": False, "boundaries_verified": False},
             provenance={"task_id": "solid-thermal-reference"})
    return c


def test_between_node_extrema_interior_face_edge_and_constant():
    corners = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    edges = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))
    nodes = np.vstack((corners, [(corners[i]+corners[j])/2 for i, j in edges]))
    target = np.array([.2, .3, .1])
    value = 50-np.sum((nodes-target)**2, axis=1)
    low, high, _, at = simplex_extrema(value[None, :], nodes[None, :, :])
    assert high[0] == pytest.approx(50)
    np.testing.assert_allclose(at[0], target, atol=1e-10)
    assert high[0] > max(value)
    assert low[0] == pytest.approx(min(value))
    for center in (np.array([.3, .2, 0]), np.array([.3, 0, 0])):
        value = 10-np.sum((nodes-center)**2, axis=1)
        _, high, _, at = simplex_extrema(value[None, :], nodes[None, :, :])
        assert high[0] == pytest.approx(10)
        np.testing.assert_allclose(at[0], center, atol=1e-10)
    low, high, _, _ = simplex_extrema(np.full((1, 10), 22.), nodes[None, :, :])
    assert low[0] == high[0] == 22.


def test_complete_steady_analysis_and_lossless_compaction(solid):
    c = thermal_case(solid)
    path = solid[2]/"case.json"
    write_json(path, c)
    assert check_case(path)["schema_version"] == "thermal-solid-1.0"
    r = analyze_case(path, solid[2]/"analysis", predict_capacity=False)
    assert r["status"] == "pass_under_stated_model", r.get("error") or r.get("verification")
    assert len(r["levels"]) == 3
    assert all(x["energy_passed"] for x in r["levels"])
    assert r["criterion_assessments"]["body_temperature"]["max_temperature_c"] == pytest.approx(30, abs=1e-4)
    assert r["whole_product_pass_available"] is False
    assert signal(r)["valid_for_comparison"]
    assert signal(r)["coverage"]["acceptance_quantity"] == "requested_temperature_extrema"
    assert signal(r)["coverage"]["pointwise_heat_flux_qualified"] is False
    assert not any(f["kind"] == "design_hypothesis" for f in signal(r)["feedback"])
    check_contract(r, "result")
    check_contract(signal(r), "signal")
    assert list((solid[2]/"analysis").rglob("thermal.dat.gz"))
    from simplecae.workbench import create_session, add_result, snapshot
    viewer = solid[2]/"viewer"
    create_session(viewer)
    add_result(viewer, solid[2]/"analysis"/"result.json", label="thermal reference")
    view = snapshot(viewer)
    data = view["runs"][0]["datasets"][0]
    assert view["runs"][0]["coverage"]["pointwise_heat_flux_qualified"] is False
    assert data["physics"] == "thermal"
    assert data["hotspot"]["max_temperature_c"] == pytest.approx(30, abs=1e-4)
    assert len(data["temperature"]) == len(data["triangles"])
    altered = copy.deepcopy(r)
    altered["criterion_assessments"]["body_temperature"]["max_temperature_c"] = 21.
    assert not signal(altered)["valid_for_comparison"]
    def assert_no_favorable_observation(result):
        s = signal(result)
        assert not s["valid_for_comparison"]
        assert s["feasible_under_stated_model"] is None
        assert all(c["status"] == "indeterminate" for c in s["criterion_assessments"].values())
        assert all(c["status"] == "indeterminate" for c in s["metrics"]["region_temperatures"].values())
        assert all(f["status"] == "indeterminate" for f in s["feedback"] if f["kind"] == "thermal_observation")
        assert not any(f["kind"] == "design_hypothesis" for f in s["feedback"])
    assert_no_favorable_observation(altered)
    field = solid[2]/"analysis"/"mesh-3"/"thermal-fields.npz"
    with field.open("ab") as stream:
        stream.write(b"changed")
    assert not signal(r)["valid_for_comparison"]
    assert_no_favorable_observation(r)
    assert r["criterion_assessments"]["body_temperature"]["status"] == "pass_under_stated_model"


@pytest.mark.parametrize("bounds,expected", [
    ({"min_temperature_c": 25.}, {"min"}),
    ({"min_temperature_c": 25., "max_temperature_c": 28.}, {"min", "max"}),
    ({"min_temperature_c": 21.05}, set()),
])
def test_feedback_locates_each_violated_bound_and_withholds_near_limit(solid, bounds, expected):
    from simplecae.thermal_solid import design_feedback
    c = thermal_case(solid)
    # Cold end is free to respond to design changes, not held below its limit.
    c["boundaries"][0].pop("temperature_c")
    c["boundaries"][0].update(type="convection", coefficient_w_m2k=1000., ambient_temperature_c=20.)
    c["criteria"][0].pop("max_temperature_c")
    c["criteria"][0].update(bounds)
    path = solid[2]/"bounds.case.json"
    write_json(path, c)
    r = analyze_case(path, solid[2]/"bounds", predict_capacity=False)
    assert r["status"] == ("fail_under_stated_model" if expected else "indeterminate")
    s = signal(r)
    hints = [f for f in s["feedback"] if f["kind"] == "design_hypothesis"]
    assert {f["bound"] for f in hints} == expected
    for hint in hints:
        assert hint["criterion_id"] == "body_temperature"
        assert hint["location_mm"][0] == pytest.approx(0. if hint["bound"] == "min" else 20., abs=1e-6)
        assert hint["requires_reanalysis"] is True
    if expected:
        criterion = s["criterion_assessments"]["body_temperature"]
        assert criterion["governing_bound"] == "min"
        assert criterion["governing_location_mm"][0] == pytest.approx(0., abs=1e-6)
    else:
        assert s["feasible_under_stated_model"] is None
        assert not s["valid_for_comparison"]
    fb = design_feedback(r, {"not_assessed": []}, "completed")
    assert fb["coverage"]["pointwise_heat_flux_qualified"] is False
    assert fb["whole_product_pass_available"] is False
    # A changed field invalidates even an apparently actionable cold/hot failure.
    with (solid[2]/"bounds"/"mesh-3"/"thermal-fields.npz").open("ab") as stream:
        stream.write(b"corrupted")
    assert not any(f["kind"] == "design_hypothesis" for f in signal(r)["feedback"])


@pytest.mark.parametrize("region,conflict", [
    ({"type": "body"}, True),
    ({"type": "surface", "selector": {"type": "plane", "axis": "y", "position_mm": 0.}}, True),
    ({"type": "surface", "selector": {"type": "plane", "axis": "x", "position_mm": 20.}}, False),
])
def test_prescribed_boundary_conflict_includes_shared_edges_but_not_remote_face(solid, region, conflict):
    from simplecae.thermal_solid import design_feedback
    c = thermal_case(solid)
    c["criteria"][0].update(min_temperature_c=25., region=region)
    path = solid[2]/"conflict.case.json"
    write_json(path, c)
    r = analyze_case(path, solid[2]/"conflict", predict_capacity=False)
    fb = design_feedback(r, {"not_assessed": []}, "completed")
    assert r["status"] == ("fail_under_stated_model" if conflict else "pass_under_stated_model")
    assert fb["cad_iteration_blocked"] is conflict
    assert bool(fb["criterion_assessments"]["body_temperature"]["prescribed_boundary_conflicts"]) is conflict
    assert not any(f["kind"] == "design_hypothesis" for f in fb["findings"])


def test_real_agent_preserves_failure_but_stops_boundary_conflict_cad_loop(solid):
    from test_thermal_network import manifest
    from simplecae.task import start_task, run_task_check
    from simplecae.workbench import snapshot
    task_path = manifest(solid[2])
    task = json.loads(task_path.read_text(encoding="utf-8"))
    c = thermal_case(solid)
    c["criteria"][0]["min_temperature_c"] = 25.
    c["provenance"]["task_id"] = task["task_id"]
    write_json(solid[2]/"case.json", c)
    task["checks"][0].update(method="fem", result_criteria=["body_temperature"])
    write_json(task_path, task)
    start_task(task_path, solid[2]/"task")
    status = run_task_check(solid[2]/"task", "heat", budget_seconds=60)
    assert status["checks"][0]["outcome"] == "fail"
    assert status["checks"][1]["outcome"] == "pending"
    review_path = status["checks"][0]["latest"]["review"]
    review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    u = review["usage_feedback"]
    assert u["status"] == "fail_under_stated_model"
    assert u["action"] == "resolve_analysis_or_inputs"
    assert u["cad_iteration"]["requires_reanalysis"] is False
    assert u["cad_iteration"]["reanalysis_trigger"] == "after_input_or_analysis_repair_if_needed"
    assert not status["whole_product_pass_available"]
    view = snapshot(solid[2]/"task"/"viewer")["runs"][-1]
    assert view["state"] == "completed"
    assert view["coverage"]["pointwise_heat_flux_qualified"] is False


def test_local_flux_requirement_is_rejected_not_silently_temperature_checked(solid):
    c = thermal_case(solid)
    c["criteria"][0]["max_heat_flux_w_m2"] = 2000.
    path = solid[2]/"flux-requirement.json"
    write_json(path, c)
    with pytest.raises(ValueError):
        read_case(path)


@pytest.mark.parametrize("change", ["unknown", "no_capacity", "jump", "bad_mesh", "nonfinite", "wrong_units"])
def test_invalid_inputs_rejected_before_output(solid, change):
    c = thermal_case(solid)
    if change == "unknown":
        c["convection_guessed"] = True
    elif change == "no_capacity":
        c.update(mode="transient", time_steps=4, duration_s=1., initial_temperature_c=20.)
    elif change == "jump":
        c.update(mode="transient", time_steps=4, duration_s=1., initial_temperature_c=30.)
        c["material"].update(density_kg_m3=1000., specific_heat_j_kgk=1000.)
    elif change == "bad_mesh":
        c["mesh"]["sizes_mm"] = [5., 5., 5.]
    elif change == "nonfinite":
        c["boundaries"][1]["total_heat_w"] = float("nan")
    else:
        c["model"]["units"] = "m"
    path = solid[2]/"case.json"
    path.write_text(json.dumps(c), encoding="utf-8")
    with pytest.raises(ValueError):
        read_case(path)


def test_transient_three_spatial_and_three_time_levels(solid):
    c = thermal_case(solid)
    c.update(mode="transient", initial_temperature_c=20., duration_s=10.,
             time_steps=4, boundaries=[], volumetric_heat_w_m3=1e6)
    c["material"].update(density_kg_m3=1000., specific_heat_j_kgk=1000.)
    path = solid[2]/"case.json"
    write_json(path, c)
    r = analyze(path, solid[2]/"transient")
    assert r["status"] == "pass_under_stated_model", r.get("error") or r.get("verification")
    assert len(r["levels"]) == 5
    assert max(r["verification"]["time_field_differences_c"]) < 1e-4
    assert r["criterion_assessments"]["body_temperature"]["max_temperature_c"] == pytest.approx(30., abs=1e-4)
    assert signal(r)["valid_for_comparison"]


def test_requested_time_grid_is_not_replaced_by_rounded_dat_stamps(solid):
    c = thermal_case(solid)
    c.update(mode="transient", initial_temperature_c=20., duration_s=1.,
             time_steps=6, boundaries=[], volumetric_heat_w_m3=1e5)
    c["material"].update(density_kg_m3=1000., specific_heat_j_kgk=1000.)
    path = solid[2]/"fractional.case.json"
    write_json(path, c)
    r = analyze(path, solid[2]/"fractional")
    assert "error" not in r
    e = r["levels"][0]["energy"]
    assert e[0]["time_s"] == 1/24
    assert e[0]["printed_time_s"] != e[0]["time_s"]
    assert e[-1]["time_s"] == 1.
    assert r["levels"][0]["time_s"][1:] == [x["time_s"] for x in e]


@pytest.mark.parametrize("limit,outcome", [(28., "fail"), (40., "pass")])
def test_real_agent_task_solid_temperature_and_pending_physical_check(solid, limit, outcome):
    from test_thermal_network import manifest
    from simplecae.task import start_task, run_task_check
    from simplecae.workbench import snapshot
    task_path = manifest(solid[2])
    task = json.loads(task_path.read_text(encoding="utf-8"))
    c = thermal_case(solid)
    c["criteria"][0]["max_temperature_c"] = limit
    c["provenance"]["task_id"] = task["task_id"]
    write_json(solid[2]/"case.json", c)
    task["checks"][0].update(method="fem", result_criteria=["body_temperature"])
    write_json(task_path, task)
    workspace = solid[2]/"task"
    start_task(task_path, workspace)
    status = run_task_check(workspace, "heat", budget_seconds=60)
    assert status["checks"][0]["outcome"] == outcome, status["checks"][0]
    assert status["checks"][1]["outcome"] == "pending"
    assert not status["whole_product_pass_available"]
    view = snapshot(workspace/"viewer")
    assert view["runs"][-1]["analysis"] == "thermal_solid"
    assert view["runs"][-1]["datasets"][0]["physics"] == "thermal"


def test_interior_heat_peak_controls_over_a_passing_surface(solid):
    c = thermal_case(solid)
    c["boundaries"][1] = dict(c["boundaries"][0], name="right",
                              selector={"type": "plane", "axis": "x", "position_mm": 20.})
    c["volumetric_heat_w_m3"] = 1e6
    c["criteria"][0]["max_temperature_c"] = 44.
    c["criteria"].append({"id": "cold_face", "target": "cold face",
                          "region": {"type": "surface", "selector": c["boundaries"][0]["selector"]},
                          "max_temperature_c": 21.})
    path = solid[2]/"case.json"
    write_json(path, c)
    r = analyze(path, solid[2]/"peak")
    assert r["status"] == "fail_under_stated_model", r.get("error") or r.get("verification")
    peak = r["criterion_assessments"]["body_temperature"]
    assert peak["max_temperature_c"] == pytest.approx(45., abs=1e-4)
    assert peak["max_location_mm"][0] == pytest.approx(10., abs=1e-4)
    assert r["criterion_assessments"]["cold_face"]["status"] == "pass_under_stated_model"
    assert not signal(r)["feasible_under_stated_model"]
    assert not r["whole_product_pass_available"]


def test_high_conductivity_opposing_reservoirs_do_not_have_zero_exchange_scale(solid):
    c = thermal_case(solid)
    c["material"]["conductivity_w_mk"] = 200.
    c["boundaries"][1] = dict(c["boundaries"][0], name="hot", temperature_c=100.,
                              selector={"type": "plane", "axis": "x", "position_mm": 20.})
    c["criteria"][0]["max_temperature_c"] = 110.
    path = solid[2]/"metal.case.json"
    write_json(path, c)
    r = analyze(path, solid[2]/"metal")
    assert r["status"] == "pass_under_stated_model", r.get("error") or r.get("verification")
    assert all(level["energy"][0]["reservoir_exchange_scale_w"] >= 160.-1e-4 for level in r["levels"])
    assert r["criterion_assessments"]["body_temperature"]["max_temperature_c"] == pytest.approx(100., abs=1e-4)


def test_unresolved_time_step_never_gets_favorable_signal(solid):
    c = thermal_case(solid)
    c.update(mode="transient", initial_temperature_c=20., duration_s=10.,
             time_steps=4, volumetric_heat_w_m3=1e6)
    c["boundaries"][1] = dict(c["boundaries"][0], name="right",
                              selector={"type": "plane", "axis": "x", "position_mm": 20.})
    c["material"].update(density_kg_m3=1000., specific_heat_j_kgk=1000.)
    path = solid[2]/"case.json"
    write_json(path, c)
    r = analyze(path, solid[2]/"unresolved")
    assert r["status"] == "indeterminate", r.get("error") or r.get("verification")
    assert not r["verification"]["time_refinement_passed"]
    assert signal(r)["feasible_under_stated_model"] is None


def test_asymmetric_heating_reflection_and_energy(solid):
    temperatures = []
    for y in (0., 10.):
        c = thermal_case(solid)
        c["boundaries"][1]["selector"] = {"type": "plane", "axis": "y", "position_mm": y}
        path = solid[2]/f"case-{y}.json"
        write_json(path, c)
        r = analyze(path, solid[2]/f"asymmetric-{y}")
        assert "error" not in r, r.get("error")
        assert r["verification"]["energy_balance_passed"]
        peak = r["criterion_assessments"]["body_temperature"]
        temperatures.append(peak["max_temperature_c"])
        assert peak["max_location_mm"][0] > 18.
        assert abs(peak["max_location_mm"][1]-y) < 1.
    assert abs(temperatures[0]-temperatures[1]) < .05
