"""Unprestressed, undamped C3D10 normal-mode primitives in SI units.

Independent matrix-action checks use the documented native four-point rule.
The higher-order consistent mass is retained as a separate integration audit.
Eigenvectors are mass normalized by the solver, never physical displacement.
"""
from __future__ import annotations

from pathlib import Path
import re
import numpy as np
from scipy.sparse import coo_matrix, kron, eye, diags

from .loads import tetra10_basis
from .thermal_solid_solver import tetra10_gradient
from .solver import dat_real, native_real
from .constraints import boundary_lines, rigid_diagnostics


def write_deck(case, mesh, path, count):
    coords, tets, _, _, meta = mesh
    m = case["material"]
    if type(count) is not int or not 1 <= count <= 80:
        raise ValueError("Request between 1 and 80 native modes")
    lines = ["*HEADING", "SimpleCAE normal modes; m kg s Pa; no preload", "*NODE,NSET=NALL"]
    lines += [f"{n}," + ",".join(native_real(float(v)*.001) for v in p)
              for n, p in sorted(coords.items())]
    lines += ["*ELEMENT,TYPE=C3D10,ELSET=EALL"]
    lines += [f"{e}," + ",".join(map(str, ns)) for e, ns in sorted(tets.items())]
    lines += ["*MATERIAL,NAME=BODY", "*ELASTIC",
              f"{native_real(m['young_mpa']*1e6)},{native_real(m['poisson'])}",
              "*DENSITY", native_real(m["density_kg_m3"]),
              "*SOLID SECTION,ELSET=EALL,MATERIAL=BODY"]
    from .modal_mass import compile_masses
    masses,reports=compile_masses(case,mesh,Path(path).parent)
    meta['attached_nodal_mass_kg']=masses;meta['attached_mass_reports']=reports
    for index,(node,mass) in enumerate(sorted(masses.items()),start=1):
        name=f'ADDMASS{index}'
        lines += [f'*ELEMENT,TYPE=MASS,ELSET={name}',f'{max(tets)+index},{node}',
                  f'*MASS,ELSET={name}',native_real(mass)]
    if meta["fixed_dofs"]:
        lines += ["*BOUNDARY", *boundary_lines(meta["fixed_dofs"])]
    # No minimum/maximum frequency filter: preserve every requested low mode.
    lines += ["*STEP", "*FREQUENCY,SOLVER=SPOOLES", str(count),
              "*NODE PRINT,NSET=NALL", "U", "*NODE FILE", "U", "*END STEP"]
    Path(path).write_text("\n".join(lines)+"\n", encoding="ascii")


