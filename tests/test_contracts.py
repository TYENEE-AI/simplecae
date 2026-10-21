from __future__ import annotations
import copy
from types import SimpleNamespace
import numpy as np
import pytest

from simplecae.assessment import assess
from simplecae.benchmarks import bar_case
from simplecae.case import validate_case
from simplecae.geometry import edge_permutation, integrate_tri6, select_faces
from simplecae.solver import execute, mises, parse_dat


@pytest.fixture
def case():
    return bar_case("bar", [0., 0., -100.], [5., 4., 3.])


def levels(stresses=(10.,10.1,10.2), displacements=(.01,.0101,.0102)):
    return [{"results": {"max_von_mises_mpa": s, "max_displacement_mm": u,
                         "minimum_bbox_extent_mm": 10., "max_strain_norm": .00005,
                         "force_balance_relative_error": 1e-8, "moment_balance_relative_error": 1e-8}}
            for s, u in zip(stresses, displacements)]


@pytest.mark.parametrize("field,value", [("youngs_modulus_mpa",0), ("youngs_modulus_mpa",float("nan")),
                                         ("youngs_modulus_mpa",True), ("poisson_ratio",.5), ("yield_strength_mpa",-1)])
def test_invalid_material_rejected(case, field, value):
    case["material"][field] = value
    with pytest.raises(ValueError):
        validate_case(case)


def test_unknown_input_not_silently_ignored(case):
    case["criteria"]["allow_displacment"] = 1
    with pytest.raises(ValueError, match="unknown"):
        validate_case(case)


def test_boolean_condition_is_explicit(case):
    case["conditions"]["material_verified"] = "true"
    with pytest.raises(ValueError):
        validate_case(case)


def test_insufficient_refinement_rejected(case):
    case["mesh"]["sizes_mm"] = [3.,2.99,2.98]
    with pytest.raises(ValueError, match="20%"):
        validate_case(case)


def test_proportional_limit_and_vertical_mass(case):
    case["criteria"]["max_displacement_mm"] = .02
    result = assess(case, levels())
    limit = result["conditional_body_limit"]
    assert limit["available"]
    assert limit["governing_limit"] == "stiffness"
    assert limit["load_pattern_scale_factor"] == pytest.approx(.02/.0102)
    assert limit["vertical_payload_mass_equivalent_kg"] == pytest.approx(100*.02/.0102/9.80665)
    assert result["whole_installation_status"] == "not_assessed"


@pytest.mark.parametrize("condition", ["material_verified","dimensions_verified","supports_represent_actual_mounting",
                                       "load_pattern_verified","self_weight_negligible"])
def test_unknown_conditions_suppress_capacity(case, condition):
    case["conditions"][condition] = False
    limit = assess(case, levels())["conditional_body_limit"]
    assert not limit["available"] and limit["scaled_loads_n"] is None
    assert any(condition in reason for reason in limit["withheld_reasons"])


def test_missing_failure_model_suppresses_strength(case):
    del case["material"]["failure_criterion"]
    result = assess(case, levels())
    assert result["strength_utilization"] is None
    assert not result["conditional_body_limit"]["available"]


@pytest.mark.parametrize("section,key", [("material","yield_strength_mpa"),("criteria","yield_safety_factor"),
                                         ("criteria","max_displacement_mm")])
def test_missing_criteria_suppress_capacity(case, section, key):
    del case[section][key]
    assert not assess(case, levels())["conditional_body_limit"]["available"]


def test_growing_peak_is_not_clipped(case):
    result = assess(case, levels(stresses=(10.,20.,40.)))
    assert result["status"] == "indeterminate"
    assert not result["conditional_body_limit"]["available"]


def test_bad_equilibrium_invalidates(case):
    data = levels()
    data[0]["results"]["moment_balance_relative_error"] = .01
    result = assess(case, data)
    assert result["status"] == "invalid"
    assert not result["conditional_body_limit"]["available"]


