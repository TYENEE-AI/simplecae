"""Mode/subspace correspondence; eigenvalue order alone is not convergence."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from scipy.optimize import linear_sum_assignment

from .loads import tetra10_basis
from .probes import PointSampler

FREQUENCY_TOLERANCE = .01
SUBSPACE_MAC_MIN = .95
CLUSTER_RELATIVE_GAP = .01


def match(fa, fb, a, b, weights):
    """Match sampled modes, retaining repeated eigenspaces as groups.

`a,b` have modes x samples x components; weights are positive volume measures.
Frequency criteria are unchanged for groups: compare their sorted spectra.
Within a degenerate space there is no unique individual physical eigenvector.
"""
    fa, fb, a, b, weights = [np.asarray(x, dtype=float) for x in (fa, fb, a, b, weights)]
    if (fa.ndim != 1 or fb.shape != fa.shape or a.shape != b.shape or a.ndim != 3
            or a.shape[0] != len(fa) or weights.shape != (a.shape[1],)
            or not all(np.isfinite(x).all() for x in (fa, fb, a, b, weights))
            or np.any(fa <= 0) or np.any(fb <= 0) or np.any(weights <= 0)):
        raise ValueError("Mode matching needs complete finite positive-frequency samples")
    av = (a*np.sqrt(weights)[None, :, None]).reshape((len(fa), -1)).T
    bv = (b*np.sqrt(weights)[None, :, None]).reshape((len(fa), -1)).T
    an, bn = np.linalg.norm(av, axis=0), np.linalg.norm(bv, axis=0)
    if np.any(an == 0) or np.any(bn == 0):
        raise ValueError("Zero mode cannot be matched")
    mac = ((av.T@bv)/an[:, None]/bn[None, :])**2
    i, j = linear_sum_assignment(-mac)
    mapping = dict(zip(map(int, i), map(int, j)))
    # Form connected near-degenerate groups in either discretization after
    # correspondence. No benchmark-specific mode numbers or polarizations.
    parent = list(range(len(fa)))
    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i
    for i in range(len(fa)):
        for j in range(i):
            if (abs(fa[i]-fa[j])/max(fa[i], fa[j]) <= CLUSTER_RELATIVE_GAP
                    or abs(fb[mapping[i]]-fb[mapping[j]])/
                    max(fb[mapping[i]], fb[mapping[j]]) <= CLUSTER_RELATIVE_GAP):
                parent[root(i)] = root(j)
    groups = {}
    for i in range(len(fa)):
        groups.setdefault(root(i), []).append(i)
    records = []
    for group in groups.values():
        other = [mapping[i] for i in group]
        aa, bb = av[:, group], bv[:, other]
        if np.linalg.matrix_rank(aa) != len(group) or np.linalg.matrix_rank(bb) != len(group):
            raise ValueError("Rank-deficient modal eigenspace")
        qa, qb = np.linalg.qr(aa)[0], np.linalg.qr(bb)[0]
        singular = np.linalg.svd(qa.T@qb, compute_uv=False)
        subspace_mac = float(np.min(singular)**2)
        errors = np.abs(np.sort(fa[group])/np.sort(fb[other])-1)
        records.append({"coarse_modes": group, "fine_modes": other,
                        "min_subspace_mac": subspace_mac,
                        "frequency_relative_errors": errors.tolist(),
                        "passed": bool(subspace_mac >= SUBSPACE_MAC_MIN
                                       and np.all(errors <= FREQUENCY_TOLERANCE)),
                        "individual_shape_meaning": "nonunique repeated/near-repeated eigenspace"
                        if len(group) > 1 else "matched individual eigenvector"})
    return {"passed": all(r["passed"] for r in records), "groups": records,
            "mapping": {str(k): v for k, v in mapping.items()}, "frequency_relative_tolerance": FREQUENCY_TOLERANCE,
            "min_subspace_mac": SUBSPACE_MAC_MIN, "cluster_relative_gap": CLUSTER_RELATIVE_GAP}


def compare_meshes(coarse_dir, fine_dir, coarse_fields, fine_fields, coarse_rigid=0, fine_rigid=0):
    """Use every native integration point of the coarser mesh, volume weighted.

Fine modes are evaluated through actual C3D10 isoparametric interpolation.
Unmapped points reject correspondence; no nearest-node snapping or dropping.
"""
    with np.load(Path(coarse_dir)/"mesh.npz", allow_pickle=False) as d:
        rows = {int(n): i for i, n in enumerate(d["node_ids"])}
        conn = np.array([[rows[int(n)] for n in ns] for ns in d["connectivity"]])
        xyz = d["xyz"]
        basis = tetra10_basis(d["native_volume_quadrature_points"])
        points = np.einsum("qi,eic->eqc", basis, xyz[conn]).reshape((-1, 3))
        weights = d["native_volume_quadrature_measures_mm3"].ravel()
        mode_rows = {int(n): i for i, n in enumerate(coarse_fields[0])}
        mode_conn = np.array([[mode_rows[int(n)] for n in ns] for ns in d["connectivity"]])
        a = np.einsum("qi,meic->meqc", basis,
                      coarse_fields[3][coarse_rigid:, mode_conn]).reshape(
                          (len(coarse_fields[2])-coarse_rigid, -1, 3))
    with np.load(Path(fine_dir)/"mesh.npz", allow_pickle=False) as d:
        sampler = PointSampler(dict(zip(map(int, d["node_ids"]), d["xyz"])),
                               dict(zip(map(int, d["element_ids"]), d["connectivity"])))
    mode_rows = {int(n): i for i, n in enumerate(fine_fields[0])}
    b = []
    for point in points:
        at = sampler.locate(point)
        nodes = [mode_rows[n] for n in at["node_ids"]]
        b.append(np.einsum("i,mic->mc", at["weights"], fine_fields[3][fine_rigid:, nodes]))
    b = np.stack(b, axis=1)
    return match(coarse_fields[2][coarse_rigid:], fine_fields[2][fine_rigid:], a, b, weights)
