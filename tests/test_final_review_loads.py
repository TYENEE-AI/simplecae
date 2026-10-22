import json
import numpy as np
import pytest
from simplecae.loads import distribute_wrench
from simplecae.diagnostics import WorkflowError
from simplecae.benchmarks import bar_case
from simplecae.geometry import make_mesh


def patch():
    xyz={i:np.array([x,y,0.]) for i,(x,y) in enumerate([(-1,-1),(1,-1),(1,1),(-1,1)],1)}
    return xyz,{n:1. for n in xyz}


def test_remote_force_refused_but_forces_retained():
    xyz,weights=patch();report={}
    with pytest.raises(WorkflowError) as error:
        distribute_wrench(xyz,weights,[0,0,-49],[0,0,0],[2.1,0,0],diagnostics=report)
    assert error.value.diagnostic['code']=='opposite_sign_traction'
    assert report['opposite_fraction']==pytest.approx(1.1/4.2)
    assert len(report['nodes'])==4
    assert report['reverse_resultant_n'][2]>0
    assert report['reverse_bbox_mm'][0][0]==-1
    assert 'remote_application_point' in report['warnings']


def test_centroid_and_explicit_permission():
    xyz,weights=patch();report={}
    distribute_wrench(xyz,weights,[0,0,-49],[0,0,0],[0,0,0],diagnostics=report)
    assert report['opposite_fraction']==0 and not report['warnings']
    distribute_wrench(xyz,weights,[0,0,-49],[0,0,0],[2.1,0,0],allow_opposite_traction=True,diagnostics=report)
    assert report['assumptions'] and 'opposite_sign_traction' in report['warnings']


def test_bearing_feasibility_and_conservation():
    xyz,weights=patch();report={}
    with pytest.raises(WorkflowError,match='infeasible_bearing_distribution'):
        distribute_wrench(xyz,weights,[0,0,-49],[0,0,0],[2.1,0,0],distribution='bearing_only',diagnostics=report)
    assert report['opposite_fraction']==0 and report['moment_relative_residual']>.01
    forces,center,moment=distribute_wrench(xyz,weights,[0,0,-49],[0,0,0],[.4,0,0],distribution='bearing_only',diagnostics=report)
    assert all(f[2]<=0 for f in forces.values())
    assert sum(forces.values())==pytest.approx([0,0,-49])
    assert sum((np.cross(xyz[n]-center,f) for n,f in forces.items()))==pytest.approx(moment,abs=1e-7)
    assert report['moment_relative_residual']<1e-8


def test_refused_mesh_writes_load_evidence(tmp_path):
    from pathlib import Path
    step=Path(__file__).resolve().parents[1]/'examples/integration/cadgen-beam.step'
    c=bar_case(str(step.with_suffix('')),[0,0,-49],[4,3,2]);c['schema_version']='2.0'
    c['loads'][0]['application_point_mm']=[100,50,0]
    with pytest.raises(WorkflowError,match='opposite_sign_traction'):
        make_mesh(c,4,tmp_path)
    report=json.loads((tmp_path/'load_distribution.json').read_text())
    assert report['loads'][0]['opposite_fraction']>.2
    assert report['loads'][0]['nodes']
    assert not (tmp_path/'job.inp').exists()
