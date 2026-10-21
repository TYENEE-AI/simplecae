"""Native solid heat-transfer primitives; not yet a qualified public analysis.

Geometry stays in mm for the shared mesher/Viewer. The native thermal deck uses
metres, watts, kilograms, seconds and Celsius throughout. Mechanical restraints
and elastic constants are neither invented nor required.
"""
from __future__ import annotations

from pathlib import Path
import re
import numpy as np

from .contact import surface_index
from .geometry import select_faces, integrate_tri6
from .solver import dat_real, native_real
from .loads import tetra10_basis


def tri6_mass(points, *, native=False):
    """Surface shape-product integral in m2, including curved quadratic faces."""
    quadrature = [(1/3, 1/3, .225)]
    for a, b, w in ((.059715871789770, .470142064105115, .132394152788506),
                    (.797426985353087, .101286507323456, .125939180544827)):
        quadrature.extend([(b, b, w), (a, b, w), (b, a, w)])
    if native:
        # Native quadratic-face thermal integration is the degree-2 rule.
        quadrature = [(1/6, 1/6, 1/3), (2/3, 1/6, 1/3), (1/6, 2/3, 1/3)]
    matrix = np.zeros((6, 6))
    for r, s, w in quadrature:
        l = 1-r-s
        n = np.array([l*(2*l-1), r*(2*r-1), s*(2*s-1), 4*l*r, 4*r*s, 4*s*l])
        dr = np.array([1-4*l, 4*r-1, 0, 4*(l-r), 4*s, -4*s])
        ds = np.array([1-4*l, 0, 4*s-1, -4*r, 4*r, 4*(l-s)])
        jac = np.linalg.norm(np.cross(dr @ points, ds @ points))
        if not np.isfinite(jac) or jac <= 0:
            raise ValueError("Degenerate thermal surface")
        matrix += .5*w*jac*np.outer(n, n)
    return matrix


def tetra10_gradient(points):
    p = np.asarray(points).reshape((-1, 3))
    bary = np.column_stack((1-p.sum(axis=1), p))
    db = np.vstack((-np.ones(3), np.eye(3)))
    rows = [(4*bary[:, i, None]-1)*db[i] for i in range(4)]
    rows += [4*(bary[:, a, None]*db[b] + bary[:, b, None]*db[a])
             for a, b in ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))]
    return np.stack(rows, axis=1)


def compile_boundaries(case, mesh, directory):
    coords, tets, _, _, meta = mesh
    index = surface_index(tets)
    with np.load(Path(directory) / "mesh.npz", allow_pickle=False) as data:
        triangles = data["surface_tri6"]
        faces = data["surface_face_ids"]
        patches = {}
        occupied = {}
        fixed = {}
        for spec in case["boundaries"]:
            name = spec["name"]
            if name in patches:
                raise ValueError("Thermal boundary names must be unique")
            selected = select_faces(meta["geometry"], spec["selector"])
            for face in selected:
                if face in occupied:
                    raise ValueError("Thermal boundary faces overlap; use one explicit boundary per face")
                occupied[face] = name
            patch = triangles[np.isin(faces, selected)]
            if not len(patch):
                raise ValueError("Thermal boundary has no surface elements")
            weights, elements, face_mass = {}, [], []
            for tri in patch:
                owners = index.get(tuple(sorted(map(int, tri[:3]))), [])
                if len(owners) != 1:
                    raise ValueError("Thermal boundary is not an external solid face")
                elements.append(owners[0])
                values, _, _ = integrate_tri6(np.array([coords[int(n)] for n in tri]) * .001)
                if spec["type"] == "convection":
                    face_mass.append((list(map(int, tri)), tri6_mass(
                        np.array([coords[int(n)] for n in tri]) * .001, native=True)))
                for n, w in zip(tri, values):
                    weights[int(n)] = weights.get(int(n), 0.) + float(w)
            if len(set(elements)) != len(elements):
                raise ValueError("Duplicate thermal boundary elements")
            if spec["type"] == "temperature":
                for n in weights:
                    if n in fixed and fixed[n] != spec["temperature_c"]:
                        raise ValueError("Conflicting prescribed temperatures on a shared edge/node")
                    fixed[n] = spec["temperature_c"]
            patches[name] = dict(spec, face_ids=selected, element_sides=elements,
                                 node_weights_m2=weights, area_m2=sum(weights.values()),
                                 face_mass_m2=face_mass)
    if case["mode"] == "steady" and not any(
            p["type"] in ("temperature", "convection") for p in patches.values()):
        raise ValueError("Steady conduction requires a temperature reference or convection heat path")
    return patches, fixed


