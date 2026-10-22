"""Explicit scene/unit normalization and conservative closed-surface meshing.

No hull substitution, hole filling, boolean union or visual-material inference.
"""
from pathlib import Path
import json
import struct
import numpy as np
from scipy.spatial import cKDTree
from .case import sha256


def glb_document(path):
    data=Path(path).read_bytes()
    if len(data)<20 or data[:4]!=b"glTF" or struct.unpack_from('<I',data,4)[0]!=2:
        raise ValueError("expected a glTF 2.0 GLB document")
    if struct.unpack_from('<I',data,8)[0]!=len(data):
        raise ValueError("GLB length does not match header")
    size,kind=struct.unpack_from('<II',data,12)
    if kind!=0x4e4f534a or 20+size>len(data):
        raise ValueError("GLB JSON chunk is missing or truncated")
    return json.loads(data[20:20+size].decode('utf-8').rstrip('\x00 '))


def triangle_overlap(a,b,tol):
    """Separating-axis test, including in-plane axes for coplanar triangles."""
    ea=np.roll(a,-1,axis=0)-a
    eb=np.roll(b,-1,axis=0)-b
    na=np.cross(ea[0],ea[1]); nb=np.cross(eb[0],eb[1])
    axes=[na,nb]+[np.cross(x,y) for x in ea for y in eb]
    axes += [np.cross(na,e) for e in ea] + [np.cross(nb,e) for e in eb]
    for axis in axes:
        length=np.linalg.norm(axis)
        if length<1e-16:
            continue
        axis=axis/length
        pa=a@axis; pb=b@axis
        if pa.max()<pb.min()-tol or pb.max()<pa.min()-tol:
            return False
    return True


def _segment_triangle(p, q, triangle, tol):
    """Closed segment/triangle test, including coplanar segments.

    Used only for the edge opposite a shared vertex, so the legitimate shared
    point is never itself a candidate intersection.
    """
    a, b, c = triangle
    normal = np.cross(b-a, c-a)
    normal /= np.linalg.norm(normal)
    dp, dq = np.dot(p-a, normal), np.dot(q-a, normal)
    if min(dp, dq) > tol or max(dp, dq) < -tol:
        return False
    drop = int(np.argmax(np.abs(normal)))
    tri = np.delete(triangle-a, drop, axis=1)
    start, end = np.delete(p-a, drop), np.delete(q-a, drop)
    cross = lambda u, v: u[0]*v[1]-u[1]*v[0]
    orientation = np.sign(cross(tri[1], tri[2]))
    if abs(dp) <= tol and abs(dq) <= tol:
        # Clip the segment against the three oriented triangle half-planes.
        lo, hi = 0., 1.
        for i in range(3):
            edge = tri[(i+1)%3]-tri[i]
            allowance = tol*np.linalg.norm(edge)
            f0 = orientation*cross(edge, start-tri[i])+allowance
            f1 = orientation*cross(edge, end-tri[i])+allowance
            if f0 < 0 and f1 < 0: return False
            if f0 < 0: lo = max(lo, f0/(f0-f1))
            if f1 < 0: hi = min(hi, f0/(f0-f1))
        return lo <= hi
    t = dp/(dp-dq)
    if not 0 <= t <= 1: return False
    point = start+t*(end-start)
    return all(orientation*cross(tri[(i+1)%3]-tri[i], point-tri[i]) >=
               -tol*np.linalg.norm(tri[(i+1)%3]-tri[i]) for i in range(3))


