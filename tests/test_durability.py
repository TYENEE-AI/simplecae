"""Independent material-curve references and fail-closed Agent integration."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from simplecae.api import analyze_case, check_case
from simplecae.case import sha256, write_json
from simplecae.durability import calculate, validate, signal, seal
from simplecae.schemas import check_contract
from simplecae.signals import compare_results
from simplecae.task import start_task, run_task_check, task_status
from simplecae.workbench import snapshot


def source(root, name, value):
    p = root/(name+".json")
    write_json(p, value)
    return {"path": str(p), "sha256": sha256(p), "basis": "Mathematical reference, not physical material qualification"}


def example(root, mode="fatigue"):
    material = {"id": "reference", "manufacture": "mathematical", "orientation": "x"}
    common = {"material": material, "temperature_c": 20., "kind": "mathematical_reference",
              "stress_definition": "signed_uniaxial_local", "applicability_basis": "Explicit analytical reference domain"}
    point = {"id": "root", "target": "section root", "position_mm": [0, 0, 0], "frame": "part", "direction": [1, 0, 0]}
    if mode == "fatigue":
        curve = common | {"curves": [{"stress_ratio": -1., "amplitude_mpa": [100., 50., 25.],
                                      "cycles_to_failure": [10000., 100000., 1000000.]}]}
        service = [{"id": "normal", "cycles": 10000., "basis": "Requested cycle count"},
                   {"id": "peak", "cycles": 2000., "basis": "Requested peak count"}]
        point["blocks"] = [{"service_id": "normal", "minimum_mpa": -50., "maximum_mpa": 50.},
                           {"service_id": "peak", "minimum_mpa": -100., "maximum_mpa": 100.}]
        criterion = {"id": "durability", "point": "root", "basis": "Reference design margin", "max_damage": .5}
        extra = {}
    else:
        curve = common | {"strain_measure": "creep_only_magnitude", "stress_levels_mpa": [10., 20.],
                          "times_s": [0., 100., 1000.], "strain": [[0., .001, .01], [0., .004, .04]]}
        service = {"duration_s": 500., "history": "constant_from_unloaded", "basis": "Constant uniaxial load, not a variable history"}
        point["stress_mpa"] = 10.
        criterion = {"id": "durability", "point": "root", "basis": "Reference strain limit", "max_strain": .01}
        extra = {"strain_measure": "creep_only_magnitude"}
    curve["source"] = source(root, "material-data", curve)
    return {"schema_version": mode+"-data-1.0", "material": material, "temperature_c": 20.,
            "stress_definition": "signed_uniaxial_local", "material_curve": curve,
            "geometry_source": source(root, "geometry", {"basis": "Symbolic section geometry reference"}),
            "stress_source": source(root, "stress", point), "service_source": source(root, "service", service),
            "service": service, "points": [point], "criteria": [criterion], **extra,
            "assumptions": ["Declared local uniaxial stresses and supplied material curves"],
            "not_assessed": ["Whole-component behavior and physical material validity"],
            "conditions": dict.fromkeys(("material_data_verified", "stress_history_verified", "service_verified"), False),
            "provenance": {"task_id": mode+"-reference"}}


def run(root, case, name="run"):
    p = root/(name+".json")
    write_json(p, case)
    return analyze_case(p, root/name, predict_capacity=False)


def test_fatigue_amplitude_mean_and_miner_sum(tmp_path):
    r = calculate(example(tmp_path))
    p = r["points"]["root"]
    assert p["damage"] == pytest.approx(.1+.2)
    assert p["blocks"][0]["amplitude_mpa"] == 50.
    assert p["blocks"][0]["mean_mpa"] == 0.
    assert p["blocks"][0]["stress_ratio"] == -1.
    assert [b["cycles_to_failure"] for b in p["blocks"]] == pytest.approx([1e5, 1e4])
    assert r["status"] == "pass_under_stated_model"
    assert not r["whole_product_pass_available"]


def test_sn_log_log_interpolation_and_exact_endpoints(tmp_path):
    c = example(tmp_path)
    for amplitude, expected in [(100., 1e4), (np.sqrt(5000.), np.sqrt(1e9)), (50., 1e5), (25., 1e6)]:
        for b in c["points"][0]["blocks"]:
            b.update(minimum_mpa=-amplitude, maximum_mpa=amplitude)
        r = calculate(c)
        assert r["points"]["root"]["blocks"][0]["cycles_to_failure"] == pytest.approx(expected)
    # Same physical cycle represented by its extrema, not range mistaken for amplitude.
    assert calculate(c)["points"]["root"]["blocks"][0]["amplitude_mpa"] == 25.


def test_mean_stress_requires_matching_r_data(tmp_path):
    c = example(tmp_path)
    for b in c["points"][0]["blocks"]:
        b.update(minimum_mpa=0., maximum_mpa=100.)
    r = calculate(c)
    assert r["status"] == "indeterminate"
    assert "stress_ratio_not_covered" in r["points"]["root"]["gaps"]
    curve = copy.deepcopy(c["material_curve"]["curves"][0])
    curve.update(stress_ratio=0., cycles_to_failure=[1000., 10000., 100000.])
    c["material_curve"]["curves"].append(curve)
    r = calculate(c)
    assert r["points"]["root"]["damage"] == pytest.approx(1.2)
    assert r["status"] == "fail_under_stated_model"


@pytest.mark.parametrize("fault", ["below", "above", "constant", "zero_max", "missing_curve", "temperature", "orientation"])
def test_fatigue_gaps_never_become_infinite_life(tmp_path, fault):
    c = example(tmp_path)
    b = c["points"][0]["blocks"][0]
    if fault in ("below", "above"):
        v = 24.9 if fault == "below" else 100.1
        b.update(minimum_mpa=-v, maximum_mpa=v)
    elif fault == "constant":
        b.update(minimum_mpa=5., maximum_mpa=5.)
    elif fault == "zero_max":
        b.update(minimum_mpa=-100., maximum_mpa=0.)
    elif fault == "missing_curve":
        c["material_curve"] = None
    elif fault == "temperature":
        c["temperature_c"] = 25.
    else:
        c["material"]["orientation"] = "other"  # deepcopy to avoid shared fixture identity below
        c["material_curve"]["material"] = {"id": "reference", "manufacture": "mathematical", "orientation": "x"}
    r = calculate(c)
    assert r["status"] == "indeterminate"
    assert r["points"]["root"]["damage"] is None
    assert r["points"]["root"]["blocks"][0]["cycles_to_failure"] is None


def test_unsupported_block_cannot_be_dropped_to_make_pass(tmp_path):
    c = example(tmp_path)
    c["points"][0]["blocks"][1].update(minimum_mpa=-200., maximum_mpa=200.)
    r = calculate(c)
    assert r["points"]["root"]["known_damage_lower_bound"] == pytest.approx(.1)
    assert r["points"]["root"]["damage"] is None
    assert r["criterion_assessments"]["durability"]["status"] == "indeterminate"
    c["points"][0]["blocks"].pop()
    with pytest.raises(ValueError, match="every service"):
        validate(c)


def test_creep_constant_stress_reference_and_bilinear_table(tmp_path):
    c = example(tmp_path, "creep")
    assert calculate(c)["points"]["root"]["strain"] == pytest.approx(.005)
    c["points"][0]["stress_mpa"] = 20.
    r = calculate(c)
    assert r["points"]["root"]["strain"] == pytest.approx(.02)  # A sigma^2 t at a measured stress row
    assert r["status"] == "fail_under_stated_model"
    c["points"][0]["stress_mpa"] = 15.
    r = calculate(c)
    assert r["points"]["root"]["strain"] == pytest.approx(.0125)  # stated table interpolation, not nonlinear stress-law inference
    assert r["points"]["root"]["history"] == [[0., 0.], [100., .0025], [500., .0125]]


def test_creep_compression_and_total_strain_semantics(tmp_path):
    c = example(tmp_path, "creep")
    c["material_curve"]["stress_levels_mpa"] = [-10., -20.]
    c["points"][0]["stress_mpa"] = -10.
    assert calculate(c)["points"]["root"]["strain"] == pytest.approx(.005)
    c["strain_measure"] = "total_axial_strain_magnitude"
    assert calculate(c)["status"] == "indeterminate"
    c["material_curve"]["strain_measure"] = c["strain_measure"]
    c["material_curve"]["strain"] = [[.002, .003, .012], [.004, .008, .044]]
    assert calculate(c)["points"]["root"]["strain"] == pytest.approx(.007)


@pytest.mark.parametrize("fault", ["stress_low", "stress_high", "sign", "duration", "temperature", "missing_curve"])
def test_creep_no_extrapolation(tmp_path, fault):
    c = example(tmp_path, "creep")
    if fault.startswith("stress"):
        c["points"][0]["stress_mpa"] = 9.9 if fault == "stress_low" else 20.1
    elif fault == "sign":
        c["points"][0]["stress_mpa"] = -10.
    elif fault == "duration":
        c["service"]["duration_s"] = 1000.01
    elif fault == "temperature":
        c["temperature_c"] = 60.
    else:
        c["material_curve"] = None
    r = calculate(c)
    assert r["points"]["root"]["strain"] is None
    assert r["points"]["root"]["history"] == []
    assert r["status"] == "indeterminate"


@pytest.mark.parametrize("mode", ["fatigue", "creep"])
def test_api_schema_source_mutation_and_reconstructed_signal(tmp_path, mode):
    c = example(tmp_path, mode)
    r = run(tmp_path, c)
    assert r["evaluation_signal"]["valid_for_comparison"]
    check_contract(r, "result")
    check_contract(r["evaluation_signal"], "signal")
    altered = copy.deepcopy(r)
    key = "damage" if mode == "fatigue" else "strain"
    altered["points"]["root"][key] = 0.
    altered["evidence_sha256"] = seal(altered)
    assert not signal(altered)["valid_for_comparison"]  # full reconstruction, not just a digest
    assert not any(f["kind"] == "design_hypothesis" for f in signal(altered)["feedback"])
    p = Path(c["stress_source"]["path"])
    p.write_text("changed source", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        check_case(tmp_path/"run.json")


@pytest.mark.parametrize("mode", ["fatigue", "creep"])
def test_no_criteria_or_near_threshold_cannot_pass(tmp_path, mode):
    c = example(tmp_path, mode)
    c["criteria"] = []
    assert calculate(c)["status"] == "indeterminate"
    c = example(tmp_path, mode)
    if mode == "fatigue":
        c["criteria"][0]["max_damage"] = .3
    else:
        c["criteria"][0]["max_strain"] = .005
    assert calculate(c)["status"] == "indeterminate"


@pytest.mark.parametrize("fault", ["nonmonotone_sn", "range_mismatch", "nan", "nonunit_axis", "nonmonotone_creep", "bad_zero", "mixed_signs"])
def test_invalid_data_rejected(tmp_path, fault):
    c = example(tmp_path, "creep" if fault in ("nonmonotone_creep", "bad_zero", "mixed_signs") else "fatigue")
    if fault == "nonmonotone_sn":
        c["material_curve"]["curves"][0]["cycles_to_failure"] = [1e5, 1e4, 1e6]
    elif fault == "range_mismatch":
        c["material_curve"]["curves"][0]["amplitude_mpa"].pop()
    elif fault == "nan":
        c["points"][0]["blocks"][0]["maximum_mpa"] = float("nan")
    elif fault == "nonunit_axis":
        c["points"][0]["direction"] = [2, 0, 0]
    elif fault == "nonmonotone_creep":
        c["material_curve"]["strain"][1][1] = .0005
    elif fault == "bad_zero":
        c["material_curve"]["strain"][0][0] = .0001
    else:
        c["material_curve"]["stress_levels_mpa"] = [-10., 20.]
    with pytest.raises(ValueError):
        validate(c)


def manifest(root, c):
    t = json.loads((Path(__file__).resolve().parents[1]/"examples/tasks/bench-fixture.task.json").read_text(encoding="utf-8"))
    t.update(task_id=c["provenance"]["task_id"], request="Check declared material-curve durability",
             scenarios=[{"id": "service", "use": "Declared repeated or sustained service",
                         "success": "Named-location damage/strain below the declared limit; physical evidence separate"}])
    selected, physical = t["checks"][:2]
    selected.update(id="durability", scenario="service", method="calculation", result_criteria=["durability"],
                    question="Does the named location meet the declared duty and material-curve criterion?",
                    targets=["section root"], load_path="Declared uniaxial local stress",
                    load_basis="Hashed stress and service evidence", support_basis="External stress-model basis")
    physical.update(id="physical", scenario="service", question="Are whole-component and physical durability verified?")
    cp = root/"case.json"
    write_json(cp, c)
    t.update(cases={"durability": str(cp)}, sources=[str(cp)])
    p = root/"task.json"
    write_json(p, t)
    return p


@pytest.mark.parametrize("mode", ["fatigue", "creep"])
@pytest.mark.parametrize("outcome,trigger", [("pass", "none_for_this_check"), ("fail", "after_design_change"),
                                            ("insufficient_evidence", "after_input_or_analysis_repair_if_needed")])
def test_agent_worker_completion_and_viewer(tmp_path, mode, outcome, trigger):
    c = example(tmp_path, mode)
    if outcome == "fail":
        if mode == "fatigue":
            c["points"][0]["blocks"][0].update(minimum_mpa=-100., maximum_mpa=100.)
        else:
            c["points"][0]["stress_mpa"] = 20.
    if outcome == "insufficient_evidence":
        c["material_curve"] = None
    start_task(manifest(tmp_path, c), tmp_path/"task")
    status = run_task_check(tmp_path/"task", "durability", budget_seconds=40)
    row = status["checks"][0]
    assert row["outcome"] == outcome, row
    assert row["latest"]["analysis"]["reanalysis_trigger"] == trigger
    assert status["checks"][1]["outcome"] == "pending"
    assert not status["whole_product_pass_available"]
    view = snapshot(tmp_path/"task/viewer")
    assert view["runs"][-1]["durability_display"]["mode"] == mode+"_data"
    assert view["runs"][-1]["datasets"] == []
    source_path = Path(c["service_source"]["path"])
    source_path.write_text("changed service", encoding="utf-8")
    assert task_status(tmp_path/"task")["status"] == "insufficient_evidence"


@pytest.mark.parametrize("mode", ["fatigue", "creep"])
def test_compare_stress_revision_not_relaxed_duty_or_material(tmp_path, mode):
    paths = []
    for index in range(3):
        root = tmp_path/str(index)
        root.mkdir()
        c = example(root, mode)
        if index == 0:
            if mode == "fatigue":
                c["points"][0]["blocks"][0].update(minimum_mpa=-100., maximum_mpa=100.)
            else:
                c["points"][0]["stress_mpa"] = 20.
        if index == 2:
            if mode == "fatigue":
                c["service"][0]["cycles"] /= 2
            else:
                c["service"]["duration_s"] /= 2
        c["stress_source"] = source(root, "stress", c["points"])
        run(root, c)
        paths.append(root/"run/result.json")
    assert compare_results(paths[:2])["comparable"]
    assert not compare_results([paths[0], paths[2]])["comparable"]


@pytest.mark.parametrize("mode", ["fatigue", "creep"])
def test_unselected_unsupported_location_prevents_overall_pass(tmp_path, mode):
    c = example(tmp_path, mode)
    other = copy.deepcopy(c["points"][0])
    other.update(id="other", target="second required location", position_mm=[10., 0., 0.])
    if mode == "fatigue":
        other["blocks"][0].update(minimum_mpa=-200., maximum_mpa=200.)
    else:
        other["stress_mpa"] = 30.
    c["points"].append(other)
    r = run(tmp_path, c)
    assert r["criterion_assessments"]["durability"]["status"] == "pass_under_stated_model"
    assert r["points"]["other"]["gaps"]
    assert r["status"] == "indeterminate"
    assert not r["evaluation_signal"]["valid_for_comparison"]
    assert r["evaluation_signal"]["feasible_under_stated_model"] is None


@pytest.mark.parametrize("mode", ["fatigue", "creep"])
@pytest.mark.parametrize("side", ["below", "above"])
def test_one_ulp_outside_material_domain_is_not_clamped(tmp_path, mode, side):
    c = example(tmp_path, mode)
    lo, hi = (25., 100.) if mode == "fatigue" else (10., 20.)
    v = float(np.nextafter(lo, -np.inf) if side == "below" else np.nextafter(hi, np.inf))
    if mode == "fatigue":
        c["points"][0]["blocks"][0].update(minimum_mpa=-v, maximum_mpa=v)
    else:
        c["points"][0]["stress_mpa"] = v
    assert calculate(c)["status"] == "indeterminate"


def test_creep_single_measured_stress_row_and_last_time_endpoint(tmp_path):
    c = example(tmp_path, "creep")
    c["material_curve"]["stress_levels_mpa"] = [10.]
    c["material_curve"]["strain"] = [[0., .001, .01]]
    c["service"]["duration_s"] = 1000.
    c["criteria"][0]["max_strain"] = .02
    r = calculate(c)
    assert r["status"] == "pass_under_stated_model"
    assert r["points"]["root"]["history"] == [[0., 0.], [100., .001], [1000., .01]]
