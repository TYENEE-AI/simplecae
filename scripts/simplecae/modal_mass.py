"""Explicit nonstructural surface mass; no added stiffness or rigid offset."""
from pathlib import Path
import numpy as np
from .geometry import select_faces


def compile_masses(case, mesh, directory):
    coords, _, _, _, meta=mesh
    totals={};reports=[]
    if not case.get('attached_masses'):return totals,reports
    with np.load(Path(directory)/'mesh.npz',allow_pickle=False) as data:
        triangles=data['surface_tri6'];face_ids=data['surface_face_ids']
    for spec in case['attached_masses']:
        faces=select_faces(meta['geometry'],spec['selector'])
        if any(f['type']!='Plane' for f in meta['geometry']['faces'] if f['id'] in faces):
            raise ValueError('Attached surface masses currently require a planar mounting patch')
        weights={}
        # Positive barycentric lumping on four subtriangles of each tri6.
        # Cross-mesh mode checks retain the attachment discretization error.
        for tri in triangles[np.isin(face_ids,faces)]:
            for indices in ((0,3,5),(3,1,4),(5,4,2),(3,4,5)):
                ns=[int(tri[i]) for i in indices];p=np.array([coords[n] for n in ns])
                area=float(np.linalg.norm(np.cross(p[1]-p[0],p[2]-p[0]))/2)
                for n in ns:weights[n]=weights.get(n,0.)+area/3
        area=sum(weights.values())
        if area<=0:raise ValueError('Attached mass has an empty or zero-area patch')
        if any(meta['fixed_dofs'].get(str(n)) for n in weights):
            raise ValueError('Attached mass patch overlaps restrained nodes; choose the actual moving attachment')
        masses={n:spec['mass_kg']*a/area for n,a in weights.items() if a>0}
        for n,m in masses.items():totals[n]=totals.get(n,0.)+m
        reports.append({'name':spec['name'],'mass_kg':sum(masses.values()),'face_ids':faces,
                        'center_mm':(sum((coords[n]*m for n,m in masses.items()),np.zeros(3))/spec['mass_kg']).tolist(),
                        'node_count':len(masses),'basis':spec['basis'],
                        'model':'Nonstructural mass distributed over the selected patch. No payload stiffness, remote COM, rotary inertia or mount compliance.'})
    return totals,reports