def adjacent_pair_intersects(a, b, shared, tol):
    """Test overlap beyond shared topology; never contract skinny triangles."""
    if len(shared) == 3: return True  # Duplicate faces are not adjacency.
    if len(shared) == 2:
        p, q = (a[i] for i, _ in shared)
        ra = a[next(i for i in range(3) if i not in {s[0] for s in shared})]
        rb = b[next(i for i in range(3) if i not in {s[1] for s in shared})]
        edge = q-p
        na, nb = np.cross(edge, ra-p), np.cross(edge, rb-p)
        na /= np.linalg.norm(na); nb /= np.linalg.norm(nb)
        # Noncoplanar triangles intersect only along their common edge.
        # Test both distances, important for very different triangle heights.
        if abs(np.dot(rb-p, na)) > tol or abs(np.dot(ra-p, nb)) > tol:
            return False
        return np.dot(na, nb) > 0  # Same-side coplanar fold.
    if len(shared) == 1:
        ia, ib = shared[0]
        ea, eb = a[[i for i in range(3) if i != ia]], b[[i for i in range(3) if i != ib]]
        return _segment_triangle(*ea, b, tol) or _segment_triangle(*eb, a, tol)
    return triangle_overlap(a, b, tol)


def check_self_intersection(mesh,pair_budget=None,*,algorithm='topology'):
    if algorithm not in ('topology','legacy'):
        raise ValueError('intersection algorithm must be topology or legacy')
    triangles=np.asarray(mesh.triangles,dtype=float)
    if pair_budget is None:pair_budget=max(600000,12*len(triangles))
    if type(pair_budget) is not int or pair_budget<0:raise ValueError('pair budget must be a nonnegative integer')
    centers=triangles.mean(axis=1)
    radii=np.linalg.norm(triangles-centers[:,None,:],axis=2).max(axis=1)
    max_radius=float(radii.max())
    lower,upper=triangles.min(axis=1),triangles.max(axis=1)
    edge_lengths=np.linalg.norm(np.roll(triangles,-1,axis=1)-triangles,axis=2)
    tree=cKDTree(centers)
    span=max(float(np.linalg.norm(np.ptp(mesh.vertices,axis=0))),1.)
    tol=span*1e-10
    count=0
    for i in range(len(triangles)):
        candidates=np.asarray(tree.query_ball_point(centers[i],radii[i]+max_radius+tol),dtype=int)
        candidates=candidates[candidates>i]
        candidates=candidates[(np.linalg.norm(centers[i]-centers[candidates],axis=1)<=radii[i]+radii[candidates]+tol)
                              & np.all(upper[i]>=lower[candidates]-tol,axis=1)
                              & np.all(upper[candidates]>=lower[i]-tol,axis=1)]
        for j in candidates:
            count+=1
            if count>pair_budget:
                raise ValueError("surface-intersection checking exceeds pair budget; reduce tessellation or provide STEP")
            a,b=triangles[i],triangles[j]
            shared=[(ia,ib) for ia,va in enumerate(mesh.faces[i]) for ib,vb in enumerate(mesh.faces[j]) if va==vb]
            if algorithm=='legacy' and shared:
                # Adjacent faces must touch along their shared topology. Test
                # their interiors after a declared tiny contraction instead.
                a=centers[i]+(a-centers[i])*(1-1e-6)
                b=centers[j]+(b-centers[j])*(1-1e-6)
            local_tol=max(edge_lengths[i].max(),edge_lengths[j].max())*1e-12
            intersects=(triangle_overlap(a,b,tol) if algorithm=='legacy' else adjacent_pair_intersects(a,b,shared,local_tol))
            if intersects:
                from .diagnostics import WorkflowError
                areas=np.linalg.norm(np.cross(np.array([a,b])[:,1]-np.array([a,b])[:,0],np.array([a,b])[:,2]-np.array([a,b])[:,0]),axis=1)/2
                aspects=2*areas/np.array([edge_lengths[i].max(),edge_lengths[j].max()])**2
                raise WorkflowError(f"intersecting surface triangles {i} and {j}; no automatic topology repair",
                    'surface_self_intersection',next_action='inspect_triangle_pair_or_export_step',
                    details={'triangle_ids':[int(i),int(j)],'coordinates_mm':[a.tolist(),b.tolist()],
                             'areas_mm2':areas.tolist(),'minimum_altitude_to_longest_edge':float(aspects.min()),
                             'local_tolerance_mm':local_tol,
                             'advice':'Inspect the reported overlap. For sliver tessellation, try a coarser CAD mesh export or native STEP; do not disable validation.'})
    return {"candidate_pairs_checked":count,"pair_budget":pair_budget,"length_tolerance_mm":tol,
            "broad_phase_tolerance_mm":tol,
            "algorithm":algorithm,"adjacent_face_interior_contraction":1e-6 if algorithm=='legacy' else None,
            "local_relative_tolerance":1e-12 if algorithm=='topology' else None,"passed":True,
            "meaning":"finite-precision triangle intersection check; features below tolerance are unresolved"}


