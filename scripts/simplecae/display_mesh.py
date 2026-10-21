"""Deterministic display-only vertex clustering, never an FE/source operation."""
import numpy as np


def simplify_display(mesh,target=20000):
    if len(mesh.faces)<=target:return mesh,None
    import trimesh
    vertices=np.asarray(mesh.vertices);lo=vertices.min(axis=0);span=float(np.max(vertices.max(axis=0)-lo))
    if span<=0:raise ValueError('display mesh has zero extent')
    for divisions in (256,192,128,96,64,48,32):
        cell=span/divisions
        groups=np.floor((vertices-lo)/cell).astype(np.int64)
        _,inverse=np.unique(groups,axis=0,return_inverse=True)
        count=np.bincount(inverse);new=np.column_stack([np.bincount(inverse,weights=vertices[:,i])/count for i in range(3)])
        faces=inverse[np.asarray(mesh.faces)]
        faces=faces[(faces[:,0]!=faces[:,1])&(faces[:,1]!=faces[:,2])&(faces[:,0]!=faces[:,2])]
        # Retain orientation of the first original face for each collapsed triangle.
        _,indices=np.unique(np.sort(faces,axis=1),axis=0,return_index=True);faces=faces[np.sort(indices)]
        max_error=float(np.max(np.linalg.norm(vertices-new[inverse],axis=1)))
        if len(faces)<=target and max_error<=span*.01:
            result=trimesh.Trimesh(vertices=new,faces=faces,process=False)
            return result,{'method':'vertex clustering for display only','source_triangles':len(mesh.faces),
                           'display_triangles':len(faces),'max_original_vertex_shift_m':max_error,
                           'scope':'Visual approximation only; STEP/FEM/collision geometry is unchanged. Thin or small features can disappear.'}
    raise ValueError('visual cannot meet display budget within1% extent vertex-error limit; use a separate documented visual mesh')
