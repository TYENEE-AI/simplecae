"""Compile measured-force uncertainty into explicit analysis cases, never a rating."""
from pathlib import Path
from copy import deepcopy
import json,os
from .case import keys,number,write_json,sha256

def force_bounds(spec,nominal):
    keys(spec,['measured_hold_interval_n','absolute_error_n','error_verified','holding_window_verified','reference'],
         ['measured_hold_interval_n','absolute_error_n'],'force measurement')
    interval=spec['measured_hold_interval_n']
    if not isinstance(interval,list) or len(interval)!=2:raise ValueError('measured_hold_interval_n needs [low,high] in N')
    low,high=[number(v,'measured holding force',True) for v in interval]
    if high<low:raise ValueError('measured holding interval must be ordered')
    error=number(spec['absolute_error_n'],'absolute force error')
    if error<0:raise ValueError('absolute force error must be nonnegative')
    if not low<=number(nominal,'nominal force',True)<=high:raise ValueError('nominal measured command must lie in the holding interval')
    for k in ('error_verified','holding_window_verified'):
        if k in spec and type(spec[k]) is not bool:raise ValueError(k+' must be boolean')
    verified=spec.get('error_verified',False) and spec.get('holding_window_verified',False)
    if verified and (not isinstance(spec.get('reference'),str) or not spec['reference'].strip()):raise ValueError('verified force budget needs a measurement/holding-test reference')
    return {'measured_hold_interval_n':[low,high],'absolute_error_n':error,
            'raw_lower_bound_n':low-error,'lower_normal_force_n':max(0.,low-error),'upper_normal_force_n':high+error,
            'contact_not_assured':low-error<=0,'measurement_conditions_verified':bool(verified),
            'formula':'true force interval = [measured low - absolute error, measured high + absolute error]; normal contact cannot be negative',
            'reference':spec.get('reference'),'meaning':'Declared uncertainty bound, not measured or certified by CAD/the solver.'}

def compile_force_envelope(task,source,out):
    from .grasp import compile_gripper_task
    from .api import check_case
    source=Path(source).resolve();out=Path(out).resolve()
    if not source.is_file() or json.loads(source.read_text(encoding='utf-8-sig'))!=task:
        raise ValueError('force-envelope task must match its saved source JSON; save edits before compiling')
    if 'force_measurement' not in task:raise ValueError('force envelope requires explicit force_measurement')
    budget=force_bounds(task['force_measurement'],task['normal_force_per_finger_n'])
    base=deepcopy(task);base.pop('force_measurement');c=compile_gripper_task(base,source)
    out.mkdir(parents=True,exist_ok=False);cases=[]
    states=[('nominal',task['normal_force_per_finger_n'],False),('upper_force',budget['upper_normal_force_n'],True)]
    if not budget['contact_not_assured']:states.insert(1,('lower_force',budget['lower_normal_force_n'],True))
    for name,force,required in states:
        child=deepcopy(c);normal_names=set(child['grasp']['normal_load_names'])
        for load in child['loads']:
            if load['name'] in normal_names:
                import numpy as np
                direction=np.array(load['force_n']);direction/=np.linalg.norm(direction);load['force_n']=(direction*force).tolist()
        child['grasp']['conditions']['force_verified']=child['grasp']['conditions']['force_verified'] and budget['measurement_conditions_verified']
        child['provenance']['task_id']=str(task['task_id'])+'/'+name
        child['provenance']['parameters']={'force_state':name,'force_measurement':task['force_measurement'],'true_normal_force_n':force}
        explanation='Force-envelope endpoint: '+name+'. Both endpoints need structural/drive checks; minimum force governs friction assurance. Nominal force alone does not cover sensor/control uncertainty.'
        child['notes']=child['notes']+' '+explanation if isinstance(child['notes'],str) else {'original_notes':child['notes'],'force_envelope':explanation}
        path=out/(name+'.robot.json');write_json(path,child);check_case(path)
        cases.append({'name':name,'normal_force_per_finger_n':force,'analysis_required':required,'case_path':path.name,'case_sha256':sha256(path)})
    # Windows cannot express a relative filesystem path between different drives.
    # This is provenance data; retain the actual absolute source plus its hash.
    try:source_reference=os.path.relpath(source,out).replace('\\','/')
    except ValueError:source_reference=source.as_posix()
    manifest={'schema_version':'gripper-force-envelope-1.0','task_id':task['task_id'],
        'source_task':source_reference,'source_task_sha256':sha256(source),
        'force_budget':budget,'cases':cases,'analysis_performed':False,'whole_installation_rating_available':False,
        'complete_force_envelope_generated':not budget['contact_not_assured'],
        'scope':'Declared equal per-finger force interval at frozen poses. Analyze both endpoints for linear elastic/effort/contact criteria; no inferred nonlinear/buckling response between endpoints.',
        'required_action':'Contact loss is possible at the uncertainty lower bound; revise/verify the holding window and error budget. Upper-force analysis does not remove this gap.' if budget['contact_not_assured'] else 'Analyze required lower/upper cases then summarize. Nominal case is optional reference, not the worst case.'}
    path=out/'force-envelope.json';write_json(path,manifest)
    return {'force_envelope':str(path),'force_budget':budget,'cases':[dict(row,case_path=str(out/row['case_path'])) for row in cases],
            'meaning':manifest['required_action'],'analysis_performed':False}
