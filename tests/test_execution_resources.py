import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from simplecae.execution import hardware_snapshot, cost_projection
from simplecae.hotspot import mesh_sensitivity
from simplecae.solver import native_work


def test_snapshot_unknown_memory_is_not_zero_capacity():
    r=hardware_snapshot()
    assert r['logical_cpus'] is None or r['logical_cpus']>=1
    assert r['available_memory_bytes'] is None or r['available_memory_bytes']>0


def test_cpu_observation_never_spawns_an_unrelated_process(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("hardware observation must not launch a subprocess")
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("platform.processor", forbidden)
    snapshot = hardware_snapshot()
    assert isinstance(snapshot["processor"], str)
    from simplecae.parallel import hardware_identity
    assert hardware_identity()["processor"] == snapshot["processor"]


def test_empirical_estimate_is_advisory_and_uses_actual_completed_work():
    mesh={'node_count':200,'element_count':70}
    assert cost_projection(mesh,[])['estimated_native_seconds'] is None
    levels=[{'mesh':{'node_count':50},'solver':{'elapsed_seconds':5}},
            {'mesh':{'node_count':100},'solver':{'elapsed_seconds':20}}]
    before=copy.deepcopy(levels)
    r=cost_projection(mesh,levels)
    assert r['estimated_native_seconds']==pytest.approx(80)
    assert not r['estimate_is_guarantee'] and levels==before
    assert cost_projection(mesh,[{'mesh':{'node_count':50},'solver':{'elapsed_seconds':float('nan')}}])['estimated_native_seconds'] is None


def test_native_requested_threads_not_substituted_for_observed(tmp_path):
    log='number of equations\n 20\nNumber of contact spring elements=123\nFactoring the system of equations'
    assert native_work(log,tmp_path)['spooles_reported_threads']==[]
    (tmp_path/'spooles.out').write_text('Using 2 threads\nUsing 2 threads\n')
    r=native_work(log,tmp_path)
    assert r['spooles_reported_threads']==[2] and r['equations']==20
    assert r['maximum_contact_spring_count']==123 and r['factorization_count']==1


def test_growing_peak_with_good_elements_is_not_automatically_accepted_or_called_singular():
    r={'case':{'mesh':{}},'levels':[{'mesh_size_mm':h,'results':{
        'max_von_mises_mpa':s,'max_displacement_mm':.1,'peak_element_centroid_mm':[0,0,0],
        'peak_mesh_quality':{'minimum_signed_inverse_condition_number':.8}}}
        for h,s in [(4,7),(3,9),(2,12)]]}
    before=copy.deepcopy(r)
    d=mesh_sensitivity(r)
    assert d['cause']=='unresolved' and d['displacement_stable']
    assert [p['max_von_mises_mpa'] for p in d['peaks']]==[7,9,12]
    assert r==before
    r['levels'][1]['results']['max_von_mises_mpa']=7
    r['levels'][2]['results']['max_von_mises_mpa']=7
    assert mesh_sensitivity(r) is None


def test_auto_shares_total_deadline_and_explicit_timeout_still_means_cap(tmp_path,monkeypatch):
    import importlib
    from test_design_check import files
    module=importlib.import_module('simplecae.design_check')
    real=subprocess.Popen
    commands=[]
    def worker(command,**options):
        if '--out' not in command:return real(command,**options)
        commands.append(command)
        return real([sys.executable,'-c','pass'],**options)
    monkeypatch.setattr(module.subprocess,'Popen',worker)
    monkeypatch.setenv('SIMPLECAE_SOLVER_THREADS','1')
    case,context=files(tmp_path)
    for name,timeout,expected in [('auto','auto',7),('fixed',2,2)]:
        r=module.design_check(case,tmp_path/name,context_path=context,timeout=timeout,budget_seconds=7)
        cmd=commands[-1]
        assert float(cmd[cmd.index('--timeout')+1])==expected
        assert r['resource_plan']['timeout_policy']==('shared_total_budget' if name=='auto' else 'explicit_per_solve_cap')
        assert r['feedback']['conditional_model_pass'] is None


def test_explicit_parallel_build_still_uses_full_worker_and_result_gates(tmp_path,monkeypatch):
    import importlib
    from test_design_check import files
    module=importlib.import_module('simplecae.design_check')
    real=subprocess.Popen;seen=[]
    def worker(command,**options):
        seen.append(command)
        return real([sys.executable,'-c','pass'],**options)
    monkeypatch.setattr(module.subprocess,'Popen',worker)
    monkeypatch.setattr('simplecae.solver.os.cpu_count',lambda:4)
    monkeypatch.setenv('SIMPLECAE_SOLVER_THREADS','2')
    c,ctx=files(tmp_path);binary=tmp_path/'explicit.exe';binary.write_bytes(b'not run')
    r=module.design_check(c,tmp_path/'out',context_path=ctx,ccx=binary)
    assert '--ccx' in seen[0]
    assert r['resource_plan']['requested_threads']==2
    assert r['feedback']['conditional_model_pass'] is None
    assert r['feedback']['valid_for_comparison'] is False
