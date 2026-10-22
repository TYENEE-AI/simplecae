"""Located diagnostic hypotheses, never a change to strength acceptance."""
from pathlib import Path
import math
import numpy as np


def diagnose(case, levels, assessment):
    """Require rising non-decaying peaks, converged displacement and a CAD cause.

    The angle/distance/decay thresholds label a hypothesis only. They never gate
    solver execution or exclude stress. Unsupported shapes simply remain unknown.
    """
    if 'model' not in case or Path(case['model']['path']).suffix.lower() not in ('.step','.stp') or len(levels)<3:
        return None
    verification=assessment.get('verification',{})
    pairs=verification.get('mesh_comparisons',[])[-2:]
    if (len(pairs)!=2 or not all(p.get('displacement_converged') for p in pairs) or
        all(p.get('stress_converged') for p in pairs) or
        verification.get('force_and_moment_balance_passed') is not True or
        verification.get('small_response_screen_passed') is not True):return None
    peaks=[l['results']['max_von_mises_mpa'] for l in levels[-3:]]
    if not peaks[0]<peaks[1]<peaks[2]:return None
    changes=[p['stress_relative_change'] for p in pairs]
    if changes[0]<=0 or changes[1]/changes[0]<=.6:return None
    point=levels[-1]['results'].get('peak_element_centroid_mm')
    if point is None:return None
    h=levels[-1]['mesh_size_mm']
    from .geometry import session,inventory,select_faces
    with session(Path(case['model']['path']),case['model']) as g:
        info=inventory(g,Path(case['model']['path']))
        if case['model'].get('interface_manifest'):
            from .bridge import resolve_interfaces
            info['interfaces']=resolve_interfaces(case['model']['interface_manifest'],info)
        faces={f['id']:f for f in info['faces']}
        edges={}
        for face in faces:
            for dim,tag in g.model.getBoundary([(2,face)],oriented=False):
                if dim==1:edges.setdefault(tag,set()).add(face)
        boundary_edges=set()
        for spec in case.get('supports',[])+case.get('loads',[]):
            if 'selector' not in spec:continue
            selected=set(select_faces(info,spec['selector']))
            boundary_edges.update(tag for tag,adjacent in edges.items() if adjacent&selected and not adjacent<=selected)
        candidates=[]
        for edge,adjacent in edges.items():
            location,_=g.model.getClosestPoint(1,edge,point)
            # Some Gmsh/OCC builds return an unset curve parameter from
            # getClosestPoint despite a correct Cartesian projection. Recover
            # it from that point, then clamp to the trimmed edge bounds.
            parameter=g.model.getParametrization(1,edge,location)
            lo,hi=g.model.getParametrizationBounds(1,edge)
            parameter=np.clip(parameter,lo,hi)
            location=np.asarray(g.model.getValue(1,edge,parameter))
            distance=float(np.linalg.norm(location-np.asarray(point)))
            if distance>2*h:continue
            kind=None;angle=None
            if len(adjacent)==2:
                a,b=[faces[f] for f in sorted(adjacent)]
                if a.get('normal') is not None and b.get('normal') is not None:
                    n1,n2=np.asarray(a['normal']),np.asarray(b['normal'])
                    bend=math.degrees(math.acos(float(np.clip(np.dot(n1,n2),-1,1))))
                    scale=max(h,math.sqrt(min(a['area_mm2'],b['area_mm2'])))
                    if (np.dot(np.asarray(a['centroid_mm'])-location,n2)>scale*1e-9 and
                        np.dot(np.asarray(b['centroid_mm'])-location,n1)>scale*1e-9 and bend>15):
                        kind='reentrant_sharp';angle=180+bend
            if kind is None and edge in boundary_edges:kind='load_support_boundary'
            if kind:
                candidates.append({'xyz':point,'nearest_edge_id':edge,'edge_type':kind,'adjacent_faces':sorted(adjacent),
                    'distance_mm':distance,'edge_point_mm':location.tolist(),'interior_angle_deg':angle})
    if not candidates:return None
    located=min(candidates,key=lambda x:x['distance_mm'])
    parameters=case.get('provenance',{}).get('parameters',{})
    hints=[key for key in parameters if any(token in key.lower() for token in ('fillet','blend','radius'))]
    action={'type':'cad_change','suggestion':'add_fillet' if located['edge_type']=='reentrant_sharp' else 'review_physical_load_support_transition',
            'edge_hint':located,'param_hint':hints[0] if len(hints)==1 else None,
            'requires_reanalysis':True,'geometry_owner':'original CAD skill'}
    return {'classification':'likely_singular','peak_at':located,'stress_peaks_mpa':peaks,
            'stress_change_decay_ratio':changes[1]/changes[0],'displacement_converged':True,
            'heuristics':{'minimum_reentrant_angle_deg':195,'maximum_distance_mesh_sizes':2,'minimum_change_decay_ratio':.6},
            'actions':[action],
            'meaning':'Located singularity hypothesis only. Raw stress peaks, existing failures and acceptance criteria remain unchanged. Review a physical fillet/transition before another mesh attempt; no automatic hotspot exclusion or criterion relaxation.'}