def test_prediction_crossing_small_response_gate_withheld(case):
    case["criteria"]["max_displacement_mm"] = 5.
    data = levels(stresses=(1.,1.,1.))
    result = assess(case, data)
    assert not result["conditional_body_limit"]["available"]
    assert "predicted limiting load" in result["conditional_body_limit"]["withheld_reasons"][0]


def test_overload_reports_failed_body_and_lower_limit(case):
    case["criteria"]["max_displacement_mm"] = .005
    result = assess(case, levels())
    assert result["status"] == "fail_under_stated_model"
    assert result["conditional_body_limit"]["load_pattern_scale_factor"] < 1


def test_oblique_or_multiple_loads_not_called_hanging_mass(case):
    case["loads"][0]["total_force_n"] = [10.,0.,-100.]
    assert assess(case, levels())["conditional_body_limit"]["vertical_payload_mass_equivalent_kg"] is None
    case["loads"].append(copy.deepcopy(case["loads"][0]))
    assert assess(case, levels())["conditional_body_limit"]["vertical_payload_mass_equivalent_kg"] is None


def test_tri6_load_integrals_force_and_moment():
    p = np.array([[0,0,2],[2,0,2],[0,3,2],[1,0,2],[1,1.5,2],[0,1.5,2]],dtype=float)
    w, area, first = integrate_tri6(p)
    assert area == pytest.approx(3.)
    assert np.allclose(w[:3], 0., atol=1e-12)
    assert np.allclose(w[3:], 1.)
    force = np.array([10.,20.,-30.])
    loads = w[:,None]*force/area
    assert np.allclose(loads.sum(axis=0), force)
    assert np.allclose(np.cross(p, loads).sum(axis=0), np.cross(first/area,force))


def test_reference_topology_order_not_assumed():
    corners = np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]])
    gmsh_edges = [(0,1),(1,2),(2,0),(0,3),(2,3),(1,3)]
    local = np.vstack([corners]+[(corners[a]+corners[b])[None,:]/2 for a,b in gmsh_edges])
    perm = edge_permutation(local.ravel(),3,4,[(0,1),(1,2),(2,0),(0,3),(1,3),(2,3)])
    assert perm == [0,1,2,3,4,5,6,7,9,8]


def test_stale_face_ids_rejected():
    info = {"geometry_sha256":"a"*64,"faces":[{"id":1}]}
    with pytest.raises(ValueError,match="different geometry"):
        select_faces(info,{"type":"face_ids","ids":[1],"geometry_sha256":"b"*64})


def test_no_face_match_rejected():
    info = {"faces":[]}
    with pytest.raises(ValueError,match="no full"):
        select_faces(info,{"type":"plane","axis":"x","position_mm":0})


def test_mises_invariants():
    assert mises([100,100,100,0,0,0]) == 0
    assert mises([100,0,0,0,0,0]) == pytest.approx(100)
    assert mises([0,0,0,10,0,0]) == pytest.approx(np.sqrt(3)*10)


def test_exit_zero_error_log_is_failure(tmp_path, monkeypatch):
    inp = tmp_path/"job.inp"
    inp.write_text("dummy")
    def native_error(*args,**kwargs):
        kwargs['stdout'].write('*ERROR: invalid model\n')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("simplecae.solver.subprocess.run",native_error)
    with pytest.raises(RuntimeError,match="failed"):
        execute(tmp_path/"ccx", inp)
    assert (tmp_path/"job.solver.log").exists()


def test_stale_solver_results_rejected(tmp_path):
    inp = tmp_path/"job.inp"
    inp.write_text("dummy")
    inp.with_suffix(".dat").write_text("old fields")
    with pytest.raises(ValueError,match="already exists"):
        execute(tmp_path/"ccx", inp)


def test_incomplete_dat_rejected(tmp_path):
    p = tmp_path/"bad.dat"
    p.write_text("displacements (vx,vy,vz)\n 1 1D-3 0 0\n")
    with pytest.raises(RuntimeError,match="incomplete"):
        parse_dat(p)
