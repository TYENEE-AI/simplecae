"""Real bounded-entry references, including expected failure/insufficiency."""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from .paths import resource_root
from pathlib import Path
import copy
import json
import numpy as np

from .case import write_json
from .design_check import design_check, compare_design_checks


def validate_design_checks(out, ccx=None, timeout=DEFAULT_NATIVE_TIMEOUT):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    root=resource_root()
    context=root/'examples/preview/design-context.json'
    checks=[]
    expected={'pass':'pass_under_stated_model','fail':'fail_under_stated_model',
              'indeterminate':'indeterminate','iteration':'pass_under_stated_model'}
    for name,status in expected.items():
        review=design_check(root/f'examples/preview/{name}.case.json',out/name,
            context_path=context,ccx=ccx,timeout=timeout,budget_seconds=timeout,preview=False)
        f=review['feedback']
        checks.append({'case':name,'passed':review['execution']['state']=='completed' and f['model_status']==status
            and f['whole_product_pass_available'] is False and f['conditional_model_pass']==(True if status=='pass_under_stated_model' else False if status=='fail_under_stated_model' else None),
            'actual_status':f['model_status'],'expected_status':status})
    comparison=compare_design_checks([out/'fail/design-review.json',out/'iteration/design-review.json'])
    write_json(out/'design-comparison.json',comparison)
    checks.append({'case':'same-task-CAD-iteration','passed':comparison['comparable'] and comparison['whole_product_pass_available'] is False})
    checks.append({'case':'insufficient-evidence-comparison-rejected','passed':not compare_design_checks([out/'pass/design-review.json',out/'indeterminate/design-review.json'])['comparable']})
    advanced=root/'examples/joints/bolt-preload-overload.case.json'
    review=design_check(advanced,out/'default-detailed-guard',context_path=context,ccx=ccx,budget_seconds=timeout)
    checks.append({'case':'default-keeps-preload-and-requests-depth','passed':review['execution']['state']=='needs_explicit_model' and review['execution']['worker_started'] is False})
    # Scope is explicit for the distinct detailed mathematical reference.
    detailed_context=out/'detailed-context.json'
    write_json(detailed_context,{'question':'Does the declared preload stage exceed its axial allowance?',
        'scope':'Prescribed mathematical bolt/contact reference, including preload, lock and service.',
        'assumptions':['Ideal elastic bodies, prescribed spring stiffness and preload.'],
        'not_assessed':['Physical fastener, anchor, material and product qualification.']})
    review=design_check(advanced,out/'detailed-preload-failure',context_path=detailed_context,depth='detailed',
        ccx=ccx,timeout=timeout,budget_seconds=timeout,preview=False)
    checks.append({'case':'preload-failure-survives-detailed-entry','passed':review['execution']['state']=='completed'
        and review['feedback']['model_status']=='fail_under_stated_model'
        and review['feedback']['conditional_model_pass'] is False
        and any(k.startswith('preload:') and v['status']=='fail_under_stated_model'
                for k,v in review['feedback']['criterion_assessments'].items())})
    detailed=json.loads((out/'detailed-preload-failure/analysis/result.json').read_text(encoding='utf-8'))
    checks.append({'case':'capacity-off-preserves-all-bolt-stages','passed':not detailed['analysis_options']['predict_capacity']
        and all(set(map(int,l['solver']['completed_load_steps']))=={1,2,3} for l in detailed['levels'])
        and set(detailed['stage_assessments'])=={'preload','locked','service'}})
    # Same declared mathematical model, only an execution option differs.
    # True flags here declare benchmark premises, not physical verification.
    from .api import analyze_case
    gravity=json.loads((root/'examples/preview/pass.case.json').read_text(encoding='utf-8'))
    gravity['model']['path']=str(root/'examples/preview/beam.step')
    gravity['material']['density_kg_m3']=7850.
    gravity['gravity']={'acceleration_m_s2':[0.,0.,-9.80665]}
    gravity['conditions']={key:True for key in gravity['conditions']}
    gravity['conditions']['self_weight_negligible']=False
    gravity['notes']='Prescribed mathematical gravity reference; true flags specify analytic premises only, not a physical certificate.'
    write_json(out/'gravity.case.json',gravity)
    on=analyze_case(out/'gravity.case.json',out/'capacity-on',ccx=ccx,timeout=timeout,preview=False,storage='full')
    off=analyze_case(out/'gravity.case.json',out/'capacity-off',ccx=ccx,timeout=timeout,preview=False,predict_capacity=False,storage='full')
    checks.append({'case':'capacity-off-retains-requested-verdict-and-criteria','passed':on['status']==off['status']=='pass_under_stated_model'
        and on['assessment']['criterion_assessments']==off['assessment']['criterion_assessments']
        and on['assessment']['verification']==off['assessment']['verification']})
    checks.append({'case':'capacity-is-explicitly-withheld-only-when-disabled','passed':on['assessment']['conditional_body_limit']['available']
        and not off['assessment']['conditional_body_limit']['available']
        and off['assessment']['conditional_body_limit']['load_pattern_scale_factor'] is None})
    for i,(a,b) in enumerate(zip(on['levels'],off['levels']),1):
        da,db=Path(a['directory']),Path(b['directory'])
        with np.load(da/'fields.npz') as x,np.load(db/'fields.npz') as y:
            identical=set(x.files)==set(y.files) and all(np.array_equal(x[k],y[k]) for k in x.files)
        checks.append({'case':f'gravity-level-{i}-identical-service-deck-and-all-fields','passed':
            (da/'job.inp').read_bytes()==(db/'job.inp').read_bytes() and identical and a['results']==b['results']
            and (da/'fixed.inp').is_file() and not (db/'fixed.inp').exists()})
    robot=json.loads((root/'examples/robots/one-link.robot.json').read_text(encoding='utf-8'))
    robot['model']['path']=str(root/'examples/robots'/robot['model']['path'])
    for component in robot['components']:component['case_path']=str(root/'examples/robots'/component['case_path'])
    robot['poses']=robot['poses'][:1]
    robot['effort_limits']={'shoulder':.1}
    robot['conditions']={key:False for key in robot['conditions']}
    write_json(out/'robot.case.json',robot)
    robot_context=out/'robot-context.json'
    write_json(robot_context,{'question':'Does actuator effort control the task despite an acceptable arm?',
        'scope':'Prescribed one-link static model with component FEM and declared actuator effort.',
        'assumptions':['Mathematical link, pose, payload and actuator limit.'],
        'not_assessed':['Physical link/actuator and whole robot qualification.']})
    review=design_check(out/'robot.case.json',out/'robot',context_path=robot_context,ccx=ccx,timeout=timeout,budget_seconds=timeout,preview=False)
    checks.append({'case':'robot-actuator-governing-feedback-and-no-body-promotion','passed':review['execution']['state']=='completed'
        and review['feedback']['model_status']=='fail_under_stated_model'
        and '/actuator/shoulder' in review['feedback']['governing_criterion']['name']
        and review['feedback']['governing_criterion']['utilization']>1
        and not review['feedback']['whole_product_pass_available']})
    column=json.loads((root/'examples/advanced/column.case.json').read_text(encoding='utf-8'))
    column['model']['path']=str(root/'examples/advanced/column.step')
    fixed=copy.deepcopy(column['loads'][0]);fixed.update(name='fixed-compression',total_force_n=[-20.,0.,0.],scalable=False)
    column['loads'].append(fixed)
    write_json(out/'column.case.json',column)
    eigen=analyze_case(out/'column.case.json',out/'column',ccx=ccx,timeout=timeout,preview=False,predict_capacity=False,storage='full')
    reference=(np.pi**2*200000*(10000/12)/(4*300**2)-20)/100
    buckling=eigen.get('assessment',{}).get('buckling',{})
    checks.append({'case':'capacity-off-preserves-requested-fixed-prestress-buckling','passed':eigen['status']!='invalid'
        and buckling.get('mesh_converged') is True
        and abs(buckling['lowest_positive_load_factor']/reference-1)<=.03
        and all(Path(l['directory'],'buckling.inp').is_file() for l in eigen['levels'])
        and not eigen['assessment']['conditional_body_limit']['available']})
    joint_context=out/'joint-context.json'
    write_json(joint_context,{'question':'Does the task displacement include the declared joint and link flexibility?',
        'scope':'Posed mathematical two-link tree, explicit scalar joint stiffness and link FEM.',
        'assumptions':['Prescribed spring and link constants; fixed/full field transfer and small-response screens remain.'],
        'not_assessed':['Physical calibration, coupled continuum, actual drive/mount and product qualification.']})
    for name,status in [('compliant-arm','pass_under_stated_model'),('compliant-arm-failure','fail_under_stated_model'),('compliant-arm-large-motion','indeterminate')]:
        case=json.loads((root/f'examples/robots/{name}.robot.json').read_text(encoding='utf-8'))
        case['model']['path']=str(root/'examples/robots'/case['model']['path'])
        for component in case['components']:component['case_path']=str((root/'examples/robots'/component['case_path']).resolve())
        write_json(out/f'{name}.json',case)
        review=design_check(out/f'{name}.json',out/name,context_path=joint_context,ccx=ccx,timeout=timeout,budget_seconds=timeout,preview=False)
        solved=json.loads(Path(review['result']['path']).read_text(encoding='utf-8'))
        checks.append({'case':name+'-capacity-off-preserves-task-and-all-auxiliary-fields','passed':review['execution']['state']=='completed'
            and solved['status']==status and not solved['conditional_payload_limit']['available']
            and all(p['task_probe_assessment']['payload_scale_limit'] is None
                and not p['task_probe_assessment']['conditional_limit_eligible']
                and all(not component['analysis_options']['predict_capacity']
                    and component['analysis_options']['require_fixed_response']
                    and all(Path(l['directory'],'fixed-results.json').is_file() for l in component['levels'])
                    for component in p['components']) for p in solved['poses'])})
    report={'passed':all(c['passed'] for c in checks),'checks':checks,
            'meaning':'Real numerical entry/iteration checks with expected failures; no physical product qualification.'}
    write_json(out/'validation.json',report)
    return report
