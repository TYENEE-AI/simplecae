"""Standalone interactive viewer using computed mesh/fields, no external CDN."""
from .paths import resource_root
import json
from pathlib import Path
import numpy as np


def viewer_data(directory:Path, include_modes=True):
    mesh=np.load(directory/"mesh.npz")
    fields=np.load(directory/"fields.npz")
    # Only surface nodes are referenced by the displayed triangles. Retaining
    # interior volume nodes bloats every report/revision without adding visible
    # geometry. Preserve every surface triangle and its original field values.
    all_ids=list(map(int,mesh["node_ids"]))
    surface_ids=set(map(int,np.asarray(mesh["surface_tri6"]).ravel()))
    rows=[i for i,n in enumerate(all_ids) if n in surface_ids]
    ids=[all_ids[i] for i in rows]
    index={n:i for i,n in enumerate(ids)}
    us={int(n):v for n,v in zip(fields["node_ids"],fields["displacements"])}
    u=np.array([us[n] for n in ids])
    stress={}
    strength={}
    for (e,_),s in zip(fields["stress_ids"],fields["stresses"]):
        vm=float(np.sqrt(.5*((s[0]-s[1])**2+(s[1]-s[2])**2+(s[2]-s[0])**2)+3*np.sum(s[3:]**2)))
        stress[int(e)]=max(stress.get(int(e),0.),vm)
    if 'strength_utilizations' in fields and len(fields['strength_utilizations'])==len(fields['stress_ids']):
        for (e,_),value in zip(fields['stress_ids'],fields['strength_utilizations']):strength[int(e)]=max(strength.get(int(e),0.),float(value))
    owners={}
    for e,ns in zip(mesh["element_ids"],mesh["connectivity"]):
        for face in ((0,1,2),(0,1,3),(0,2,3),(1,2,3)):
            owners[tuple(sorted(int(ns[i]) for i in face))]=int(e)
    triangles,values,utilizations=[] ,[],[]
    for tri in mesh["surface_tri6"]:
        e=owners[tuple(sorted(map(int,tri[:3])))]
        for face in ((0,3,5),(3,1,4),(5,4,2),(3,4,5)):
            triangles.append([index[int(tri[i])] for i in face])
            values.append(stress[e])
            if strength:utilizations.append(strength[e])
    modes={}
    for file in sorted(directory.glob("buckling-mode-*.npz")) if include_modes else []:
        source=np.load(file)
        vectors={int(n):v for n,v in zip(source["node_ids"],source["displacements"])}
        modes[file.stem]=[vectors[n].tolist() for n in ids]
    return {"xyz":mesh["xyz"][rows].tolist(),"triangles":triangles,"stress":values,
            "strength":utilizations,
            "displacements":u.tolist(),"modes":modes,"units":"mm/N/MPa",
            "display":{"volume_node_count":len(all_ids),"surface_node_count":len(ids),
                       "omitted_interior_nodes":len(all_ids)-len(ids),"surface_triangles_unchanged":True},
            "stress_meaning":"Each boundary triangle is colored by its adjacent volume element's peak integration-point stress, not exact surface stress. Unused interior nodes are omitted only from display; numerical evidence and acceptance are unchanged."}


def embed_viewer(directory:Path):
    data=viewer_data(directory)
    script=(resource_root()/"assets/viewer.js").read_text(encoding="utf-8")
    payload=json.dumps(data,allow_nan=False,separators=(",",":")).replace("<","\\u003c")
    return '<section class="cae-viewer"><h2>查看哪里变形、哪里受力集中</h2><p>拖动旋转，滚轮缩放。变形放大与模态幅值仅用于观察形状。</p><div class="viewer-controls"><label>显示 <select id="cae-field"><option value="stress">受力集中（MPa）</option><option value="displacement">实际位移（mm）</option></select></label><label>形状放大 <input id="cae-scale" type="range" min="0" max="2" step="0.01" value="1"></label><button id="cae-reset">重置视角</button><button id="cae-animate">形状演示</button></div><canvas id="cae-canvas" style="width:100%;height:520px;background:#f2f5f9;border-radius:16px;touch-action:none"></canvas><p id="cae-legend"></p><p id="cae-pick">点击模型查看当前位置的显示数值。</p></section><script id="cae-data" type="application/json">'+payload+'</script><script>'+script+'</script>'
