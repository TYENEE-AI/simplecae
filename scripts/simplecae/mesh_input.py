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


def check_self_intersection(mesh,pair_budget=600000):
    triangles=np.asarray(mesh.triangles,dtype=float)
    centers=triangles.mean(axis=1)
    radii=np.linalg.norm(triangles-centers[:,None,:],axis=2).max(axis=1)
    tree=cKDTree(centers)
    span=max(float(np.linalg.norm(np.ptp(mesh.vertices,axis=0))),1.)
    tol=span*1e-10
    count=0
    for i in range(len(triangles)):
        for j in tree.query_ball_point(centers[i],radii[i]+radii.max()+tol):
            if j<=i or np.linalg.norm(centers[i]-centers[j])>radii[i]+radii[j]+tol:
                continue
            if np.any(triangles[i].max(axis=0)<triangles[j].min(axis=0)-tol) or np.any(triangles[j].max(axis=0)<triangles[i].min(axis=0)-tol):
                continue
            count+=1
            if count>pair_budget:
                raise ValueError("surface-intersection checking exceeds pair budget; reduce tessellation or provide STEP")
            a,b=triangles[i],triangles[j]
            if set(mesh.faces[i]) & set(mesh.faces[j]):
                # Adjacent faces must touch along their shared topology. Test
                # their interiors after a declared tiny contraction instead.
                a=centers[i]+(a-centers[i])*(1-1e-6)
                b=centers[j]+(b-centers[j])*(1-1e-6)
            if triangle_overlap(a,b,tol):
                raise ValueError(f"intersecting surface triangles {i} and {j}; no automatic topology repair")
    return {"candidate_pairs_checked":count,"length_tolerance_mm":tol,
            "adjacent_face_interior_contraction":1e-6,"passed":True,
            "meaning":"finite-precision triangle intersection check; features below tolerance are unresolved"}


def load_surface(model):
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
    if not len(mesh.faces) or len(mesh.faces)>100000 or not np.all(np.isfinite(mesh.vertices)):
        raise ValueError("mesh must have finite vertices and 1..100000 triangles")
    old_count=len(mesh.vertices)
    # Weld coincident tessellation vertices only; do not fill or alter surfaces.
    mesh.merge_vertices(digits_vertex=12)
    if np.min(mesh.area_faces)<=max(mesh.extents.max(),1.)**2*1e-16:
        raise ValueError("surface has degenerate triangles")
    if not mesh.is_watertight or not mesh.is_winding_consistent:
        raise ValueError("surface must be closed with consistent face winding; no implicit repair")
    if len(mesh.split(only_watertight=False))!=1:
        raise ValueError("selected occurrence contains disconnected shells; use explicit solid bodies")
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
