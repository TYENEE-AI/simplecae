"""Native analytic gauges, local refinement and campaign completion/resume."""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from pathlib import Path
from copy import deepcopy
import json
from .case import CONDITIONS,write_json,sha256
from .geometry import session
from .api import analyze_case
from .campaign import run_campaign
from .schemas import check_contract

def validate_maker(out,ccx=None,timeout=DEFAULT_NATIVE_TIMEOUT):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);checks=[]
    def check(name,passed,**detail):
        checks.append({'name':name,'passed':bool(passed),**detail})
        if not passed:raise AssertionError(name)
    with session() as g:
        g.model.occ.addBox(0,0,0,60,10,10);g.model.occ.synchronize();g.write(str(out/'bar.step'))
    material={'name':'analytic isotropic coupon','source':'E=69000 MPa, A=100 mm2 mathematical reference; no material test',
        'youngs_modulus_mpa':69000.,'poisson_ratio':.33,'yield_strength_mpa':240.,'failure_criterion':'von_mises_yield'}
    base={'schema_version':'2.0','reference_only':True,'model':{'path':str((out/'bar.step').resolve())},'material':material,
        'loads':[{'name':'left','selector':{'type':'plane','axis':'x','position_mm':0},'total_force_n':[-100,0,0]},
            {'name':'right','selector':{'type':'plane','axis':'x','position_mm':60},'total_force_n':[100,0,0]}],
        'criteria':{'yield_safety_factor':3.,'max_displacement_mm':None},'conditions':{k:False for k in CONDITIONS},
        'mesh':{'sizes_mm':[4.,2.8,1.96],'local_refinements':[{'name':'left-local','selector':{'type':'plane','axis':'x','position_mm':0},'size_factor':.6,'distance_mm':6.}]},
        'provenance':{'generator':'Gmsh analytic case','generator_version':'4.15.2','task_id':'maker-analytic-axial'},
        'probes':[{'name':'left','type':'point','point_mm':[0,5,5],'convergence_required':False},
            {'name':'right','type':'point','point_mm':[60,5,5],'convergence_required':False},
            {'name':'length','type':'relative_length','from_probe':'left','to_probe':'right','max_displacement_mm':.01}]}
    values=[];casepaths=[]
    for name,points in [('gauge-a',[[2,2,2],[2,8,2],[2,2,8]]),('gauge-b',[[4,3,3],[4,7,3],[4,3,7]])]:
        case=deepcopy(base);case['supports']=[{'name':str(i),'point_mm':p,'dofs':ds,'geometry_sha256':sha256(out/'bar.step')} for i,(p,ds) in enumerate(zip(points,[[1,2,3],[1,3],[1]]))]
        path=out/(name+'.json');write_json(path,case);casepaths.append(path)
        result=analyze_case(path,out/name,ccx=ccx,timeout=timeout,preview=False,storage='full')
        check(name+'-qualified',result['status']=='pass_under_stated_model',error=result.get('error'))
        check_contract(result,'result');check_contract(result['evaluation_signal'],'signal')
        r=result['levels'][-1]['results'];length=r['probes'][-1]['value_mm'];values.append(length)
        check(name+'-axial-displacement',abs(length/(100*60/(100*69000))-1)<.002,actual_mm=length)
        check(name+'-axial-stress',abs(r['max_von_mises_mpa']-1)<.002,actual_mpa=r['max_von_mises_mpa'])
        check(name+'-negligible-reference-reaction',r['reference_reaction_norm_n']<1e-6,actual_n=r['reference_reaction_norm_n'])
        check(name+'-six-independent-equations',all(l['mesh']['reference_support']['rank']==6 for l in result['levels']))
        targets=[l['mesh']['local_refinements'][0]['target_size_mm'] for l in result['levels']]
        check(name+'-all-local-targets-refine',all(abs(b/a-.7)<1e-9 for a,b in zip(targets,targets[1:])),targets_mm=targets)
        check(name+'-no-physical-material-claim',not result['evaluation_signal']['physical_conditions_verified'] and not result['assessment']['conditional_body_limit']['available'])
    check('gauge-invariant-length',abs(values[0]-values[1])<1e-8)
    invalid=json.loads(casepaths[0].read_text(encoding='utf-8'));invalid['supports'][0]['point_mm']=[100,100,100]
    bad=out/'outside-material.json';write_json(bad,invalid)
    campaign_case=out/'campaign-case.json';write_json(campaign_case,json.loads(casepaths[0].read_text(encoding='utf-8')))
    manifest=out/'campaign.json';write_json(manifest,{'schema_version':'simplecae-campaign-1.0','title':'native completion and partial failure',
        'items':[{'id':'valid','case_path':str(campaign_case.resolve()),'case_sha256':sha256(campaign_case)},
            {'id':'outside','case_path':str(bad.resolve()),'case_sha256':sha256(bad)}]})
    first=run_campaign(manifest,out/'campaign-run',ccx=ccx,timeout=timeout,preview=False)
    check('campaign-partial-failure-isolated',first['completed_count']==2 and first['items'][0]['status']=='pass_under_stated_model' and first['items'][1]['status']=='invalid')
    child=out/'campaign-run'/first['items'][1]['output_relative_path']/'analysis/signal.json'
    rejected=json.loads(child.read_text(encoding='utf-8'))
    check('invalid-gravity-or-missing-assessment-never-physical',not rejected['physical_conditions_verified'] and bool(rejected['not_assessed']))
    second=run_campaign(manifest,out/'campaign-run',ccx=ccx,timeout=timeout,preview=False,resume=True)
    check('campaign-audited-resume',second['items'][0]['resumed'] and second['items'][0]['output_relative_path']==first['items'][0]['output_relative_path'])
    folder=out/'campaign-run'/second['items'][0]['output_relative_path']
    modified=json.loads((folder/'analysis/signal.json').read_text(encoding='utf-8'))
    modified['metrics']['max_displacement_mm']+=.01
    write_json(folder/'analysis/signal.json',modified)
    third=run_campaign(manifest,out/'campaign-run',ccx=ccx,timeout=timeout,preview=False,resume=True)
    check('campaign-tampered-artifact-forces-new-attempt',not third['items'][0]['resumed'] and third['items'][0]['output_relative_path']!=first['items'][0]['output_relative_path'])
    changed=json.loads(campaign_case.read_text(encoding='utf-8'))
    changed['provenance']['task_id']='maker-analytic-axial-redeclared'
    write_json(campaign_case,changed)
    batch=json.loads(manifest.read_text(encoding='utf-8'));batch['items'][0]['case_sha256']=sha256(campaign_case);write_json(manifest,batch)
    fourth=run_campaign(manifest,out/'campaign-run',ccx=ccx,timeout=timeout,preview=False,resume=True)
    check('campaign-changed-declared-source-does-not-resume',not fourth['items'][0]['resumed'] and fourth['items'][0]['signal']['task_id']==changed['provenance']['task_id'])
    check('changed-task-still-uses-actual-qualified-native-fields',fourth['items'][0]['status']=='pass_under_stated_model')
    report={'passed':all(c['passed'] for c in checks),'checks':checks,'evidence_kind':'Actual native analytic static and software orchestration verification; no physical tests'}
    write_json(out/'validation.json',report);return report