def parse_dat(path, node_ids, count):
    """Reject incomplete or ambiguous eigenvalue/vector tables."""
    text = Path(path).read_text(encoding="ascii", errors="strict")
    eigenvalues = {}
    shapes = {}
    state, mode = None, None
    for line in text.splitlines():
        compact = re.sub(r"\s+", "", line).upper()
        if "EIGENVALUENUMBER" in compact:
            match = re.search(r"EIGENVALUENUMBER(\d+)", compact)
            if match:
                mode = int(match[1])
                if mode in shapes:
                    raise ValueError("Duplicate eigenmode field")
                shapes[mode] = {}
                state = None
                continue
        if "MODE" in compact and "EIGENVALUE" in compact and "FREQUENCY" in compact:
            state = "eigenvalues"
            continue
        if line.strip().lower().startswith("displacements"):
            if mode is None:
                raise ValueError("Displacement field has no eigenmode number")
            state = "shape"
            continue
        tokens = line.split()
        if tokens and re.fullmatch(r"\d+", tokens[0]):
            if state == "eigenvalues":
                if len(tokens) != 5:
                    raise ValueError("Malformed eigenvalue row")
                n = int(tokens[0])
                if n in eigenvalues:
                    raise ValueError("Duplicate eigenvalue")
                eigenvalues[n] = [dat_real(x) for x in tokens[1:]]
            elif state == "shape":
                if len(tokens) != 4:
                    raise ValueError("Malformed modal displacement row")
                n = int(tokens[0])
                if n in shapes[mode]:
                    raise ValueError("Duplicate modal node")
                shapes[mode][n] = [dat_real(x) for x in tokens[1:]]
        elif tokens and not all(set(t) <= set("-=") for t in tokens):
            # Headings for participation/effective mass must not become modes.
            if state == "eigenvalues" and eigenvalues:
                state = None
            elif state == "shape" and shapes[mode]:
                state = None
    expected = set(range(1, count+1))
    if set(eigenvalues) != expected or set(shapes) != expected:
        raise ValueError("Missing or extra eigenpairs")
    ids = sorted(map(int, node_ids))
    if any(set(v) != set(ids) for v in shapes.values()):
        raise ValueError("Incomplete modal nodal fields")
    table = np.array([eigenvalues[i] for i in range(1, count+1)])
    u = np.array([[shapes[i][n] for n in ids] for i in range(1, count+1)])
    if not np.isfinite(table).all() or not np.isfinite(u).all():
        raise ValueError("Nonfinite eigenpair")
    # Columns: lambda, real angular frequency, real Hz, imaginary angular
    # frequency. Tiny negative rigid eigenvalues are retained, not clipped;
    # the audit must establish their rigid shape AND negligible eigenvalue.
    lam, omega, frequency = table[:, 0], table[:, 1], table[:, 2]
    imaginary = table[:, 3]
    if (np.any(table[:, 1:] < 0) or np.any((omega > 0) & (imaginary > 0))
            or not np.allclose(omega**2-imaginary**2, lam, rtol=2e-5, atol=1e-10)
            or not np.allclose(omega/(2*np.pi), frequency, rtol=2e-5, atol=1e-10)
            or np.any(np.diff(lam) < -max(1e-8, np.max(np.abs(lam))*1e-8))):
        raise ValueError("Inconsistent eigenvalue/frequency table")
    return np.array(ids), lam, frequency, u


def matrices(directory, material):
    """Independently assemble isotropic elasticity and consistent mass.

Only sparse matrices; no dense ndof-by-ndof allocation. The 30-by-30 element
stiffness uses engineering shear strains. Geometric Jacobians are evaluated
from the actual quadratic coordinates, including curved mid-edge nodes.
"""
    with np.load(Path(directory)/"mesh.npz", allow_pickle=False) as d:
        ids = np.sort(d["node_ids"])
        xyz = d["xyz"][np.argsort(d["node_ids"])]*.001
        rows = {int(n): i for i, n in enumerate(ids)}
        conn = np.array([[rows[int(n)] for n in ns] for ns in d["connectivity"]])
        ip = d["native_volume_quadrature_points"]
        w = d["native_volume_quadrature_measures_mm3"]*1e-9
        hi_basis = tetra10_basis(d["volume_quadrature_points"])
        hi_w = d["volume_quadrature_measures_mm3"]*1e-9
    basis, grads = tetra10_basis(ip), tetra10_gradient(ip)
    young, nu, rho = material["young_mpa"]*1e6, material["poisson"], material["density_kg_m3"]
    shear = young/(2*(1+nu))
    lame = young*nu/((1+nu)*(1-2*nu))
    constitutive = np.diag([2*shear]*3+[shear]*3)
    constitutive[:3, :3] += lame
    kr, kc, kv, mr, mc, mv, mhv = [], [], [], [], [], [], []
    for e, nodes in enumerate(conn):
        points = xyz[nodes]
        jac = np.einsum("qia,ib->qab", grads, points)
        spatial = np.einsum("qia,qba->qib", grads, np.linalg.inv(jac))
        b = np.zeros((len(ip), 6, 30))
        for a in range(3):
            b[:, a, a::3] = spatial[:, :, a]
        for s, (a, c) in enumerate(((0, 1), (1, 2), (0, 2)), 3):
            b[:, s, a::3] = spatial[:, :, c]
            b[:, s, c::3] = spatial[:, :, a]
        ke = np.einsum("qai,ab,qbj,q->ij", b, constitutive, b, w[e])
        me = rho*np.einsum("qi,qj,q->ij", basis, basis, w[e])
        mhe = rho*np.einsum("qi,qj,q->ij", hi_basis, hi_basis, hi_w[e])
        dofs = (3*nodes[:, None]+np.arange(3)).ravel()
        kr.append(np.repeat(dofs, 30)); kc.append(np.tile(dofs, 30)); kv.append(ke.ravel())
        mr.append(np.repeat(nodes, 10)); mc.append(np.tile(nodes, 10))
        mv.append(me.ravel()); mhv.append(mhe.ravel())
    n = len(ids)
    k = coo_matrix((np.concatenate(kv), (np.concatenate(kr), np.concatenate(kc))),
                   shape=(3*n, 3*n)).tocsr()
    index = (np.concatenate(mr), np.concatenate(mc))
    m = coo_matrix((np.concatenate(mv), index), shape=(n, n)).tocsr()
    mh = coo_matrix((np.concatenate(mhv), index), shape=(n, n)).tocsr()
    return ids, xyz, k, kron(m, eye(3), format="csr"), kron(mh, eye(3), format="csr")


