"""Explicit whole-face local sizing; every target refines with global h."""
from .case import keys,number,selector

def validate_refinements(mesh):
    specs=mesh.get('local_refinements',[])
    if not isinstance(specs,list):raise ValueError('mesh.local_refinements must be a list')
    names=[]
    for spec in specs:
        keys(spec,['name','selector','size_factor','distance_mm','sampling'],['name','selector','size_factor','distance_mm'],'local refinement')
        if not isinstance(spec['name'],str) or not spec['name'].strip():raise ValueError('local refinement name must be nonempty')
        names.append(spec['name']);selector(spec['selector'])
        if number(spec['size_factor'],'size_factor',True)>1:raise ValueError('size_factor must be <=1')
        number(spec['distance_mm'],'distance_mm',True)
        if type(spec.get('sampling',50)) is not int or not 10<=spec.get('sampling',50)<=500:raise ValueError('sampling must be 10..500')
    if len(names)!=len(set(names)):raise ValueError('local refinement names must be unique')
    return specs

def configure(g,info,mesh,h):
    from .geometry import select_faces
    specs=validate_refinements(mesh);fields=[];records=[]
    for spec in specs:
        faces=select_faces(info,spec['selector'])
        distance=g.model.mesh.field.add('Distance')
        g.model.mesh.field.setNumbers(distance,'SurfacesList',faces)
        g.model.mesh.field.setNumber(distance,'Sampling',spec.get('sampling',50))
        threshold=g.model.mesh.field.add('Threshold')
        for key,value in {'InField':distance,'SizeMin':h*spec['size_factor'],'SizeMax':h,'DistMin':0.,'DistMax':spec['distance_mm']}.items():
            g.model.mesh.field.setNumber(threshold,key,value)
        fields.append(threshold)
        records.append(dict(spec,face_ids=faces,target_size_mm=h*spec['size_factor']))
    if fields:
        minimum=g.model.mesh.field.add('Min');g.model.mesh.field.setNumbers(minimum,'FieldsList',fields)
        g.model.mesh.field.setAsBackgroundMesh(minimum)
        g.option.setNumber('Mesh.MeshSizeMin',h*min(s['size_factor'] for s in specs))
        g.option.setNumber('Mesh.MeshSizeFromPoints',0)
        g.option.setNumber('Mesh.MeshSizeFromCurvature',0)
        g.option.setNumber('Mesh.MeshSizeExtendFromBoundary',0)
    return records


def measure_surfaces(records,surfaces,coords):
    """Report attained corner-edge sizes; a sampled sizing field is a target."""
    import math
    result=[]
    for record in records:
        triangles=[tri for face in record['face_ids'] for tri in surfaces.get(face,[])]
        lengths=[math.dist(coords[tri[i]],coords[tri[j]]) for tri in triangles for i,j in ((0,1),(1,2),(2,0))]
        measured={'available':bool(lengths),'triangle_count':len(triangles),
                  'meaning':'Measured triangle corner chords, not curved arc lengths or a structural acceptance override.'}
        if lengths:
            mean=sum(lengths)/len(lengths)
            measured.update(corner_edge_min_mm=min(lengths),corner_edge_mean_mm=mean,corner_edge_max_mm=max(lengths),
                            corner_edge_mean_to_target=mean/record['target_size_mm'])
        result.append(dict(record,surface_mesh=measured))
    return result
