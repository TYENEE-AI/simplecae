"""Opt-in, CAD-verified contained planar contact; no implicit extrapolation.

The exact trimmed CAD slave must be inside the master after gap projection.
The FE interpolation is checked separately: CAD coverage does not imply that
two independently curved quadratic meshes cover each other's approximation.
"""
import numpy as np
from .assembly import SurfaceProjector,quadrature,tri_basis


def cad_coverage(spec,bodies,body_data,normal,gap):
    from .geometry import session,select_faces
    from .robot import rotation_rpy
    selected={}
    with session() as g:
        for role in ('master','slave'):
            side=spec[role];data=body_data[side['body']]
            if not data.get('brep'):
                raise ValueError('slave_within_master requires native CAD planar faces')
            before=set(g.model.occ.getEntities(2))
            imported=g.model.occ.importShapes(data['brep']);g.model.occ.synchronize()
            available=list(set(g.model.occ.getEntities(2))-before)
            ids=select_faces(data['local_geometry'],side['selector']);chosen=[]
            for fid in ids:
                f=next(f for f in data['local_geometry']['faces'] if f['id']==fid)
                matches=[dt for dt in available if
                    abs(g.model.occ.getMass(*dt)-f['area_mm2'])<=max(f['area_mm2'],1)*1e-8 and
                    np.linalg.norm(np.array(g.model.occ.getCenterOfMass(*dt))-f['centroid_mm'])<1e-6]
                if len(matches)!=1:raise ValueError('cannot uniquely recover source-bound contact CAD face')
                chosen+=g.model.occ.copy(matches)
            b=next(b for b in bodies if b['name']==side['body'])
            placement=b.get('placement',{'rpy_rad':[0,0,0],'translation_mm':[0,0,0]})
            # OCC affineTransform converts conics to approximate splines, even
            # for an identity transform. Native rigid operations preserve the
            # trimmed circles needed by this geometric coverage proof.
            from scipy.spatial.transform import Rotation
            rotvec=Rotation.from_matrix(rotation_rpy(placement['rpy_rad'])).as_rotvec()
            angle=float(np.linalg.norm(rotvec))
            if angle>1e-14:g.model.occ.rotate(chosen,0,0,0,*(rotvec/angle),angle)
            translation=np.array(placement['translation_mm'],float)
            if role=='slave':translation-=gap*np.asarray(normal)
            if np.linalg.norm(translation)>0:g.model.occ.translate(chosen,*translation)
            selected[role]=chosen
        area=sum(g.model.occ.getMass(*dt) for dt in selected['slave'])
        outside,_=g.model.occ.cut(selected['slave'],selected['master'])
        remainder=sum(g.model.occ.getMass(*dt) for dt in outside if dt[0]==2)
    tolerance=max(area,1.)*1e-8
    if area<=0 or not np.isfinite(remainder) or remainder>tolerance:
        raise ValueError(f'contact slave footprint is not contained in master: uncovered {remainder:g} mm2')
    return {'method':'exact OpenCASCADE trimmed-face difference after declared rigid placement/gap projection',
            'slave_cad_area_mm2':area,'uncovered_area_mm2':remainder,'area_tolerance_mm2':tolerance}


def contained_samples(master,slave,coords,budget,tolerance):
    projector=SurfaceProjector(coords,master['triangles'],tolerance)
    # Includes boundary nodes; a failed FE projection is not snapped or omitted.
    for point in slave['points']:projector.project(point)
    count=0
    for i,tri in enumerate(slave['triangles']):
        p=np.array([coords[n] for n in tri])
        for r,s,w in quadrature():
            ns,dr,ds=tri_basis(r,s);point=ns@p
            mn,nm,error=projector.project(point)
            measure=float(np.linalg.norm(np.cross(dr@p,ds@p))*w/2)
            if not np.isfinite(measure) or measure<=0:raise ValueError('invalid planar contact quadrature Jacobian')
            if abs(nm.sum()-1)>1e-9 or np.linalg.norm(nm@np.array([coords[n] for n in mn])-point)>tolerance:
                raise ValueError('contact interpolation does not reproduce rigid motion')
            count+=1
            if count>budget:raise ValueError('contained contact quadrature exceeds declared budget')
            yield tri,ns,mn,nm,point,measure,i
