"""Quadratic temperature extrema, including peaks between finite-element nodes."""
from itertools import combinations
import numpy as np


def simplex_extrema(values, xyz):
    """Exact stationary candidates on every subsimplex of a P2 triangle/tet.

    Temperature is quadratic in natural coordinates even on a curved element.
    A singular stationary set reaches a lower-dimensional face; those faces and
    vertices are enumerated too. This avoids treating nodal maxima as hotspots.
    """
    values, xyz = np.asarray(values, dtype=float), np.asarray(xyz, dtype=float)
    if values.ndim != 2 or values.shape[1] not in (6, 10) or xyz.shape != (*values.shape, 3):
        raise ValueError("Expected quadratic triangle/tetrahedron fields and geometry")
    if not np.isfinite(values).all() or not np.isfinite(xyz).all():
        raise ValueError("Nonfinite quadratic temperature field")
    nv = 3 if values.shape[1] == 6 else 4
    edges = ((0, 1), (1, 2), (2, 0)) if nv == 3 else (
        (0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))
    a = np.zeros((len(values), nv, nv))
    for i in range(nv):
        a[:, i, i] = values[:, i]
    for j, (u, v) in enumerate(edges):
        a[:, u, v] = a[:, v, u] = 2*values[:, nv+j]-.5*(values[:, u]+values[:, v])
    offset = values[:, 0]
    scaled = a-offset[:, None, None]
    scale = np.maximum(np.max(np.abs(scaled), axis=(1, 2)), 1.)
    scaled /= scale[:, None, None]
    low, high = values[:, 0].copy(), values[:, 0].copy()
    low_bary = np.zeros((len(values), nv))
    low_bary[:, 0] = 1
    high_bary = low_bary.copy()
    for size in range(1, nv+1):
        for subset in combinations(range(nv), size):
            bary = np.zeros((len(values), nv))
            valid = np.ones(len(values), dtype=bool)
            if size == 1:
                bary[:, subset[0]] = 1
            else:
                system = np.zeros((len(values), size+1, size+1))
                system[:, :size, :size] = 2*scaled[:, subset, :][:, :, subset]
                system[:, size, :size] = system[:, :size, size] = 1
                rhs = np.zeros(size+1)
                rhs[-1] = 1
                solution = (np.linalg.pinv(system, rcond=1e-13) @ rhs)[:, :size]
                residual = 2*np.einsum("eij,ej->ei", scaled[:, subset, :][:, :, subset], solution)
                valid = ((solution.min(axis=1) >= -1e-11)
                         & (np.abs(solution.sum(axis=1)-1) < 1e-10)
                         & (np.ptp(residual, axis=1) < 1e-9))
                solution = np.maximum(solution, 0)
                solution /= np.maximum(solution.sum(axis=1, keepdims=True), 1e-300)
                bary[:, subset] = solution
            t = offset + scale*np.einsum("ei,eij,ej->e", bary, scaled, bary)
            take = valid & (t < low)
            low[take], low_bary[take] = t[take], bary[take]
            take = valid & (t > high)
            high[take], high_bary[take] = t[take], bary[take]
    def positions(bary):
        shape = np.column_stack([bary[:, i]*(2*bary[:, i]-1) for i in range(nv)]
                                + [4*bary[:, i]*bary[:, j] for i, j in edges])
        return np.einsum("ei,eia->ea", shape, xyz)
    return low, high, positions(low_bary), positions(high_bary)


def region_history(temperature, connectivity, xyz, element_ids, times):
    """Keep all time extrema and their locations; do not subsample acceptance."""
    rows = []
    for time, nodal in zip(times, temperature):
        low, high, low_xyz, high_xyz = simplex_extrema(nodal[connectivity], xyz[connectivity])
        imin, imax = int(low.argmin()), int(high.argmax())
        rows.append({"time_s": float(time), "min_temperature_c": float(low[imin]),
                     "max_temperature_c": float(high[imax]), "min_location_mm": low_xyz[imin].tolist(),
                     "max_location_mm": high_xyz[imax].tolist(),
                     "min_element": int(element_ids[imin]), "max_element": int(element_ids[imax])})
    return rows