def load_surface(model):
    from .input_guidance import require_fem_format
    require_fem_format(model['path'])
    import trimesh
    path=Path(model['path'])
    suffix=path.suffix.lower()
    if suffix not in ('.glb','.stl','.obj'):
        raise ValueError("mesh adapter accepts GLB, STL or OBJ")
    units=model.get('units','m' if suffix=='.glb' else None)
    if units not in ('m','mm','cm'):
        raise ValueError("mesh units must be explicit m/mm/cm (GLB defaults to normative metres)")
    if suffix=='.glb':
        document=glb_document(path)
        if document.get('skins') or any(p.get('targets') for m in document.get('meshes',[]) for p in m.get('primitives',[])):
            raise ValueError("skinned/morphing GLB is not a structural rest geometry; export a posed rigid mesh or use URDF")
        if document.get('animations') and model.get('pose')!='rest':
            raise ValueError("animated GLB requires explicit pose=rest; animation is not evaluated")
        if any('uri' in b and not b['uri'].startswith('data:') for b in document.get('buffers',[])):
            raise ValueError("GLB structural buffers must be embedded")
    scene=trimesh.load_scene(path,process=False,skip_materials=True)
    nodes=list(scene.graph.nodes_geometry)
    selected=model.get('scene_node')
    if selected is None and len(nodes)!=1:
        raise ValueError(f"mesh has {len(nodes)} geometry occurrences; choose scene_node explicitly or use an assembly case. Available: {nodes}")
    selected=selected if selected is not None else nodes[0]
    if selected not in nodes:
        raise ValueError(f"unknown scene_node {selected}; available: {nodes}")
    transform,geometry=scene.graph[selected]
    mesh=scene.geometry[geometry].copy()
    if not isinstance(mesh,trimesh.Trimesh):
        raise ValueError("selected scene occurrence is not a triangle mesh")
    if not np.all(np.isfinite(transform)) or abs(np.linalg.det(transform[:3,:3]))<1e-12:
        raise ValueError("scene occurrence transform is singular or non-finite")
    mesh.apply_transform(transform)
    mesh.apply_scale({'m':1000.,'cm':10.,'mm':1.}[units])
    source_up=model.get('source_up_axis','y' if suffix=='.glb' else 'z')
    if source_up=='y':
        mesh.apply_transform([[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]])
    elif source_up!='z':
        raise ValueError("source_up_axis must be y or z")
    from .defaults import DEFAULT_INPUT_TRIANGLES
    if not len(mesh.faces) or len(mesh.faces)>DEFAULT_INPUT_TRIANGLES or not np.all(np.isfinite(mesh.vertices)):
        raise ValueError(f"mesh must have finite vertices and 1..{DEFAULT_INPUT_TRIANGLES} triangles")
    old_count=len(mesh.vertices)
    # Weld coincident tessellation vertices only; do not fill or alter surfaces.
    mesh.merge_vertices(digits_vertex=12)
    if np.min(mesh.area_faces)<=max(mesh.extents.max(),1.)**2*1e-16:
        raise ValueError("surface has degenerate triangles")
    if not mesh.is_watertight or not mesh.is_winding_consistent:
        raise ValueError("surface must be closed with consistent face winding; no implicit repair")
    if len(mesh.split(only_watertight=False))!=1:
        raise ValueError("selected occurrence contains disconnected shells; use explicit solid bodies. "
                         "scene_node cannot split a flattened multi-part occurrence. Export separate parts, "
                         "or inspect the original STEP with --all-bodies and select a source-bound solid_id. "
                         "No implicit fusion or shell selection was performed.")
    if not np.isfinite(mesh.volume) or abs(mesh.volume)<1e-12:
        raise ValueError("surface encloses no positive volume")
    flipped=mesh.volume<0
    if flipped:
        mesh.invert()
    intersections=check_self_intersection(mesh)
    return mesh,{'source_format':suffix[1:],'source_units':units,'source_up_axis':source_up,
                 'analysis_up_axis':'z','scene_node':str(selected),'scene_transform':np.asarray(transform).tolist(),
                 'coincident_vertices_welded':old_count-len(mesh.vertices),'global_winding_reversed':bool(flipped),
                 'surface_triangle_count':len(mesh.faces),'closed':True,'single_connected_shell':True,
                 'self_intersection_check':intersections,'volume_mm3':float(mesh.volume),
                 'center_of_mass_mm':mesh.center_mass.tolist(),
                 'bbox_mm':mesh.bounds.tolist(),'source_sha256':sha256(path),
                 'limitation':'Faceted surface is the analyzed geometry; original CAD curvature/tessellation error is not inferred.'}


