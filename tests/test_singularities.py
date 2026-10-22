import copy
from pathlib import Path
from simplecae.geometry import session
from simplecae.singularities import diagnose


def test_located_reentrant_edge_requires_all_trend_gates(tmp_path):
    step=tmp_path/'sharp.step'
    with session() as g:
        wall=g.model.occ.addBox(0,-10,0,8,20,80)
        arm=g.model.occ.addBox(0,-10,0,60,20,8)
        g.model.occ.fuse([(3,wall)],[(3,arm)])
        g.model.occ.synchronize();g.write(str(step))
    c={'model':{'path':str(step)},'supports':[],'loads':[],
       'provenance':{'parameters':{'root_fillet_r':0}}}
    levels=[{'mesh_size_mm':h,'results':{'max_von_mises_mpa':p,'peak_element_centroid_mm':[8.5,0,7.8]}}
            for h,p in zip([4,3,2.25],[10,12,14])]
    v={'force_and_moment_balance_passed':True,'small_response_screen_passed':True,
       'mesh_comparisons':[{'displacement_converged':True,'stress_converged':False,'stress_relative_change':.16},
                           {'displacement_converged':True,'stress_converged':False,'stress_relative_change':.14}]}
    result=diagnose(c,levels,{'verification':v})
    assert result['classification']=='likely_singular'
    assert result['peak_at']['edge_type']=='reentrant_sharp'
    assert result['peak_at']['interior_angle_deg']==270
    assert result['actions'][0]['param_hint']=='root_fillet_r'
    for key in ('force_and_moment_balance_passed','small_response_screen_passed'):
        bad=copy.deepcopy(v);bad[key]=False
        assert diagnose(c,levels,{'verification':bad}) is None
    bad=copy.deepcopy(v);bad['mesh_comparisons'][-1]['displacement_converged']=False
    assert diagnose(c,levels,{'verification':bad}) is None
    bad=copy.deepcopy(v);bad['mesh_comparisons'][-1]['stress_relative_change']=.01
    assert diagnose(c,levels,{'verification':bad}) is None
    for level in levels:level['results']['peak_element_centroid_mm']=[60,0,8]
    assert diagnose(c,levels,{'verification':v}) is None  # convex outer edge