def write_deck(case, mesh, patches, fixed, path, steps=None):
    """Constant boundary values apply as a step, without an unintended load ramp."""
    coords, tets, _, _, _ = mesh
    material = case["material"]
    lines = ["*HEADING", "SimpleCAE solid heat transfer; m kg s W degC", "*NODE,NSET=NALL"]
    lines += [f"{n}," + ",".join(native_real(float(x)*.001) for x in p)
              for n, p in sorted(coords.items())]
    lines += ["*ELEMENT,TYPE=C3D10,ELSET=EALL"]
    lines += [f"{e}," + ",".join(map(str, ns)) for e, ns in sorted(tets.items())]
    lines += ["*MATERIAL,NAME=BODY", "*CONDUCTIVITY", native_real(material["conductivity_w_mk"]),
              "*SOLID SECTION,ELSET=EALL,MATERIAL=BODY"]
    if case["mode"] == "transient":
        lines += ["*DENSITY", native_real(material["density_kg_m3"]),
                  "*SPECIFIC HEAT", native_real(material["specific_heat_j_kgk"]),
                  "*INITIAL CONDITIONS,TYPE=TEMPERATURE", f"NALL,{native_real(case['initial_temperature_c'])}"]
    if fixed:
        lines += ["*BOUNDARY"] + [f"{n},11,11,{native_real(v)}" for n, v in sorted(fixed.items())]
    lines += ["*STEP,INC=100000"]
    if case["mode"] == "steady":
        lines += ["*HEAT TRANSFER,STEADY STATE,SOLVER=SPOOLES", "1.,1."]
    else:
        if type(steps) is not int or steps <= 0:
            raise ValueError("Transient native steps must be a positive integer")
        duration = case["duration_s"]
        lines += ["*HEAT TRANSFER,DIRECT,SOLVER=SPOOLES",
                  f"{native_real(duration/steps)},{native_real(duration)}"]
    fluxes = [f"{e},S{s},{native_real(p['flux_w_m2'])}" for p in patches.values()
              if p["type"] == "heat_flux" for e, s in p["element_sides"]]
    if case.get("volumetric_heat_w_m3", 0):
        fluxes += [f"EALL,BF,{native_real(case['volumetric_heat_w_m3'])}"]
    if fluxes:
        lines += ["*DFLUX", *fluxes]
    films = [f"{e},F{s},{native_real(p['ambient_temperature_c'])},{native_real(p['coefficient_w_m2k'])}"
             for p in patches.values() if p["type"] == "convection"
             for e, s in p["element_sides"]]
    if films:
        lines += ["*FILM", *films]
    lines += ["*NODE PRINT,NSET=NALL,FREQUENCY=1", "NT,RFL",
              "*EL PRINT,ELSET=EALL,FREQUENCY=1", "HFL",
              "*NODE FILE,FREQUENCY=1", "NT", "*END STEP"]
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")


def parse_fields(path, node_ids, element_ids, expected_times):
    """Require complete unrounded-time coverage; truncated/duplicate data fails."""
    frames = {}
    section = None
    stamp = None
    patterns = (("temperatures", "temperature_c", 2),
                ("heat flux", "flux_w_m2", 5), ("heat generation", "rfl_w", 2))
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        low = line.strip().lower()
        found = next(((key, width) for prefix, key, width in patterns if low.startswith(prefix)), None)
        if found:
            match = re.search(r"\btime\s+(\S+)", low)
            if not match:
                raise ValueError("Thermal field lacks time stamp")
            stamp = dat_real(match[1])
            section, width = found
            frame = frames.setdefault(stamp, {})
            if section in frame:
                raise ValueError("Duplicate thermal field section")
            frame[section] = {}
        elif low and low[0].isalpha():
            section = None
        elif section and low:
            parts = low.split()
            if len(parts) != width:
                raise ValueError("Malformed thermal field row")
            values = [dat_real(x) for x in parts]
            if not np.isfinite(values).all():
                raise ValueError("Non-finite thermal field")
            key = (int(values[0]), int(values[1])) if width == 5 else int(values[0])
            value = values[2:] if width == 5 else values[1]
            if key in frames[stamp][section]:
                raise ValueError("Duplicate thermal field sample")
            frames[stamp][section][key] = value
    times = sorted(frames)
    if len(times) != len(expected_times) or not np.allclose(
            times, expected_times, rtol=2e-6, atol=1e-10):
        raise ValueError("Thermal solver has missing/unexpected time increments")
    expected_ips = {(e, ip) for e in element_ids for ip in (1, 2, 3, 4)}
    for frame in frames.values():
        if (set(frame) != {"temperature_c", "rfl_w", "flux_w_m2"}
                or set(frame["temperature_c"]) != set(node_ids)
                or set(frame["rfl_w"]) != set(node_ids)
                or set(frame["flux_w_m2"]) != expected_ips):
            raise ValueError("Incomplete thermal field coverage")
    return [(float(t), frames[t]) for t in times]