def import_surface(g,model):
    mesh,source=load_surface(model)
    surface=g.model.addDiscreteEntity(2)
    g.model.mesh.addNodes(2,surface,list(range(1,len(mesh.vertices)+1)),mesh.vertices.ravel().tolist())
    g.model.mesh.addElementsByType(surface,2,list(range(1,len(mesh.faces)+1)),(mesh.faces+1).ravel().tolist())
    g.model.mesh.classifySurfaces(np.deg2rad(40.),True,True,np.pi)
    g.model.mesh.createGeometry()
    surfaces=[t for d,t in g.model.getEntities(2)]
    loop=g.model.geo.addSurfaceLoop(surfaces)
    g.model.geo.addVolume([loop])
    g.model.geo.synchronize()
    return source


def surface_inventory(g,path,source):
    ids,xyz,_=g.model.mesh.getNodes()
    coords={int(n):p for n,p in zip(ids,np.asarray(xyz).reshape(-1,3))}
    faces=[]
    for _,tag in g.model.getEntities(2):
        types,_,connections=g.model.mesh.getElements(2,tag)
        triangles=[]
        for kind,raw in zip(types,connections):
            _,_,_,nodes,_,corners=g.model.mesh.getElementProperties(kind)
            if corners!=3:
                raise ValueError("discrete boundary is not triangular")
            triangles.extend([[coords[int(n)] for n in t[:3]] for t in np.asarray(raw).reshape(-1,nodes)])
        points=np.asarray(triangles).reshape(-1,3)
        centers=np.mean(triangles,axis=1)
        triangles=np.asarray(triangles)
        areas=np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1)/2
        singular=np.linalg.svd(points-points.mean(axis=0),compute_uv=False)
        planar=singular[-1]<=max(singular[0],1.)*1e-9
        faces.append({'id':tag,'type':'Plane' if planar else 'FacetedSurface','area_mm2':float(areas.sum()),
                      'centroid_mm':np.average(centers,axis=0,weights=areas).tolist(),
                      'bbox_mm':np.r_[points.min(axis=0),points.max(axis=0)].tolist()})
    return {'geometry_sha256':sha256(path),'source_model':str(path.resolve()),'units':'mm',
            'gmsh_version':g.__version__,'solid_count':1,'volume_mm3':source['volume_mm3'],
            'bbox_mm':source['bbox_mm'],'center_of_mass_mm':source['center_of_mass_mm'],'faces':faces,'mesh_input':source}
