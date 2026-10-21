"""Native analytical references for the in-development conduction backend."""
import copy
from pathlib import Path

import numpy as np
import pytest

from simplecae.geometry import make_mesh
from simplecae.solver import execute, find_ccx
from simplecae.thermal_solid_solver import (
    compile_boundaries, write_deck, parse_fields, energy_history, tetra10_gradient, tri6_mass)


def end(axis, position):
    return {"type": "plane", "axis": axis, "position_mm": position}


@pytest.fixture
def solid(tmp_path):
    import gmsh
    step = tmp_path / "slab.step"
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("slab")
        gmsh.model.occ.addBox(0, 0, 0, 20, 10, 10)
        gmsh.model.occ.synchronize()
        gmsh.write(str(step))
    finally:
        gmsh.finalize()
    c = {"schema_version": "thermal-solid-1.0", "mode": "steady",
         "model": {"path": str(step), "expected_bbox_mm": [[0, 0, 0], [20, 10, 10]]},
         "mesh": {"max_elements": 20000, "preserve_boundary_nodes": True},
         "material": {"conductivity_w_mk": 2.},
         "boundaries": [{"name": "cold", "type": "temperature", "selector": end("x", 0),
                         "temperature_c": 20.},
                        {"name": "hot", "type": "temperature", "selector": end("x", 20),
                         "temperature_c": 100.}]}
    mesh = make_mesh(c, 5, tmp_path)
    return c, mesh, tmp_path


def solve(solid, c=None, steps=None, label="thermal"):
    original, mesh, directory = solid
    c = c if c is not None else original
    patches, fixed = compile_boundaries(c, mesh, directory)
    deck = directory / (label + ".inp")
    write_deck(c, mesh, patches, fixed, deck, steps)
    record = execute(find_ccx(), deck, timeout=60, analysis_type="thermal")
    expected = np.linspace(c["duration_s"]/steps, c["duration_s"], steps) if steps else [1.]
    frames = parse_fields(deck.with_suffix(".dat"), mesh[0], mesh[1], expected)
    assert record["returncode"] == 0
    return frames, patches, deck


def test_linear_slab_temperature_flux_and_reactions(solid):
    frames, _, _ = solve(solid)
    f = frames[0][1]
    coords = solid[1][0]
    assert max(abs(t - (20 + 4*coords[n][0])) for n, t in f["temperature_c"].items()) < 1e-4
    assert np.max(np.abs(np.array(list(f["flux_w_m2"].values())) - [-8000, 0, 0])) < 1e-4
    cold = sum(v for n, v in f["rfl_w"].items() if abs(coords[n][0]) < 1e-7)
    hot = sum(v for n, v in f["rfl_w"].items() if abs(coords[n][0]-20) < 1e-7)
    assert cold == pytest.approx(-.8, abs=1e-7)
    assert hot == pytest.approx(.8, abs=1e-7)
    assert "fixed_dofs" not in solid[1][-1]
    assert solid[1][-1]["physics"] == "heat_transfer"
    patches, fixed = compile_boundaries(solid[0], solid[1], solid[2])
    e = energy_history(solid[0], patches, fixed, frames, solid[2])[0]
    assert abs(e["reservoir_input_w"]) < 1e-7
    assert e["reservoir_exchange_scale_w"] >= 1.6-1e-7


