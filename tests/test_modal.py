import copy
import json
from pathlib import Path
import numpy as np
import pytest

from test_modal_solver import beam
from simplecae.case import write_json
from simplecae.api import check_case, analyze_case
from simplecae import modal


def case_file(beam):
    c, directory = beam
    c = copy.deepcopy(c)
    c["model"]["units"] = "mm"
    c["material"].update(name="analytical reference", basis="Constant isotropic mathematical reference")
    c["supports"][0].update(target="root face", basis="Fully built-in analytical boundary")
    c.update(support_mode="supported", elastic_mode_count=2,
             criteria=[{"id": "first", "type": "minimum_elastic_frequency",
                        "target": "beam", "basis": "Declared reference acceptance threshold", "minimum_hz": 100}],
             assumptions=["Small vibration about undeformed and unprestressed reference."],
             not_assessed=["Physical mounting and actual print properties."],
             conditions={"properties_verified": False, "mounting_verified": False},
             provenance={"task_id": "modal-reference", "revision": "initial"})
    c["mesh"]["sizes_mm"] = [6, 4.5, 3.3]
    c["mesh"]["max_elements"] = 10000
    path = directory/"case.json"
    write_json(path, c)
    return path, c


def test_local_refinement_is_available_and_source_bound(beam):
    from simplecae.case import sha256
    from simplecae.geometry import inspect, make_mesh
    path, c = case_file(beam)
    model=Path(c["model"]["path"])
    info=inspect(model,beam[1]/"inspection.json")
    c["mesh"]["local_refinements"]=[{
        "name":"selected-feature",
        "selector":{"type":"face_ids","ids":[info["faces"][0]["id"]],
                    "geometry_sha256":sha256(model)},
        "size_factor":.6,"distance_mm":2.}]
    write_json(path,c)
    checked=modal.read_case(path)
    directory=beam[1]/"local-mesh";directory.mkdir()
    mesh=make_mesh(checked,6,directory)
    assert mesh[-1]["local_refinements"][0]["surface_mesh"]["available"]
    c["mesh"]["local_refinements"][0]["selector"]["geometry_sha256"]="0"*64
    write_json(path,c)
    directory=beam[1]/"stale-local-mesh";directory.mkdir()
    with pytest.raises(ValueError,match="hash|different|geometry"):
        make_mesh(modal.read_case(path),6,directory)
    c["mesh"]["local_refinements"]*=2
    write_json(path,c)
    with pytest.raises(ValueError,match="unique"):
        modal.read_case(path)


def test_api_qualification_compact_evidence_and_mutation(beam):
    path, c = case_file(beam)
    assert check_case(path)["schema_version"] == modal.SCHEMA
    r = analyze_case(path, beam[1]/"run", predict_capacity=False)
    assert r["status"] == "pass_under_stated_model", r.get("verification", r.get("error"))
    assert r["evaluation_signal"]["valid_for_comparison"]
    assert not r["whole_product_pass_available"]
    assert (beam[1]/"run/mesh-3/modes.dat.gz").exists()
    assert not (beam[1]/"run/mesh-3/modes.dat").exists()
    assert modal.signal(r)["valid_for_comparison"]
    from simplecae.workbench import create_session, add_result, snapshot
    viewer = beam[1]/"viewer"
    create_session(viewer, "Modal reference")
    add_result(viewer, beam[1]/"run/result.json")
    view = snapshot(viewer)["runs"][0]
    assert view["state"] == "completed", view.get("error")
    field = view["datasets"][0]
    assert field["physics"] == "modal"
    assert len(field["modal_modes"]) == 4
    assert all(max(m["nodal_magnitude"]) == pytest.approx(1) for m in field["modal_modes"])
    assert not field["stress"]
    changed = copy.deepcopy(r)
    changed["levels"][-1]["elastic_frequencies_hz"][0] *= 2
    assert not modal.signal(changed)["valid_for_comparison"]
    evidence = beam[1]/"run/mesh-3/modes.npz"
    with evidence.open("ab") as f:
        f.write(b"changed")
    bad = modal.signal(r)
    assert not bad["valid_for_comparison"]
    assert bad["criterion_assessments"]["first"]["status"] == "indeterminate"


