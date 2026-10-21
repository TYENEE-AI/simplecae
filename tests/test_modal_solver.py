"""Physical references for the unprestressed native modal backend."""
import copy
import numpy as np
import pytest

from simplecae.geometry import make_mesh
from simplecae.solver import execute, find_ccx
from simplecae import modal_solver as modal


@pytest.fixture
def beam(tmp_path):
    import gmsh
    path = tmp_path/"beam.step"
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("beam")
        gmsh.model.occ.addBox(0, 0, 0, 100, 10, 6)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    case = {"schema_version": "modal-solid-1.0",
            "model": {"path": str(path), "expected_bbox_mm": [[0, 0, 0], [100, 10, 6]]},
            "material": {"young_mpa": 2000., "poisson": .3, "density_kg_m3": 1200.},
            "supports": [{"name": "root", "selector": {
                "type": "plane", "axis": "x", "position_mm": 0}}],
            "mesh": {"max_elements": 20000, "preserve_boundary_nodes": True}}
    return case, tmp_path


def solve(beam, *, count=8, free_body=False, h=5, label="modal"):
    case, directory = beam
    directory = directory/label
    directory.mkdir()
    mesh = make_mesh(case, h, directory, allow_free_body=free_body)
    path = directory/"modes.inp"
    modal.write_deck(case, mesh, path, count)
    execute(find_ccx(), path, timeout=90, analysis_type="frequency")
    parsed = modal.parse_dat(path.with_suffix(".dat"), mesh[0], count)
    evidence = modal.audit(directory, case["material"], mesh, parsed, free_body=free_body)
    return mesh, parsed, evidence, path


def test_cantilever_bending_reference(beam):
    _, (_, _, frequency, _), evidence, _ = solve(beam)
    # Euler-Bernoulli thin-beam limit; 3D shear/root effects are explicit.
    expected = 1.875104068711961**2/(2*np.pi*.1**2)*np.sqrt(2e9*.006**2/(12*1200))
    assert frequency[0] == pytest.approx(expected, rel=.025)
    assert frequency[1] == pytest.approx(expected*10/6, rel=.035)
    assert evidence["passed"], evidence
    assert evidence["total_mass_kg"] == pytest.approx(.0072, rel=1e-5)


def test_stiffness_density_scaling(beam):
    mesh, base, _, path = solve(beam, count=4)
    for name, key, factor, ratio in (("stiffness", "young_mpa", 4, 2),
                                      ("mass", "density_kg_m3", 4, .5)):
        c = copy.deepcopy(beam[0])
        c["material"][key] *= factor
        deck = path.with_name(name+".inp")
        modal.write_deck(c, mesh, deck, 4)
        execute(find_ccx(), deck, timeout=90, analysis_type="frequency")
        parsed = modal.parse_dat(deck.with_suffix(".dat"), mesh[0], 4)
        assert np.allclose(parsed[2], base[2]*ratio, rtol=2e-5)
        assert modal.audit(path.parent, c["material"], mesh, parsed)["passed"]


def test_free_body_has_six_rigid_modes(beam):
    beam[0]["supports"] = []
    _, parsed, evidence, _ = solve(beam, free_body=True, count=12)
    assert evidence["passed"], evidence
    assert evidence["rigid_mode_indices"] == list(range(6))
    assert np.max(np.abs(parsed[1][:6])) < 1e-6*parsed[1][6]


def test_inadequate_support_is_rejected(beam):
    beam[0]["supports"][0]["dofs"] = [1]
    with pytest.raises(ValueError, match="rigid-body"):
        solve(beam)


def test_axial_rod_reference_and_corrupted_eigenvector(beam):
    # Prescribed transverse guide at every node gives the 1D axial rod limit.
    c, directory = beam
    c["material"]["poisson"] = 0
    mesh = make_mesh(c, 5, directory)
    for n in mesh[0]:
        ds = mesh[-1]["fixed_dofs"].setdefault(str(n), [])
        mesh[-1]["fixed_dofs"][str(n)] = sorted(set(ds) | {2, 3})
    path = directory/"axial.inp"
    modal.write_deck(c, mesh, path, 4)
    execute(find_ccx(), path, timeout=90, analysis_type="frequency")
    parsed = modal.parse_dat(path.with_suffix(".dat"), mesh[0], 4)
    expected = np.sqrt(2e9/1200)/(.1*4)
    assert parsed[2][0] == pytest.approx(expected, rel=.001)
    # The first axial frequency is the reference; higher 3D guided modes can
    # vary across the cross section and are not labelled 1D harmonics.
    assert modal.audit(directory, c["material"], mesh, parsed)["passed"]
    damaged = list(copy.deepcopy(parsed))
    damaged[3][0, -1, 0] += 1
    evidence = modal.audit(directory, c["material"], mesh, damaged)
    assert not evidence["passed"]
    assert not evidence["checks"]["eigen_residual_passed"]
    damaged[3][0] = 0
    with pytest.raises(ValueError, match="nonzero"):
        modal.audit(directory, c["material"], mesh, damaged)


def test_malformed_and_incomplete_native_output(beam):
    mesh, parsed, _, path = solve(beam, count=4)
    original = path.with_suffix(".dat").read_text()
    for text in (original[:len(original)//2], original.replace("displacements", "unrequested"),
                 original+original):
        bad = path.with_name("bad.dat")
        bad.write_text(text)
        with pytest.raises(ValueError):
            modal.parse_dat(bad, mesh[0], 4)
    with pytest.raises(ValueError, match="eigenpairs"):
        modal.parse_dat(path.with_suffix(".dat"), mesh[0], 5)


def test_three_mesh_field_correspondence(beam):
    from simplecae.modal_matching import compare_meshes
    solves = [solve(beam, h=h, count=4, label=f"grid-{i}") for i, h in enumerate((6, 4.5, 3.3))]
    for a, b in zip(solves, solves[1:]):
        correspondence = compare_meshes(a[3].parent, b[3].parent, a[1], b[1])
        assert correspondence["passed"], correspondence
