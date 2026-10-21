"""Diagnostic mesh trends only; never remove a peak or infer an acceptable stress."""
import math


def mesh_sensitivity(result):
    levels=result.get('levels',[])
    if len(levels)<3:return None
    rows=[level.get('results',{}) for level in levels[-3:]]
    if any(not all(isinstance(row.get(k),(int,float)) and math.isfinite(row[k]) and row[k]>0
                   for k in ('max_von_mises_mpa','max_displacement_mm')) for row in rows):return None
    mesh=result.get('case',{}).get('mesh',{})
    stress=[abs(b['max_von_mises_mpa']-a['max_von_mises_mpa'])/b['max_von_mises_mpa'] for a,b in zip(rows,rows[1:])]
    displacement=[abs(b['max_displacement_mm']-a['max_displacement_mm'])/b['max_displacement_mm'] for a,b in zip(rows,rows[1:])]
    if all(x<=mesh.get('stress_relative_tolerance',.1) for x in stress):return None
    stable_u=all(x<=mesh.get('displacement_relative_tolerance',.05) for x in displacement)
    return {'kind':'numerical_diagnostic','scope':'stress_mesh_sensitivity',
            'cause':'unresolved','requires_reanalysis':True,
            'displacement_stable':stable_u,'stress_relative_changes':stress,
            'displacement_relative_changes':displacement,
            'peaks':[{'mesh_size_mm':level.get('mesh_size_mm'),
                      **{k:row.get(k) for k in ('max_von_mises_mpa','peak_element_centroid_mm',
                                               'peak_mesh_quality','peak_element_corner_edges_mm')}}
                     for level,row in zip(levels[-3:],rows)],
            'message':'Full peak stress has not met the original mesh criterion. Stable displacement does not establish local strength or prove a singularity.',
            'suggestion':'Check local element quality, load/support discontinuities and the actual CAD transition radius. Refine the peak region while holding physics and the remote mesh fixed; compare full peaks and fixed physical offset diagnostics. A good-quality rising peak near a reentrant sharp edge supports a singularity hypothesis, not permission to omit it. Obtain a real radius or explicitly propose a CAD revision and recheck all gates.'}