def test_curved_cylinder_preserves_native_coordinates_and_linear_conduction(tmp_path):
    import gmsh
    step = tmp_path/"cylinder.step"
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("cylinder")
        gmsh.model.occ.addCylinder(0, 0, 0, 0, 0, 50, 5)
        gmsh.model.occ.synchronize()
        gmsh.write(str(step))
    finally:
        gmsh.finalize()
    c = {"schema_version": "thermal-solid-1.0", "mode": "steady",
         "model": {"path": str(step), "expected_bbox_mm": [[-5, -5, 0], [5, 5, 50]]},
         "mesh": {"max_elements": 10000, "preserve_boundary_nodes": True},
         "material": {"conductivity_w_mk": 2.},
         "boundaries": [{"name": "cold", "type": "temperature", "selector": end("z", 0), "temperature_c": 20.},
                        {"name": "hot", "type": "temperature", "selector": end("z", 50), "temperature_c": 100.}]}
    # Native Gmsh topology differs across platforms. A single coarse curved
    # mesh is not an exact cylinder: keep its measured failure, and verify
    # refinement against the SAME analytical solution, BCs and accuracy limits.
    from simplecae.case import write_json
    references = []
    for size in (1.8, 1.5, 1.35):
        directory = tmp_path / f"mesh-{size}"
        directory.mkdir()
        mesh = make_mesh(c, size, directory)
        frames, patches, _ = solve((c, mesh, directory))
        f = frames[0][1]
        temperature_error = float(max(abs(t-(20+1.6*mesh[0][n][2]))
                                      for n, t in f["temperature_c"].items()))
        flux_error = float(np.max(np.abs(np.array(list(f["flux_w_m2"].values()))-[0, 0, -3200])))
        reference = {"mesh_size_mm": size, "elements": len(mesh[1]),
                     "temperature_error_c": temperature_error,
                     "temperature_limit_c": 1e-4, "temperature_passed": temperature_error < 1e-4,
                     "flux_error_w_m2": flux_error, "flux_limit_w_m2": 1e-3,
                     "pointwise_flux_passed": flux_error < 1e-3}
        references.append(reference)
        write_json(directory/"curved-reference.json", reference)
        write_json(tmp_path/"curved-reference-study.json", references)
        e = energy_history(c, patches, compile_boundaries(c, mesh, directory)[1], frames, directory)[0]
        assert abs(e["reservoir_input_w"]) < 1e-6
        if size == 1.8:
            coarse_mesh, coarse_patches = mesh, patches
    assert all(r["temperature_passed"] for r in references[-2:])
    assert references[-1]["temperature_error_c"] <= references[0]["temperature_error_c"]
    assert references[-1]["flux_error_w_m2"] < references[0]["flux_error_w_m2"]
    # Strict local flux remains unqualified. Do not promote temperature or
    # energy-balance success into pointwise-flux acceptance.
    assert all(r["pointwise_flux_passed"] is False for r in references)
    # Independent manufactured-field patch test: prescribe the known linear
    # temperature at every node to isolate coordinate/gradient serialization.
    # This is not presented as a second solution of the natural-boundary case.
    mesh, patches = coarse_mesh, coarse_patches
    fixed = {n: 20+1.6*p[2] for n, p in mesh[0].items()}
    deck = tmp_path/"linear-patch.inp"
    write_deck(c, mesh, patches, fixed, deck)
    execute(find_ccx(), deck, timeout=60, analysis_type="thermal")
    patch = parse_fields(deck.with_suffix(".dat"), mesh[0], mesh[1], [1.])[0][1]
    assert np.max(np.abs(np.array(list(patch["flux_w_m2"].values()))-[0, 0, -3200])) < 1e-3


def test_uniform_flux_sign_units_and_balance(solid):
    c = copy.deepcopy(solid[0])
    c["boundaries"][1] = {"name": "in", "type": "heat_flux", "selector": end("x", 20),
                          "flux_w_m2": 1000.}
    frames, patches, _ = solve(solid, c)
    f = frames[0][1]
    assert patches["in"]["area_m2"] == pytest.approx(.0001)
    assert max(abs(t - (20 + .5*solid[1][0][n][0])) for n, t in f["temperature_c"].items()) < 1e-4
    e = energy_history(c, patches, compile_boundaries(c, solid[1], solid[2])[1], frames, solid[2])[0]
    assert e["reservoir_input_w"] == pytest.approx(-.1, abs=1e-7)
    assert e["surface_input_w"]["in"] == pytest.approx(.1, abs=1e-7)
    assert e["max_free_node_residual_w"] < 1e-7
    assert e["max_conductive_field_residual_w"] < 2e-6


def test_convection_resistance_reference(solid):
    c = copy.deepcopy(solid[0])
    c["boundaries"][1] = {"name": "film", "type": "convection", "selector": end("x", 20),
                          "coefficient_w_m2k": 100., "ambient_temperature_c": 100.}
    frames, patches, _ = solve(solid, c)
    f = frames[0][1]
    assert max(abs(t - (20 + 2*solid[1][0][n][0])) for n, t in f["temperature_c"].items()) < 1e-4
    e = energy_history(c, patches, compile_boundaries(c, solid[1], solid[2])[1], frames, solid[2])[0]
    assert e["reservoir_input_w"] == pytest.approx(-.4, abs=1e-7)
    assert e["surface_input_w"]["film"] == pytest.approx(.4, abs=1e-7)
    assert e["max_free_node_residual_w"] < 1e-7


def test_internal_generation_quadratic_field(solid):
    c = copy.deepcopy(solid[0])
    c["boundaries"][1]["temperature_c"] = 20.
    c["volumetric_heat_w_m3"] = 1e6
    frames, patches, _ = solve(solid, c)
    f = frames[0][1]
    x = {n: p[0]*.001 for n, p in solid[1][0].items()}
    expected = {n: 20+1e6/(2*2)*v*(.02-v) for n, v in x.items()}
    assert max(abs(t-expected[n]) for n, t in f["temperature_c"].items()) < 1e-4
    e = energy_history(c, patches, compile_boundaries(c, solid[1], solid[2])[1], frames, solid[2])[0]
    assert e["reservoir_input_w"] == pytest.approx(-2., abs=1e-6)
    assert e["body_input_w"] == pytest.approx(2., abs=1e-7)
    assert e["max_free_node_residual_w"] < 1e-7


def test_insulated_transient_generation_has_no_load_ramp(solid):
    c = copy.deepcopy(solid[0])
    c.update(mode="transient", initial_temperature_c=20., duration_s=10.,
             volumetric_heat_w_m3=1e6, boundaries=[])
    c["material"].update(density_kg_m3=1000., specific_heat_j_kgk=1000.)
    frames, patches, _ = solve(solid, c, steps=10)
    for time, fields in frames:
        assert max(abs(v-(20+time)) for v in fields["temperature_c"].values()) < 1e-4
        # Uniform temperature has zero conductive contribution; it does not
        # imply that the nonzero body heat input or storage rate vanishes.
        assert sum(fields["rfl_w"].values()) == pytest.approx(0., abs=1e-6)
    for e in energy_history(c, patches, {}, frames, solid[2]):
        assert e["body_input_w"] == pytest.approx(2., abs=1e-7)
        assert e["storage_rate_w"] == pytest.approx(2., abs=1e-7)
        assert e["max_free_node_residual_w"] < 1e-7


