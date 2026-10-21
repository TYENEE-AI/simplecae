"""Synchronous typed file API for agent orchestration; no code execution endpoint."""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from pathlib import Path
import json
from .schemas import check_contract

# The bounded orchestration API supplements, rather than changes, analyze_case.
from .design_check import design_check, compare_design_checks
from .use_plan import prepare_plan, read_plan
from .task import start_task, run_task_check, record_task_check, task_status, brief_task_status


def check_gripper_task(path):
    from copy import deepcopy
    from .grasp import compile_gripper_task
    path=Path(path).resolve();task=json.loads(path.read_text(encoding='utf-8-sig'));check_contract(task,'gripper-task')
    base=deepcopy(task)
    if 'force_measurement' in base:
        from .force_envelope import force_bounds
        force_bounds(base.pop('force_measurement'),base['normal_force_per_finger_n'])
    case=compile_gripper_task(base,path);check_contract(case,'case')
    model=Path(case['model']['path'])
    if not model.is_file() or model.suffix.lower()!='.urdf':raise ValueError('gripper task must reference an existing URDF')
    from .robot import read_urdf
    read_urdf(model,case['model'].get('package_roots',{}),case.get('massless_links',[]))
    from .case import load_case
    for component in case['components']:load_case(Path(component['case_path']))
    return task


def check_case(path):
    path=Path(path).resolve();header=json.loads(path.read_text(encoding='utf-8-sig'));check_contract(header)
    version=header.get('schema_version')
    if version in ('fatigue-data-1.0', 'creep-data-1.0'):
        from .durability import read_case
        return read_case(path)
    if version=='motion-loads-1.0':
        from .motion import read_case
        return read_case(path)
    if version=='modal-solid-1.0':
        from .modal import read_case
        return read_case(path)
    if version=='thermal-solid-1.0':
        from .thermal_solid import read_case
        return read_case(path)
    if version=='thermal-network-1.0':
        from .thermal_network import validate
        return validate(header)
    if version=='robot-1.0':
        from .robot import load_robot_case,read_urdf
        case=load_robot_case(path)
        read_urdf(case['model']['path'],case['model']['package_roots'],case.get('massless_links',[]))
        from .case import load_case
        for component in case.get('components',[]):load_case(Path(component['case_path']))
        return case
    if version=='assembly-1.0':
        from .assembly import load_assembly_case
        return load_assembly_case(path)
    from .case import load_case
    return load_case(path)


def analyze_case(path,out,*,ccx=None,timeout=DEFAULT_NATIVE_TIMEOUT,preview=True,progress=None,cache=None,reuse_levels=None,predict_capacity=True,storage='compact'):
    from .observations import Observation
    observation=Observation(out,progress)
    # Never attach new telemetry to an existing result after a rejected rerun.
    fresh=not Path(out).exists();completed=False
    try:
        result=_analyze_case(path,out,ccx=ccx,timeout=timeout,preview=preview,progress=observation.event,
                             cache=cache,reuse_levels=reuse_levels,predict_capacity=predict_capacity,
                             storage=storage,observation=observation)
        completed=result.get('status')!='invalid'
        if not completed:
            result['diagnostic']={'code':'analysis_invalid','retryable_unchanged':False,
                'next_action':'inspect_retained_diagnostics','fields':[],
                'details':{'result_path':str(Path(out).resolve()/'result.json')}}
        return result
    finally:
        if fresh:
            import sys
            original_error=sys.exc_info()[1]
            try:observation.finish(completed)
            except OSError as observation_error:
                if original_error is None:raise
                original_error.add_note(f'Execution observation could not be saved: {observation_error}')


def _analyze_case(path,out,*,ccx,timeout,preview,progress,cache,reuse_levels,predict_capacity,storage,observation):
    from .retention import validate_storage, retain_output
    validate_storage(storage)
    case=check_case(path);version=case['schema_version']
    observation.mark('analysis')
    if version in ('fatigue-data-1.0', 'creep-data-1.0'):
        if cache or reuse_levels:
            raise ValueError('Durability data checks do not use solver caches')
        from .durability import analyze as analyze_durability
        result=analyze_durability(path,out,progress)
    elif version=='motion-loads-1.0':
        if cache or reuse_levels:
            raise ValueError('Motion load cache/reuse is unsupported')
        from .motion import analyze as analyze_motion
        result=analyze_motion(path,out,progress)
    elif version=='modal-solid-1.0':
        if cache or reuse_levels:
            raise ValueError('Modal cache/reuse is unsupported')
        from .modal import analyze as analyze_modal
        result=analyze_modal(path,out,ccx,timeout,progress=progress)
    elif version=='thermal-solid-1.0':
        if cache or reuse_levels:
            raise ValueError('Solid thermal cache/reuse is unsupported')
        from .thermal_solid import analyze as analyze_thermal
        result=analyze_thermal(path,out,ccx,timeout,progress=progress)
    elif version=='thermal-network-1.0':
        if cache or reuse_levels:
            raise ValueError('Thermal network cache/reuse is unsupported')
        from .thermal_network import analyze as analyze_thermal
        result=analyze_thermal(path,out)
    elif version=='robot-1.0':
        from .robot import analyze_robot
        result=analyze_robot(Path(path),Path(out),ccx,timeout,preview,progress=progress,cache=cache,reuse_levels=reuse_levels,predict_capacity=predict_capacity)
    elif version=='assembly-1.0':
        from .assembly import analyze_assembly
        result=analyze_assembly(Path(path),Path(out),ccx,timeout,preview,progress=progress,cache=cache,reuse_levels=reuse_levels,predict_capacity=predict_capacity)
    else:
        from .workflow import analyze
        result=analyze(Path(path),Path(out),ccx,timeout,preview,progress=progress,cache=cache,reuse_levels=reuse_levels,predict_capacity=predict_capacity)
    observation.mark('retention')
    retain_output(out, storage)
    return result
