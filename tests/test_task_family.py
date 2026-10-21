import pytest
from simplecae.task_family import family_status,render_family


def cases(lower='pass_under_stated_model',upper='pass_under_stated_model',nominal='not_run'):
    return [{'name':'nominal','analysis_required':False,'status':nominal,'normal_force_per_finger_n':16},
            {'name':'lower_force','analysis_required':True,'status':lower,'normal_force_per_finger_n':13},
            {'name':'upper_force','analysis_required':True,'status':upper,'normal_force_per_finger_n':19}]


@pytest.mark.parametrize('lower,upper,expected',[
 ('pass_under_stated_model','pass_under_stated_model','pass_under_stated_model'),
 ('fail_under_stated_model','pass_under_stated_model','fail_under_stated_model'),
 ('pass_under_stated_model','fail_under_stated_model','fail_under_stated_model'),
 ('indeterminate','fail_under_stated_model','indeterminate'),
 ('invalid','pass_under_stated_model','invalid'),
 ('not_run','pass_under_stated_model','indeterminate')])
def test_both_required_endpoints_control_family_status(lower,upper,expected):
    assert family_status(cases(lower,upper))==expected


def test_known_contact_loss_never_becomes_favorable_family_result():
    assert family_status(cases(),True)=='fail_under_stated_model'
    assert family_status(cases('indeterminate'),True)=='indeterminate'
    assert family_status([])=='invalid'


def test_computed_optional_reference_failure_cannot_be_hidden():
    assert family_status(cases(nominal='fail_under_stated_model'))=='fail_under_stated_model'
    assert family_status(cases(nominal='invalid'))=='invalid'
    assert family_status(cases(nominal='indeterminate'))=='indeterminate'


def test_rendered_family_explains_actual_interval_and_unverified_measurement(tmp_path):
    r={'status':'pass_under_stated_model','cases':cases(),'known_failures':[],
       'force_budget':{'measured_hold_interval_n':[15,17],'absolute_error_n':2,'lower_normal_force_n':13,'upper_normal_force_n':19,'measurement_conditions_verified':False}}
    render_family(r,tmp_path);text=(tmp_path/'task-family.html').read_text(encoding='utf-8')
    assert '13–19 N' in text and '仍未实物验证' in text and '参考输入，未求解' in text and '屈曲' in text


def test_public_one_command_runs_both_real_rigid_endpoints_and_retains_nominal(tmp_path):
    from test_force_envelope import measured_task
    from simplecae.task_family import analyze_gripper_task
    _,path=measured_task(tmp_path)
    r=analyze_gripper_task(path,tmp_path/'family',preview=False)
    from simplecae.schemas import check_contract
    check_contract(r,'task-family')
    assert r['status']=='pass_under_stated_model'
    assert [(c['name'],c['status']) for c in r['cases']]==[('nominal','not_run'),('lower_force','pass_under_stated_model'),('upper_force','pass_under_stated_model')]
    assert not r['conditional_product_capacity_available'] and r['comparison_margin'] is None
    assert all(not c['physical_conditions_verified'] for c in r['cases'] if c.get('result_relative_path'))


def test_family_source_change_between_endpoints_is_not_mixed_into_a_pass(tmp_path):
    from test_force_envelope import measured_task
    from simplecae.task_family import analyze_gripper_task
    _,path=measured_task(tmp_path)
    def progress(event):
        if event['stage']=='force_endpoint' and event['name']=='upper_force':
            robot=tmp_path/'gripper.urdf';robot.write_text(robot.read_text(encoding='utf-8')+'\n<!--revision changed-->')
    r=analyze_gripper_task(path,tmp_path/'family',preview=False,progress=progress)
    assert r['status']=='invalid' and 'source changed' in r['error']
    assert r['cases'][1]['status']=='pass_under_stated_model' and r['cases'][2]['status']=='not_run'


def test_one_command_exposes_uncertainty_contact_loss_as_known_failure(tmp_path):
    from test_force_envelope import measured_task
    from simplecae.case import write_json
    from simplecae.task_family import analyze_gripper_task
    task,path=measured_task(tmp_path);task['force_measurement']['absolute_error_n']=16;write_json(path,task)
    r=analyze_gripper_task(path,tmp_path/'family',preview=False)
    assert r['status']=='fail_under_stated_model' and r['known_failures'][0]['criterion']=='force_lower_bound'
    assert r['comparison_margin'] is None and not r['conditional_product_capacity_available']


def test_explicit_object_couple_reaches_task_compiler_grip_demand(tmp_path):
    import json
    from pathlib import Path
    from simplecae.task_family import analyze_gripper_task
    from simplecae.case import write_json
    root=Path(__file__).resolve().parents[1];task=json.loads((root/'examples/quickstart/gripper-task.json').read_text(encoding='utf-8'))
    task['model_path']=str(root/'examples/quickstart/gripper.urdf')
    task['additional_robot_loads']=[{'name':'object_twist','link':'fixed_finger','force_n':[0,0,0],'moment_n_m':[.1,0,0],'position_m':[0,0,.035],'scalable':True}]
    task['workpiece_load_names']=['object_twist'];p=tmp_path/'task.json';write_json(p,task)
    r=analyze_gripper_task(p,tmp_path/'out',preview=False)
    assert r['status']=='fail_under_stated_model'
    for c in r['cases']:
        if c['analysis_required']:
            result=json.loads((tmp_path/'out'/c['result_relative_path']).read_text(encoding='utf-8'))
            assert all(not p['grasp_assessment']['feasible'] for p in result['poses'])
