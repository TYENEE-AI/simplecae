"""Connected-body verification: patch stress, compliance, frames and materials."""
from .paths import resource_root
from pathlib import Path
import json
import copy
import math
import numpy as np
from .case import write_json
from .assembly import analyze_assembly


def tip_component(result,position_axis,component):
    directory=Path(result['levels'][-1]['directory']);mesh=np.load(directory/'mesh.npz');field=np.load(directory/'fields.npz')
    tip=mesh['xyz'][:,position_axis].max();ids={int(n) for n,p in zip(mesh['node_ids'],mesh['xyz']) if abs(p[position_axis]-tip)<1e-6}
    return abs(float(np.mean([u[component] for n,u in zip(field['node_ids'],field['displacements']) if int(n) in ids])))


def validate_assemblies(out,ccx=None,timeout=300):
    root=resource_root();fixtures=root/'examples/assemblies';out=Path(out);out.mkdir(parents=True,exist_ok=False)
    checks=[];results={}
    def check(name,passed,**details):checks.append({'name':name,'passed':bool(passed),**details})
    def compare(name,a,b,tolerance):
        error=abs(a-b)/max(abs(b),1e-30);check(name,error<=tolerance,actual=a,expected=b,relative_error=error,relative_tolerance=tolerance)
    for name in ('bonded','compliant','heterogeneous','compliant-bending','rotated','simplecad-packed'):
        result=analyze_assembly(fixtures/f'{name}.case.json',out/name,ccx,timeout,preview=True);results[name]=result
        check(name+' complete converged solve',result['status']=='pass_under_stated_model',error=result.get('error'))
        if result['status']=='invalid':continue
        axis=1 if name=='rotated' else 0;component=2 if name=='compliant-bending' else axis
        expected={'bonded':.005,'compliant':.015,'heterogeneous':.0075,'compliant-bending':.251,'rotated':.005,'simplecad-packed':.005}[name]
        compare(name+' independent displacement reference',tip_component(result,axis,component),expected,.02)
        for i,level in enumerate(result['levels']):
            compare(f'{name} global force/moment equilibrium {i+1}',max(level['results']['force_balance_relative_error'],level['results']['moment_balance_relative_error']),1e-30,0.)
            checks[-1].update(passed=max(level['results']['force_balance_relative_error'],level['results']['moment_balance_relative_error'])<=5e-4,
                              relative_error=None,relative_tolerance=None,absolute_tolerance=5e-4,expected=0.)
            check(f'{name} independent bodies retained {i+1}',level['mesh']['geometry']['solid_count']==2 and len(level['mesh']['materials'])==2)
            if name!='compliant-bending':compare(f'{name} uniform stress patch {i+1}',level['results']['max_von_mises_mpa'],10.,1e-6)
        if name in ('bonded','compliant','heterogeneous','rotated','simplecad-packed'):
            expected_limit={'compliant':.1/.015,'heterogeneous':1.5}.get(name,10.)
            limit=result['assessment']['conditional_body_limit'];check(name+' conditional body limit available',limit['available'])
            if limit['available']:compare(name+' per-material/compliance limit',limit['load_pattern_scale_factor'],expected_limit,1e-6)
        if name=='heterogeneous':check('weak body actually governs strength',result['assessment']['strength_peak']['material_id']=='MAT001')
        if name=='simplecad-packed':check('actual SDK compound solid selection',all(b['source_geometry'].get('source_solid_id') for b in result['levels'][-1]['mesh']['body_reports']))
    column=json.loads((fixtures/'bonded.case.json').read_text());column['loads'][0]['total_force_n']=[-100.,0,0]
    for body in column['bodies']:body['model']['path']=str(fixtures/'half-bar.step')
    column['buckling']={'enabled':True,'modes':3,'safety_factor':2.}
    write_json(out/'bonded-column.case.json',column)
    r=analyze_assembly(out/'bonded-column.case.json',out/'bonded-column',ccx,timeout,True);results['bonded-column']=r
    check('bonded assembly elastic buckling valid',r['status']=='pass_under_stated_model',error=r.get('error'))
    if r.get('assessment') and r['assessment'].get('buckling'):
        compare('bonded assembly Euler eigen factor',r['assessment']['buckling']['lowest_positive_load_factor'],math.pi**2*200000*(10000/12)/(4*100**2)/100,.05)
        check('bonded assembly eigen mesh convergence',r['assessment']['buckling']['mesh_converged'])
        check('bonded assembly mode files preserved',all(list(Path(l['directory']).glob('buckling-mode-*.npz')) for l in r['levels']))
    proof={'passed':all(c['passed'] for c in checks),'checks':checks,'cases':{n:str((out/n/'result.json').resolve()) for n in results},
           'evidence_kind':'Numerical connected-body verification and actual SimpleCADAPI assembly interoperability; no physical joint/material/adhesive validation',
           'references':['u=P*(L1/(E1A1)+L2/(E2A2))','Uniform stress patch sigma=P/A','Interface axial jump=P/(kn*A)',
                         'Bending reference PL^3/(3EI)+P*(L/2)^2/(kn*I)+P/(kt*A); small 3D shear/end corrections allowed',
                         'Positive spring energy and rigid-motion reproduction; segmented dual P2 interface transfer']}
    write_json(out/'validation.json',proof);return proof