def integration_data(directory):
    """Consistent volume integrals from the actual curved quadratic geometry."""
    from scipy.sparse import coo_matrix
    with np.load(Path(directory) / "mesh.npz", allow_pickle=False) as d:
        ids = d["node_ids"].copy()
        lookup = {int(n): i for i, n in enumerate(ids)}
        conn = np.array([[lookup[int(n)] for n in row] for row in d["connectivity"]])
        basis = tetra10_basis(d["volume_quadrature_points"])
        measure = d["volume_quadrature_measures_mm3"] * 1e-9
        weights = np.zeros(len(ids))
        np.add.at(weights, conn.ravel(), (measure @ basis).ravel())
        native_basis = tetra10_basis(d["native_volume_quadrature_points"])
        native_measure = d["native_volume_quadrature_measures_mm3"] * 1e-9
        native_weights = np.zeros(len(ids))
        np.add.at(native_weights, conn.ravel(), (native_measure @ native_basis).ravel())
        matrices = np.einsum("eq,qi,qj->eij", native_measure, native_basis, native_basis)
        rows = np.broadcast_to(conn[:, :, None], matrices.shape).ravel()
        cols = np.broadcast_to(conn[:, None, :], matrices.shape).ravel()
        mass = coo_matrix((matrices.ravel(), (rows, cols)), shape=(len(ids), len(ids))).tocsr()
        derivative = tetra10_gradient(d["native_volume_quadrature_points"])
        xyz = d["xyz"][conn]*.001
        jac = np.einsum("eia,qib->eqab", xyz, derivative)
        if np.any(np.linalg.det(jac) <= 0):
            raise ValueError("Thermal integration has a nonpositive Jacobian")
        gradient = np.einsum("qib,eqba->eqia", derivative, np.linalg.inv(jac))
        matrices = np.einsum("eq,eqia,eqja->eij", native_measure, gradient, gradient)
        conductance = coo_matrix((matrices.ravel(), (rows, cols)), shape=(len(ids), len(ids))).tocsr()
    return ids, lookup, weights, native_weights, mass, conductance


def energy_history(case, patches, fixed, frames, directory):
    """Audit nodal heat balance; RFL alone is not a reservoir reaction.

    Native RFL is the conductive nodal contribution. Subtract distributed input
    and add consistent transient storage before interpreting prescribed-node
    reactions. Independently verify every free node, not only a cancelling sum.
    """
    ids, lookup, weights, native_weights, mass, conductance = integration_data(directory)
    fixed_rows = [lookup[n] for n in fixed]
    free_rows = [lookup[int(n)] for n in ids if int(n) not in fixed]
    previous = np.full(len(ids), case.get("initial_temperature_c", 0.))
    # Initial conditions and Dirichlet constraints coexist in the initial state.
    for n, v in fixed.items():
        previous[lookup[n]] = v
    previous_time = 0.
    ledger = []
    for time, fields in frames:
        temperature = np.array([fields["temperature_c"][int(n)] for n in ids])
        conductive = np.array([fields["rfl_w"][int(n)] for n in ids])
        reconstructed = case["material"]["conductivity_w_mk"]*(conductance @ temperature)
        body = native_weights * case.get("volumetric_heat_w_m3", 0.)
        applied = body.copy()
        surface = {}
        for name, p in patches.items():
            q = np.zeros(len(ids))
            if p["type"] == "heat_flux":
                for n, w in p["node_weights_m2"].items():
                    q[lookup[n]] += w*p["flux_w_m2"]
            elif p["type"] == "convection":
                for nodes, matrix in p["face_mass_m2"]:
                    ii = [lookup[n] for n in nodes]
                    values = p["coefficient_w_m2k"] * (
                        matrix @ (p["ambient_temperature_c"] - temperature[ii]))
                    np.add.at(q, ii, values)
            surface[name] = float(q.sum())
            applied += q
        storage = np.zeros(len(ids))
        if case["mode"] == "transient":
            rate = (temperature-previous)/(time-previous_time)
            m = case["material"]
            storage = m["density_kg_m3"]*m["specific_heat_j_kgk"]*(mass @ rate)
        residual = conductive + storage - applied
        reaction = float(residual[fixed_rows].sum())
        error = float(applied.sum() + reaction - storage.sum())
        ledger.append({"time_s": time, "body_input_w": float(body.sum()),
                       "surface_input_w": surface, "reservoir_input_w": reaction,
                       "reservoir_exchange_scale_w": float(np.abs(residual[fixed_rows]).sum()),
                       "storage_rate_w": float(storage.sum()), "balance_error_w": error,
                       "max_free_node_residual_w": float(np.max(np.abs(residual[free_rows])))
                       if free_rows else 0.,
                       "max_conductive_field_residual_w": float(
                           np.max(np.abs(reconstructed-conductive))),
                       "independent_volume_integration_difference_m3": float(
                           np.sum(np.abs(weights-native_weights))),
                       "stored_energy_relative_zero_c_j": float(
                           case["material"].get("density_kg_m3", 0.)
                           * case["material"].get("specific_heat_j_kgk", 0.)
                           * (weights @ temperature))})
        previous, previous_time = temperature, time
    return ledger