def test_resonance_failure_insufficient_coverage_and_absent_criteria(beam):
    path, c = case_file(beam)
    c["criteria"] = [{"id": "band", "type": "avoid_excitation_band", "target": "beam",
                      "basis": "Given motor forcing band", "band_hz": [110, 140],
                      "separation_ratio": .05}]
    write_json(path, c)
    r = analyze_case(path, beam[1]/"run", predict_capacity=False)
    assert r["status"] == "fail_under_stated_model", r.get("verification", r.get("error"))
    assert any(f.get("requires_reanalysis") for f in r["evaluation_signal"]["feedback"])
    located = r["evaluation_signal"]["feedback"][0]
    assert located["criterion"] == "band" and located["modes"][0]["nodal_antinode_mm"]
    assert not r["evaluation_signal"]["whole_installation_rating_available"]
    # Change only assessment inputs to exercise insufficient-coverage logic;
    # these copies are NOT sealed results and cannot be used as CAD evidence.
    missing = copy.deepcopy(c)
    missing["criteria"][0]["band_hz"] = [1e5, 2e5]
    matches = r["verification"]["shape_correspondence"]
    status, criteria, _ = modal.assess(missing, r["levels"], matches)
    assert status == "indeterminate"
    assert not criteria["band"]["band_coverage_passed"]
    missing["criteria"] = []
    assert modal.assess(missing, r["levels"], matches)[0] == "indeterminate"
    invalid_levels = copy.deepcopy(r["levels"])
    invalid_levels[0]["audit"]["passed"] = False
    assert modal.assess(c, invalid_levels, matches)[1]["band"]["status"] == "indeterminate"


@pytest.mark.parametrize("mutation", [
    lambda c: c.update(loads=[{"force": 10}]),
    lambda c: c["material"].update(density_kg_m3=0),
    lambda c: c["material"].update(young_mpa=float("nan")),
    lambda c: c["material"].update(poisson=.5),
    lambda c: c["model"].update(units="m"),
    lambda c: c.update(support_mode="free_body"),
    lambda c: c["mesh"].update(sizes_mm=[6, 6, 3]),
    lambda c: c.update(criteria=[{"id": "x", "type": "avoid_excitation_band", "target": "part",
                                  "basis": "reference", "band_hz": [100, 10], "separation_ratio": .1}]),
])
def test_input_failures(beam, mutation):
    path, c = case_file(beam)
    check_case(path)
    mutation(c)
    path.write_text(json.dumps(c), encoding="utf-8")
    with pytest.raises(ValueError):
        check_case(path)


@pytest.mark.parametrize("minimum,outcome", [(100., "pass"), (150., "fail")])
def test_actual_agent_modal_check_preserves_physical_pending(beam, minimum, outcome):
    from verify_modal import task_manifest
    from simplecae.task import start_task, run_task_check
    from simplecae.workbench import snapshot
    path, c = case_file(beam)
    c["provenance"]["task_id"] = "modal-cad-reference"
    c["criteria"][0]["minimum_hz"] = minimum
    write_json(path, c)
    tp = beam[1]/"agent.task.json"
    task_manifest(tp, path)
    task = json.loads(tp.read_text(encoding="utf-8"))
    task["checks"][0]["result_criteria"] = ["first"]
    task["checks"][0]["acceptance"] = f"Lowest elastic frequency above {minimum} Hz"
    write_json(tp, task)
    workspace = beam[1]/"agent"
    start_task(tp, workspace)
    status = run_task_check(workspace, "resonance", budget_seconds=120)
    assert status["checks"][0]["outcome"] == outcome, status["checks"][0]
    assert status["checks"][1]["outcome"] == "pending"
    assert not status["whole_product_pass_available"]
    view = snapshot(workspace/"viewer")
    assert view["runs"][-1]["analysis"] == "modal"
    assert view["runs"][-1]["datasets"][0]["physics"] == "modal"
    assert sum(e["stage"] == "modal" for e in view["runs"][-1]["events"]) == 3
    assert sum(e["stage"] == "modal_match" for e in view["runs"][-1]["events"]) == 2


def test_curved_solid_repeated_bending_modes(tmp_path):
    import gmsh
    path = tmp_path/"round-post.step"
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("round-post")
        gmsh.model.occ.addCylinder(0, 0, 0, 0, 0, 50, 5)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    original = {"schema_version": modal.SCHEMA,
                "model": {"path": str(path), "expected_bbox_mm": [[-5, -5, 0], [5, 5, 50]]},
                "material": {"young_mpa": 2000., "poisson": .3, "density_kg_m3": 1200.},
                "supports": [{"name": "base", "selector": {"type": "plane", "axis": "z", "position_mm": 0}}],
                "mesh": {"preserve_boundary_nodes": True}}
    cp, c = case_file((original, tmp_path))
    c["mesh"]["sizes_mm"] = [5., 3.5, 2.5]
    write_json(cp, c)
    r = analyze_case(cp, tmp_path/"run", predict_capacity=False)
    assert r["status"] == "pass_under_stated_model", r.get("error") or r.get("verification")
    f = r["levels"][-1]["elastic_frequencies_hz"]
    assert f[0] == pytest.approx(f[1], rel=.005)
    matches = r["verification"]["shape_correspondence"]
    assert all(any(len(g["coarse_modes"]) == 2 for g in m["groups"]) for m in matches)
    assert all(l["audit"]["checks"]["mass_quadrature_passed"] for l in r["levels"])
    stored = json.loads((tmp_path/"run/result.json").read_text(encoding="utf-8"))
    assert modal.signal(stored)["valid_for_comparison"]