def test_steady_floating_body_rejected(solid):
    c = copy.deepcopy(solid[0])
    c["boundaries"] = []
    with pytest.raises(ValueError, match="reference"):
        compile_boundaries(c, solid[1], solid[2])


def test_overlapping_thermal_boundaries_rejected(solid):
    c = copy.deepcopy(solid[0])
    c["boundaries"][1]["selector"] = end("x", 0)
    with pytest.raises(ValueError, match="overlap"):
        compile_boundaries(c, solid[1], solid[2])


def test_shared_edge_conflicting_temperature_rejected(solid):
    c = copy.deepcopy(solid[0])
    c["boundaries"][1]["selector"] = end("y", 0)
    with pytest.raises(ValueError, match="Conflicting"):
        compile_boundaries(c, solid[1], solid[2])


def test_parser_rejects_truncated_duplicate_nonfinite_or_wrong_time(solid):
    _, _, deck = solve(solid)
    text = deck.with_suffix(".dat").read_text()
    broken = solid[2] / "broken.dat"
    broken.write_text(text[:text.index(" heat flux")])
    with pytest.raises(ValueError, match="coverage"):
        parse_fields(broken, solid[1][0], solid[1][1], [1.])
    broken.write_text(text + text)
    with pytest.raises(ValueError, match="Duplicate"):
        parse_fields(broken, solid[1][0], solid[1][1], [1.])
    with pytest.raises(ValueError, match="increments"):
        parse_fields(deck.with_suffix(".dat"), solid[1][0], solid[1][1], [.5, 1.])
    lines = text.splitlines()
    first = next(i for i, line in enumerate(lines) if "temperatures for set" in line)
    row = next(i for i in range(first+1, len(lines)) if len(lines[i].split()) == 2)
    lines[row] = lines[row].split()[0] + " NaN"
    broken.write_text("\n".join(lines))
    with pytest.raises(ValueError, match="Non-finite"):
        parse_fields(broken, solid[1][0], solid[1][1], [1.])


def test_nonuniform_transient_energy_uses_native_consistent_capacity(solid):
    c = copy.deepcopy(solid[0])
    c.update(mode="transient", initial_temperature_c=20., duration_s=10.,
             volumetric_heat_w_m3=1e6)
    c["boundaries"][1]["temperature_c"] = 20.
    c["material"].update(density_kg_m3=1000., specific_heat_j_kgk=1000.)
    frames, patches, _ = solve(solid, c, steps=20)
    fixed = compile_boundaries(c, solid[1], solid[2])[1]
    energy = energy_history(c, patches, fixed, frames, solid[2])
    assert max(abs(e["balance_error_w"]) for e in energy) < 5e-6
    assert max(e["max_free_node_residual_w"] for e in energy) < 4e-7
    assert max(e["max_conductive_field_residual_w"] for e in energy) < 2e-6
    # Mesh/time qualification is separate. This coarse reference tolerates the
    # expected discretisation error; it cannot give a design acceptance signal.
    final = frames[-1][1]["temperature_c"]
    for n, xyz in solid[1][0].items():
        x = xyz[0]*.001
        expected = 20+1e6/4*x*(.02-x)
        expected -= sum(4*1e6*.02**2/(2*np.pi**3*j**3)*np.sin(j*np.pi*x/.02)
                        * np.exp(-2e-6*(j*np.pi/.02)**2*10) for j in range(1, 100, 2))
        assert abs(final[n]-expected) < .3
    corrupt = copy.deepcopy(frames)
    target = next(n for n in solid[1][0] if n not in fixed)
    corrupt[-1][1]["temperature_c"][target] += 10.
    audit = energy_history(c, patches, fixed, corrupt, solid[2])
    assert audit[-1]["max_conductive_field_residual_w"] > .001


def test_basis_derivatives_and_surface_integration():
    from simplecae.loads import tetra10_basis
    points = np.array([[.1, .2, .3], [.25, .25, .25], [.6, .1, .1]])
    exact = tetra10_gradient(points)
    for axis in range(3):
        delta = np.eye(3)[axis]*1e-6
        numerical = (tetra10_basis(points+delta)-tetra10_basis(points-delta))/(2e-6)
        np.testing.assert_allclose(exact[:, :, axis], numerical, atol=1e-9)
    # Unit right triangle: both rules integrate its area and linear field.
    p = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                  [.5, 0, 0], [.5, .5, 0], [0, .5, 0]])
    for native in (False, True):
        m = tri6_mass(p, native=native)
        assert m.sum() == pytest.approx(.5)
        assert np.ones(6) @ m @ p[:, 0] == pytest.approx(1/6)
