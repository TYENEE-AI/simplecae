"""Fail closed on native mesher errors and retain high-order shape evidence."""
from pathlib import Path
import numpy as np


def native_mesh_call(g, stage, operation, directory):
    # Gmsh's default exception mode can throw inside an OpenMP region and
    # terminate the process before Python can retain an invalid result.
    # Mode 1 aborts the meshing operation; EVERY reported error is then
    # promoted to a Python error. It never accepts a failed optimization.
    previous=g.option.getNumber('General.AbortOnError')
    g.logger.start()
    try:
        g.option.setNumber('General.AbortOnError',1)
        try:
            value=operation()
        finally:
            messages=list(g.logger.get())
            with (Path(directory)/'mesh-native.log').open('a',encoding='utf8') as stream:
                stream.write(f'[{stage}]\n'+'\n'.join(messages)+'\n')
    finally:
        g.option.setNumber('General.AbortOnError',previous)
        g.logger.stop()
    errors=[m for m in messages if m.lstrip().startswith('Error')]
    if errors:
        raise RuntimeError(f'Gmsh {stage} failed; mesh rejected: '+'; '.join(errors))
    return value


def high_order_quality(g, element_ids):
    sicn=np.asarray(g.model.mesh.getElementQualities(element_ids,'minSICN'),float)
    determinant=np.asarray(g.model.mesh.getElementQualities(element_ids,'minDetJac'),float)
    if any(v.shape!=(len(element_ids),) or not np.all(np.isfinite(v)) for v in (sicn,determinant)):
        raise ValueError('incomplete or nonfinite high-order mesh quality')
    if np.min(determinant)<=0 or np.min(sicn)<=0:
        raise ValueError('nonpositive adaptively checked high-order Jacobian or signed shape quality')
    return sicn,determinant,{
        'minimum_signed_inverse_condition_number':float(sicn.min()),
        'minimum_adaptive_jacobian':float(determinant.min()),
        'elements_below_sicn_0_1':int((sicn<.1).sum()),
        'shape_warning_meaning':'SICN<0.1 is a diagnostic for distorted elements, not a stress allowable or a new convergence tolerance.',
        'jacobian_method':'Gmsh adaptive minDetJac, additional to existing integration-point checks'}


def rejected_high_order_mesh(g, info, h, directory):
    """Locate rejected elements and their CAD boundary faces, without repairing them."""
    from .case import write_json
    record = {
        "stage": "high_order_optimize", "mesh_size_mm": h,
        "geometry_sha256": info["geometry_sha256"],
        "status": "rejected",
        "next_action": "Inspect located curved CAD faces and use source-bound local_refinements "
                       "before whole-model refinement. Retain the original geometry, quality "
                       "gates and element/time budgets; no automatic retry or node projection.",
    }
    try:
        etype = g.model.mesh.getElementType("Tetrahedron", 2)
        ids, raw = g.model.mesh.getElementsByType(etype)
        conn = np.asarray(raw, dtype=int).reshape((-1, 10))
        det = np.asarray(g.model.mesh.getElementQualities(ids, "minDetJac"))
        sicn = np.asarray(g.model.mesh.getElementQualities(ids, "minSICN"))
        bad = ~np.isfinite(det) | ~np.isfinite(sicn) | (det <= 0) | (sicn <= 0)
        nodes, xyz, _ = g.model.mesh.getNodes()
        coords = dict(zip(map(int, nodes), np.asarray(xyz).reshape((-1, 3))))
        face_nodes = {}
        for face in info["faces"]:
            ns, _, _ = g.model.mesh.getNodes(2, face["id"], includeBoundary=True)
            face_nodes[face["id"]] = set(map(int, ns))
        records = []
        for i in np.flatnonzero(bad):
            corners = set(map(int, conn[i, :4]))
            records.append({
                "element": int(ids[i]),
                "corner_centroid_mm": np.mean([coords[n] for n in corners], axis=0).tolist(),
                "minimum_adaptive_jacobian": float(det[i]) if np.isfinite(det[i]) else None,
                "minimum_signed_inverse_condition_number": float(sicn[i]) if np.isfinite(sicn[i]) else None,
                "adjacent_face_ids": [f for f, ns in face_nodes.items() if len(corners & ns) >= 3],
            })
        located = {f for r in records for f in r["adjacent_face_ids"]}
        record.update(element_count=len(ids), rejected_element_count=len(records),
                      rejected_elements=records,
                      adjacent_cad_faces=[f for f in info["faces"] if f["id"] in located],
                      meaning="Boundary adjacency is a location cue, not proof of a CAD defect. "
                              "Optimizer failure remains fatal even when this list is empty.")
    except Exception as exc:
        # Diagnostics must not replace the original native failure.
        record["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
    write_json(Path(directory)/"mesh-diagnostic.json", record)
    return record


def element_quality(directory, element):
    path=Path(directory)/'mesh.npz'
    if not path.is_file():return None
    with np.load(path,allow_pickle=False) as data:
        if not {'element_min_sicn','element_min_det_jac','element_ids'}<=set(data.files):return None
        found=np.flatnonzero(data['element_ids']==element)
        if len(found)!=1:raise ValueError('peak element missing from mesh quality evidence')
        i=found[0]
        return {'minimum_signed_inverse_condition_number':float(data['element_min_sicn'][i]),
                'minimum_adaptive_jacobian':float(data['element_min_det_jac'][i])}
