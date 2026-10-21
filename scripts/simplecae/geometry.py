"""Import one STEP solid; select full CAD faces; create quadratic tetrahedra."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from .defaults import DEFAULT_STRUCTURAL_ELEMENTS
import numpy as np

from .case import sha256, write_json
from .loads import distribute_wrench, integrate_gravity


@contextmanager
def session(step: Path | None = None, model=None):
    import gmsh
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        gmsh.model.add("simplecae")
        gmsh._simplecae_source=None
        gmsh._simplecae_solid_id=None
        if step is not None:
            if step.suffix.lower() in ('.step','.stp'):
                gmsh.model.occ.importShapes(str(step))
                gmsh.model.occ.synchronize()
                if model and model.get('solid_id'):
                    spec=model['solid_id']
                    if spec['geometry_sha256']!=sha256(step):raise ValueError('solid_id belongs to a different STEP hash; inspect again')
                    available=gmsh.model.getEntities(3);selected=(3,spec['id'])
                    if selected not in available:raise ValueError('STEP solid_id does not exist')
                    gmsh._simplecae_solid_id=spec['id']
                    if len(available)>1:
                        isolated=gmsh.model.occ.copy([selected])
                        gmsh.model.occ.remove(available,recursive=True)
                        gmsh.model.occ.synchronize()
            else:
                from .mesh_input import import_surface
                gmsh._simplecae_source=import_surface(gmsh,model or {'path':str(step)})
        yield gmsh
    finally:
        gmsh.finalize()


def inventory(g, step: Path):
    if getattr(g,'_simplecae_source',None):
        from .mesh_input import surface_inventory
        return surface_inventory(g,step,g._simplecae_source)
    volumes = g.model.getEntities(3)
    if len(volumes) != 1:
        raise ValueError(f"Single-solid analysis requires exactly one CAD volume; found {len(volumes)}. "
                         "Use inspect --all-bodies, then select a source-bound model.solid_id / inspect --solid-id; "
                         "for a load-transferring assembly use assembly-1.0 with explicit supported connections. No implicit fusion or contact is inferred.")
    boundary = g.model.getBoundary(volumes, oriented=False)
    surfaces = sorted(t for d, t in boundary if d == 2)
    if set(surfaces) != {t for d, t in g.model.getEntities(2)}:
        raise ValueError("STEP contains loose surfaces in addition to the solid")
    volume = float(g.model.occ.getMass(3, volumes[0][1]))
    if not np.isfinite(volume) or volume <= 0:
        raise ValueError("STEP solid volume is not positive")
    bb = list(g.model.getBoundingBox(3, volumes[0][1]))
    return {
        "geometry_sha256": sha256(step), "source_step": str(step.resolve()), "units": "mm",
        "gmsh_version": g.__version__, "solid_count": 1, "volume_mm3": volume,
        "source_solid_id":getattr(g,'_simplecae_solid_id',None),
        "center_of_mass_mm": list(g.model.occ.getCenterOfMass(3,volumes[0][1])),
        "bbox_mm": [bb[:3], bb[3:]], "faces": [
            {"id": t, "type": g.model.getType(2, t), "area_mm2": g.model.occ.getMass(2, t),
             "centroid_mm": list(g.model.occ.getCenterOfMass(2, t)),
             "bbox_mm": list(g.model.getBoundingBox(2, t))} for t in surfaces
        ],
    }


def inspect(step: Path, out: Path, model=None,*,analytic_axes=False):
    if step.suffix.lower() not in (".step", ".stp", ".glb", ".stl", ".obj") or not step.is_file():
        raise ValueError("inspect accepts an existing STEP, GLB, STL or OBJ file")
    with session(step,model) as g:
        result = inventory(g, step)
        if model and model.get('interface_manifest'):
            from .bridge import resolve_interfaces
            result['interfaces']=resolve_interfaces(model['interface_manifest'],result)
        if analytic_axes:
            if step.suffix.lower() not in ('.step','.stp'):raise ValueError('analytic cylinder inspection requires native STEP/STP')
            from .interface_check import cylinder_axis
            for face in result['faces']:
                if face['type'].lower()=='cylinder':
                    try:face['analytic_cylinder']=cylinder_axis(g,face['id'])
                    except ValueError as exc:face['analytic_axis_error']=str(exc)
    write_json(out, result)
    return result


def inspect_bodies(path,out,model=None):
    model=model or {'path':str(path)}
    if path.suffix.lower() in ('.step','.stp'):
        with session(path) as g:
            bodies=[{'solid_id':tag,'name':g.model.getEntityName(3,tag),'volume_mm3':g.model.occ.getMass(3,tag),
                     'center_of_mass_mm':list(g.model.occ.getCenterOfMass(3,tag)),
                     'bbox_mm':list(g.model.getBoundingBox(3,tag))} for _,tag in g.model.getEntities(3)]
        result={'geometry_sha256':sha256(path),'source_model':str(path.resolve()),'units':'mm','bodies':bodies}
    else:
        import trimesh
        from .mesh_input import load_surface
        scene=trimesh.load_scene(path,process=False,skip_materials=True);bodies=[]
        for node in scene.graph.nodes_geometry:
            selected=dict(model,scene_node=str(node))
            try:
                _,record=load_surface(selected);bodies.append({'scene_node':str(node),'status':'closed_solid',**record})
            except ValueError as exc:bodies.append({'scene_node':str(node),'status':'not_a_supported_solid','reason':str(exc)})
        result={'geometry_sha256':sha256(path),'source_model':str(path.resolve()),'units':'mm','bodies':bodies}
    write_json(out,result);return result


def select_faces(info, spec):
    if spec['type']=='interface':
        available=info.get('interfaces',{}).get('regions',{})
        if spec['name'] not in available:
            raise ValueError(f"interface {spec['name']} is unavailable; provide a current native interface manifest")
        selected=available[spec['name']]
    elif spec["type"] == "face_ids":
        if spec["geometry_sha256"] != info["geometry_sha256"]:
            raise ValueError("face IDs belong to a different geometry hash; inspect again")
        available = {f["id"] for f in info["faces"]}
        if not set(spec["ids"]).issubset(available):
            raise ValueError("selector contains nonexistent face IDs")
        selected = spec["ids"]
    else:
        axis = "xyz".index(spec["axis"])
        position, tol = spec["position_mm"], spec.get("tolerance_mm", 1e-4)
        selected = [f["id"] for f in info["faces"] if f["type"] == "Plane"
                    and abs(f["bbox_mm"][axis] - position) <= tol
                    and abs(f["bbox_mm"][axis + 3] - position) <= tol]
    if not selected:
        raise ValueError("selector matched no full CAD face; inspect the face inventory")
    return sorted(selected)


def edge_permutation(local_coords, dimension, corners, edges):
    """Derive midside ordering from Gmsh reference coordinates, not file-format guesses."""
    xyz = np.asarray(local_coords).reshape((-1, dimension))
    order = list(range(corners))
    for a, b in edges:
        mid = (xyz[a] + xyz[b]) / 2
        match = np.flatnonzero(np.linalg.norm(xyz - mid, axis=1) < 1e-10)
        if len(match) != 1:
            raise ValueError("unsupported element reference topology")
        order.append(int(match[0]))
    return order


def integrate_tri6(points):
    """Consistent vector-traction shape integrals, area and first moment on a curved tri6."""
    quadrature = [(1/3, 1/3, .225)]
    for a, b, w in ((.059715871789770, .470142064105115, .132394152788506),
                    (.797426985353087, .101286507323456, .125939180544827)):
        quadrature.extend([(b, b, w), (a, b, w), (b, a, w)])
    weights = np.zeros(6)
    first_moment = np.zeros(3)
    for r, s, w in quadrature:
        l = 1-r-s
        n = np.array([l*(2*l-1), r*(2*r-1), s*(2*s-1), 4*l*r, 4*r*s, 4*s*l])
        dr = np.array([1-4*l, 4*r-1, 0, 4*(l-r), 4*s, -4*s])
        ds = np.array([1-4*l, 0, 4*s-1, -4*r, 4*r, 4*(l-s)])
        jac = np.linalg.norm(np.cross(dr @ points, ds @ points))
        if not np.isfinite(jac) or jac <= 0:
            raise ValueError("degenerate surface element")
        measure = .5*w*jac
        weights += measure*n
        first_moment += measure*(n @ points)
    return weights, float(weights.sum()), first_moment


def make_mesh(c, h, out: Path, allow_free_body=False, load_to_support_axes=None):
    thermal = c.get("schema_version") == "thermal-solid-1.0"
    modal = c.get("schema_version") == "modal-solid-1.0"
    if thermal:
        allow_free_body = True  # Thermal fields have no mechanical restraint DOFs.
    supports = [] if thermal else c["supports"]
    loads = [] if thermal or modal else c["loads"]
    step = Path(c["model"]["path"])
    with session(step,c['model']) as g:
        info = inventory(g, step)
        if c['model'].get('interface_manifest'):
            from .bridge import resolve_interfaces
            info['interfaces']=resolve_interfaces(c['model']['interface_manifest'],info)
        expected = c["model"].get("expected_bbox_mm")
        if expected is not None and not np.allclose(info["bbox_mm"], expected, rtol=0, atol=1e-3):
            raise ValueError("imported mm bounding box does not match expected dimensions")
        support_faces = {} if c.get('reference_only') else {s["name"]: select_faces(info, s["selector"]) for s in supports}
        load_faces = {s["name"]: select_faces(info, s["selector"]) for s in loads}
        support_union = {f for fs in support_faces.values() for f in fs}
        load_union = {f for fs in load_faces.values() for f in fs}
        from .constraints import support_dofs,check_shared_face_load
        face_dofs={}
        for spec in supports:
            for face in support_faces.get(spec['name'],[]):
                face_dofs.setdefault(face,set()).update(support_dofs(spec))
        if any(len(face_dofs[face])==3 for face in support_union & load_union):
            raise ValueError("a fully constrained CAD face cannot be both a support and a load")
        all_load_faces = [f for fs in load_faces.values() for f in fs]
        if len(all_load_faces) != len(set(all_load_faces)) and c.get("schema_version") != "2.0":
            raise ValueError("load regions overlap; combine forces explicitly")
        g.option.setNumber("Mesh.MeshSizeMin", h)
        g.option.setNumber("Mesh.MeshSizeMax", h)
        from .local_mesh import configure
        refinements=configure(g,info,c['mesh'],h)
        g.option.setNumber("Mesh.Algorithm3D", 1)
        g.option.setNumber("Mesh.RandomSeed", 1)
        # createGeometry stores discrete charts based on the imported mesh.
        # generate(3) remeshes their curves/surfaces to the requested size;
        # clearing all mesh first invalidates charts in the Windows build.
        from .mesh_diagnostics import native_mesh_call,high_order_quality
        native_mesh_call(g,'generate',lambda:g.model.mesh.generate(3),out)
        # Elevating order and untangling a mesh cannot reduce its element count.
        # Enforce the caller's budget before those expensive native operations.
        linear_count = sum(len(tags) for tags in g.model.mesh.getElements(3)[1])
        limit = c['mesh'].get('max_elements', DEFAULT_STRUCTURAL_ELEMENTS)
        if linear_count > limit:
            write_json(out/'mesh-diagnostic.json', {
                'stage': 'element_budget', 'status': 'rejected', 'mesh_size_mm': h,
                'geometry_sha256': info['geometry_sha256'],
                'element_count': linear_count, 'max_elements': limit,
                'next_action': 'Review local mesh allocation or explicitly increase the resource budget; '
                               'no order elevation, optimization or solve was started.'})
            raise ValueError(f'mesh exceeds max_elements: {linear_count} > {limit}; '
                             'review local sizing or increase the explicit budget')
        native_mesh_call(g,'set_order',lambda:g.model.mesh.setOrder(2),out)
        # Opt-in Gmsh constraint: retain CAD-projected boundary nodes while
        # optimizing the interior. Never flatten a curved face or move nodes
        # after meshing. All native error/Jacobian/convergence gates still apply.
        g.option.setNumber('Mesh.HighOrderFixBoundaryNodes',1 if c['mesh'].get('preserve_boundary_nodes',False) else 0)
        try:
            native_mesh_call(g,'high_order_optimize',lambda:g.model.mesh.optimize("HighOrder"),out)
        except Exception as original:
            from .mesh_diagnostics import rejected_high_order_mesh
            try:
                rejected_high_order_mesh(g, info, h, out)
            except Exception as diagnostic_error:
                original.add_note(f"Mesh diagnostic could not be written: {diagnostic_error}")
            raise
        types = set(map(int, g.model.mesh.getElementTypes(3)))
        etype = g.model.mesh.getElementType("Tetrahedron", 2)
        if types != {etype}:
            raise ValueError("mesh must consist entirely of quadratic tetrahedra")
        ids, xyz, _ = g.model.mesh.getNodes()
        coords = {int(n): np.array(p) for n, p in zip(ids, np.asarray(xyz).reshape((-1, 3)))}
        eid, raw = g.model.mesh.getElementsByType(etype)
        if len(eid) > c["mesh"].get("max_elements", DEFAULT_STRUCTURAL_ELEMENTS):
            raise ValueError("mesh exceeds max_elements; coarsen or increase the explicit budget")
        sicn,adaptive_jacobian,quality=high_order_quality(g,eid)
        _, _, _, _, local, _ = g.model.mesh.getElementProperties(etype)
        perm = edge_permutation(local, 3, 4, [(0,1),(1,2),(2,0),(0,3),(1,3),(2,3)])
        conn = np.asarray(raw, dtype=int).reshape((-1, 10))[:, perm]
        tets = {int(e): nodes.tolist() for e, nodes in zip(eid, conn)}
        connected_nodes = set(int(n) for n in conn.flat)
        if connected_nodes != set(coords):
            raise ValueError("mesh contains nodes disconnected from the solid")
        ip, iw = g.model.mesh.getIntegrationPoints(etype, "Gauss4")
        _, det, _ = g.model.mesh.getJacobians(etype, ip)
        det = np.asarray(det).reshape((-1, len(iw)))
        if not len(tets) or not np.all(np.isfinite(det)) or np.min(det) <= 0:
            raise ValueError("nonpositive sampled element Jacobian")
        mesh_volume = float(np.sum(det @ np.asarray(iw)))
        volume_error = abs(mesh_volume / info["volume_mm3"] - 1)
        if volume_error > .02:
            raise ValueError(f"mesh volume differs from CAD by {volume_error:.1%}")
        from .constraints import support_dofs,check_rigid_modes
        fixed_dofs={}
        for spec in ([] if c.get('reference_only') else supports):
            for f in support_faces[spec['name']]:
                nodes,_,_=g.model.mesh.getNodes(2,f,includeBoundary=True)
                for n in nodes:fixed_dofs.setdefault(int(n),set()).update(support_dofs(spec))
        fixed=set(fixed_dofs)
        reference=None
        if c.get('reference_only'):
            from .reference_support import prepare
            reference=prepare(c,coords,tets,info['geometry_sha256'])
            fixed=set(reference['reaction_nodes'])
        elif not allow_free_body:check_rigid_modes(coords,fixed_dofs)
        stype = g.model.mesh.getElementType("Triangle", 2)
        _, _, dim, _, slocal, _ = g.model.mesh.getElementProperties(stype)
        sperm = edge_permutation(slocal, dim, 3, [(0,1),(1,2),(2,0)])
        surfaces, load_reports, forces, fixed_forces = {}, [], {}, {}
        for f in [face["id"] for face in info["faces"]]:
            _, raw = g.model.mesh.getElementsByType(stype, f)
            surfaces[f] = np.asarray(raw, dtype=int).reshape((-1, 6))[:, sperm].tolist()
        from .local_mesh import measure_surfaces
        refinements=measure_surfaces(refinements,surfaces,coords)
        for spec in loads:
            integrals, area, first = {}, 0., np.zeros(3)
            for f in load_faces[spec["name"]]:
                for tri in surfaces[f]:
                    weights, a, moment = integrate_tri6(np.array([coords[n] for n in tri]))
                    area += a
                    first += moment
                    for n, w in zip(tri, weights):
                        integrals[n] = integrals.get(n, 0.) + float(w)
            if area <= 0:
                raise ValueError("load area must be positive")
            force = np.array(spec["total_force_n"], dtype=float)
            applied, center, couple = distribute_wrench(coords, integrals, force,
                spec.get("total_moment_n_mm", [0.,0.,0.]), spec.get("application_point_mm"))
            shared_faces=set(load_faces[spec['name']]) & support_union
            if shared_faces:
                shared_nodes={n for face in shared_faces for tri in surfaces[face] for n in tri}
                check_shared_face_load(applied,fixed_dofs,shared_nodes,load_to_support_axes)
            for n, f in applied.items():
                forces[n] = forces.get(n, np.zeros(3)) + f
                if not spec.get("scalable", True):
                    fixed_forces[n] = fixed_forces.get(n, np.zeros(3)) + f
            load_reports.append({"name": spec["name"], "face_ids": load_faces[spec["name"]],
                                 "area_mm2": area, "centroid_mm": (first/area).tolist(),
                                 "total_force_n": force.tolist(), "traction_mpa": (force/area).tolist(),
                                 "total_moment_n_mm_about_patch_centroid": couple.tolist(), "scalable": spec.get("scalable",True)})
        gravity_mass = None
        if c.get("gravity"):
            gravity = integrate_gravity(conn,det,ip,iw,c["material"]["density_kg_m3"],c["gravity"]["acceleration_m_s2"])
            for n,f in gravity.items():
                forces[n] = forces.get(n,np.zeros(3)) + f
                fixed_forces[n] = fixed_forces.get(n,np.zeros(3)) + f
            gravity_mass = mesh_volume*c["material"]["density_kg_m3"]*1e-9
        total_force = sum(forces.values(),np.zeros(3))
        total_moment = sum((np.cross(coords[n], f) for n, f in forces.items()),np.zeros(3))
        g.write(str(out / "mesh.msh"))
        if step.suffix.lower() in ('.step','.stp') and allow_free_body:
            g.write(str(out/'geometry.brep'))
        nodepath = out / "mesh.npz"
        thermal_quadrature = ({"volume_quadrature_points": np.asarray(ip).reshape((-1, 3)),
                               "volume_quadrature_measures_mm3": det*np.asarray(iw)}
                              if thermal or modal else {})
        if thermal or modal:
            # CalculiX C3D10 thermal matrices use the four-point degree-2
            # tetrahedral rule. Keep it alongside higher-order volume evidence.
            native_ip, native_iw = g.model.mesh.getIntegrationPoints(etype, "Gauss2")
            _, native_det, _ = g.model.mesh.getJacobians(etype, native_ip)
            thermal_quadrature.update(
                native_volume_quadrature_points=np.asarray(native_ip).reshape((-1, 3)),
                native_volume_quadrature_measures_mm3=np.asarray(native_det).reshape(
                    (-1, len(native_iw)))*np.asarray(native_iw))
        np.savez_compressed(nodepath, node_ids=np.array(list(coords)), xyz=np.array(list(coords.values())),
                            element_ids=np.array(list(tets)), connectivity=conn,
                            surface_tri6=np.array([tri for ts in surfaces.values() for tri in ts]),
                            surface_face_ids=np.array([f for f, ts in surfaces.items() for _ in ts]),
                            element_min_sicn=sicn,element_min_det_jac=adaptive_jacobian,
                            **thermal_quadrature)
        report = {"geometry": info, "mesh_size_mm": h, "node_count": len(coords), "element_count": len(tets),
                  "boundary_nodes_preserved_during_high_order_optimization":c['mesh'].get('preserve_boundary_nodes',False),
                  "local_refinements":refinements,
                  "high_order_quality":quality,
                  "element_type": "C3D10", "gmsh_to_calculix_permutation": perm,
                  "min_sampled_jacobian": float(np.min(det)), "mesh_volume_mm3": mesh_volume,
                  "cad_mesh_volume_relative_error": volume_error,
                  "support_faces": support_faces, "fixed_node_count":0 if reference else len(fixed),
                  "fixed_dofs":{str(n):sorted(ds) for n,ds in fixed_dofs.items()},"loads": load_reports,
                  "applied_force_n": total_force.tolist(), "applied_moment_n_mm": total_moment.tolist(),
                  "load_force_scale_n": float(sum(np.linalg.norm(s["total_force_n"]) + np.linalg.norm(s.get("total_moment_n_mm",[0,0,0]))/max(np.linalg.norm(np.ptp(np.array(list(coords.values())),axis=0)),1e-12) for s in loads)
                      + (gravity_mass*np.linalg.norm(c["gravity"]["acceleration_m_s2"]) if gravity_mass else 0.)),
                  "mass_kg": gravity_mass,
                  "fixed_nodal_forces": {str(n):f.tolist() for n,f in fixed_forces.items()}}
        if reference:
            report['reference_support']=reference
            report['reference_reaction_tolerance']=c['mesh'].get('balance_relative_tolerance',5e-4)
            from .reference_support import balanced
            balanced(coords,forces,report)
        if thermal:
            report["physics"] = "heat_transfer"
            for key in ("support_faces", "fixed_node_count", "fixed_dofs", "loads",
                        "applied_force_n", "applied_moment_n_mm", "load_force_scale_n",
                        "mass_kg", "fixed_nodal_forces"):
                report.pop(key, None)
        write_json(out / "mesh.json", report)
        return coords, tets, sorted(fixed), forces, report