def audit(directory, material, mesh, parsed, *, free_body=False):
    ids, xyz, stiffness, mass, accurate_mass = matrices(directory, material)
    added=mesh[-1].get('attached_nodal_mass_kg',{})
    added_total=sum(added.values())
    if added:
        diagonal=diags(np.repeat([added.get(int(n),0.) for n in ids],3),format='csr')
        mass=mass+diagonal;accurate_mass=accurate_mass+diagonal
    pids, lam, frequencies, shapes = parsed
    if not np.array_equal(ids, pids):
        raise ValueError("Modal matrix and field nodes differ")
    u = shapes.reshape((len(lam), -1)).T
    if not np.isfinite(u).all() or np.any(np.linalg.norm(u, axis=0) == 0):
        raise ValueError("Eigenvectors must be finite and nonzero")
    fixed = np.array([3*int(np.searchsorted(ids, int(n)))+d-1
                      for n, ds in mesh[-1]["fixed_dofs"].items() for d in ds], dtype=int)
    free = np.setdiff1d(np.arange(3*len(ids)), fixed)
    ku, mu = stiffness@u, mass@u
    # Rounded DAT vectors can amplify residuals at high stiffness gradients.
    # Backward error is scaled by actual sparse operator norms, not clipped.
    knorm = float(np.max(np.abs(stiffness[free][:, free]).sum(axis=1)))
    mnorm = float(np.max(np.abs(mass[free][:, free]).sum(axis=1)))
    residuals = np.max(np.abs(ku[free]-mu[free]*lam), axis=0) / (
        (knorm+np.abs(lam)*mnorm)*np.max(np.abs(u[free]), axis=0))
    gram = u.T@mu
    modal_mass = np.diag(gram)
    if not np.isfinite(gram).all() or np.any(modal_mass <= 0):
        raise ValueError("Eigenvectors have invalid generalized mass")
    norm_error = float(np.max(np.abs(gram-np.eye(len(lam)))))
    rayleigh = np.sum(u*ku, axis=0)/modal_mass
    mass_error = np.abs(np.diag(u.T@(accurate_mass@u))/modal_mass-1)
    supports_ok = not len(fixed) or bool(np.max(np.abs(u[fixed])) <= 1e-10*np.max(np.abs(u)))
    r = xyz-xyz.mean(axis=0)
    r /= max(np.linalg.norm(np.ptp(xyz, axis=0)), 1e-15)
    rigid = np.zeros((len(ids), 3, 6))
    rigid[:, :, :3] = np.eye(3)
    for a in range(3):
        rigid[:, :, 3+a] = np.cross(np.eye(3)[a], r)
    rb = rigid.reshape((-1, 6))
    fit = rb@np.linalg.lstsq(rb, u, rcond=None)[0]
    rigid_fraction = np.linalg.norm(u-fit, axis=0)/np.linalg.norm(u, axis=0)
    rigid_modes = rigid_fraction <= 1e-4
    expected = 6 if free_body else 0
    rigid_ok = int(rigid_modes.sum()) == expected
    if expected:
        rigid_ok &= bool(np.all(rigid_modes[:6]) and len(lam) > 6
                         and np.linalg.matrix_rank(np.linalg.lstsq(rb, u[:, :6], rcond=None)[0]) == 6
                         and np.max(np.abs(lam[:6])) < 1e-6*lam[6])
    elastic = ~rigid_modes
    if np.any(lam[elastic] <= 0):
        raise ValueError("Nonpositive elastic eigenvalue is not an accepted rigid mode")
    rayleigh_error = np.abs(rayleigh[elastic]/lam[elastic]-1)
    total_mass = float(np.ones(len(ids)) @ (mass[::3, ::3]@np.ones(len(ids))))
    accurate_total_mass = float(np.ones(len(ids)) @ (accurate_mass[::3, ::3]@np.ones(len(ids))))
    expected_mass = mesh[-1]["mesh_volume_mm3"]*1e-9*material["density_kg_m3"]+added_total
    with np.load(Path(directory)/"mesh.npz", allow_pickle=False) as d:
        native_volume_mass = float(np.sum(d["native_volume_quadrature_measures_mm3"]))*1e-9*material["density_kg_m3"]+added_total
    total_quadrature_error = abs(total_mass/accurate_total_mass-1)
    checks = {
        "eigen_residual_passed": bool(np.all(residuals < 2e-6)),
        "mass_orthonormality_passed": norm_error < 2e-5,
        "rayleigh_passed": bool(np.all(rayleigh_error < 2e-4)),
        "mass_quadrature_passed": bool(np.all(mass_error < .005) and total_quadrature_error < .005),
        "support_values_passed": supports_ok,
        "rigid_modes_passed": bool(rigid_ok),
        "positive_elastic_modes_passed": bool(np.all(lam[elastic] > 0)),
        # Native ARPACK targets sigma=1 rad²/s². For this positive elastic
        # problem, reaching lambda>2 brackets all lower nonnegative modes;
        # a wholly sub-Hz returned window cannot establish lowest-mode coverage.
        "native_shift_coverage_passed": bool(lam[-1] > 2),
        # Assembly identity compares like quadrature with like. The separate
        # quadrature gate measures physical mass integration discrepancy.
        "total_mass_passed": (abs(total_mass/native_volume_mass-1) < 1e-8
                              and abs(accurate_total_mass/expected_mass-1) < 1e-8),
    }
    return {"passed": all(checks.values()), "checks": checks,
            "backward_errors": residuals.tolist(), "mass_orthonormality_error": norm_error,
            "elastic_rayleigh_relative_errors": rayleigh_error.tolist(),
            "modal_mass_quadrature_relative_errors": mass_error.tolist(),
            "rigid_shape_relative_residuals": rigid_fraction.tolist(),
            "rigid_mode_indices": np.flatnonzero(rigid_modes).tolist(),
            "total_mass_kg": total_mass, "geometric_mass_kg": expected_mass-added_total,
            "expected_total_mass_kg":expected_mass,
            "solid_mass_kg":expected_mass-added_total,"attached_mass_kg":added_total,
            "attached_mass_reports":mesh[-1].get('attached_mass_reports',[]),
            "higher_order_total_mass_kg": accurate_total_mass,
            "native_volume_mass_kg": native_volume_mass,
            "total_mass_quadrature_relative_error": total_quadrature_error,
            "constraints": rigid_diagnostics(mesh[0], mesh[-1]["fixed_dofs"]),
            "amplitude_meaning": "Mass-normalized eigenvector; not physical displacement."}
