import copy
import pytest
from test_grasp_logic import task,robot_file
from simplecae.force_envelope import force_bounds,compile_force_envelope
from simplecae.case import write_json
from simplecae.api import analyze_case,check_case

def measured_task(tmp_path):
    robot_file(tmp_path/'gripper.urdf');t=task();t['normal_force_per_finger_n']=16
    t['force_measurement']={'measured_hold_interval_n':[15,17],'absolute_error_n':2,'error_verified':False,'holding_window_verified':False}
    p=tmp_path/'task.json';write_json(p,t);return t,p

def test_measured_window_and_sensor_error_produce_true_force_endpoints_without_double_counting(tmp_path):
    t,p=measured_task(tmp_path);r=compile_force_envelope(t,p,tmp_path/'cases')
    assert r['force_budget']['lower_normal_force_n']==13 and r['force_budget']['upper_normal_force_n']==19
    byname={c['name']:c for c in r['cases']}
    assert not byname['nominal']['analysis_required'] and byname['lower_force']['analysis_required'] and byname['upper_force']['analysis_required']
    for name,expected in [('lower_force',13),('upper_force',19),('nominal',16)]:
        c=check_case(byname[name]['case_path']);loads={l['name']:l for l in c['loads']}
        assert loads['normal_0']['force_n'][0]==-expected and loads['normal_1']['force_n'][0]==expected
        assert c['grasp']['conditions']['force_verified'] is False
        assert c['provenance']['parameters']['true_normal_force_n']==expected
    assert r['analysis_performed'] is False

def test_cross_drive_provenance_keeps_original_absolute_source_and_hash(tmp_path,monkeypatch):
    import json
    from simplecae.case import sha256
    t,p=measured_task(tmp_path)
    def different_drive(*args):raise ValueError("path is on mount 'C:', start on mount 'F:'")
    monkeypatch.setattr('simplecae.force_envelope.os.path.relpath',different_drive)
    r=compile_force_envelope(t,p,tmp_path/'out')
    saved=json.loads(open(r['force_envelope'],encoding='utf-8').read())
    assert saved['source_task']==p.resolve().as_posix()
    assert saved['source_task_sha256']==sha256(p)
    assert [c['normal_force_per_finger_n'] for c in r['cases']]==[16,13,19]

def test_lower_force_can_govern_drive_with_counteracting_fixed_loads_so_both_are_required(tmp_path):
    t,p=measured_task(tmp_path);t['additional_robot_loads']=[{'name':'counteracting','link':'right','force_n':[-40,0,0],
        'position_m':[0,0,0],'frame':'link','scalable':False}];write_json(p,t)
    compiled=compile_force_envelope(t,p,tmp_path/'cases');efforts={}
    for c in compiled['cases']:
        if c['analysis_required']:
            r=analyze_case(c['case_path'],tmp_path/c['name'],preview=False)
            efforts[c['name']]=abs(r['poses'][0]['actuator_efforts']['slide']['holding_effort'])
    assert efforts==pytest.approx({'lower_force':27,'upper_force':21})

def test_uncertainty_covering_zero_contact_is_exposed_not_clamped_to_a_fake_positive_minimum(tmp_path):
    t,p=measured_task(tmp_path);t['force_measurement']['absolute_error_n']=16;write_json(p,t)
    r=compile_force_envelope(t,p,tmp_path/'out')
    assert r['force_budget']['contact_not_assured'] and r['force_budget']['lower_normal_force_n']==0
    assert not any(c['name']=='lower_force' for c in r['cases'])
    assert 'Contact loss' in r['meaning']

def test_unsaved_source_change_or_unreferenced_verified_budget_cannot_be_silently_accepted(tmp_path):
    t,p=measured_task(tmp_path);t['force_measurement']['absolute_error_n']=1
    with pytest.raises(ValueError,match='saved source'):compile_force_envelope(t,p,tmp_path/'out')
    spec={'measured_hold_interval_n':[15,17],'absolute_error_n':2,'error_verified':True,'holding_window_verified':True}
    with pytest.raises(ValueError,match='reference'):force_bounds(spec,16)

@pytest.mark.parametrize('bad',[
    {'measured_hold_interval_n':[17,15],'absolute_error_n':2},
    {'measured_hold_interval_n':[15,17],'absolute_error_n':-1},
    {'measured_hold_interval_n':[15,17],'absolute_error_n':2,'error_verified':'yes'}])
def test_invalid_measurement_budget_is_actionable(bad):
    with pytest.raises(ValueError):force_bounds(bad,16)
