"""Regression for CCX missing sub-unit buckling factors (upstream #74)."""
import copy
import math
import numpy as np
import pytest
from simplecae.benchmarks import bar_case
from simplecae.geometry import session,make_mesh
from simplecae.buckling import run_buckling,write_buckling_deck
from simplecae.solver import find_ccx
from simplecae.level_cache import verify_buckling


def test_native_supercritical_load_retains_lowest_mode_and_reuse(tmp_path):
    try:ccx=find_ccx()
    except FileNotFoundError:pytest.skip('Native CalculiX required')
    p=tmp_path/'column.step'
    with session() as g:
        g.model.occ.addBox(0,-5,-5,300,10,10);g.model.occ.synchronize();g.write(str(p))
    c=bar_case('column',[-75*9.80665,0,0],[5,4,3]);c['schema_version']='2.0'
    c['model']={'path':str(p),'expected_bbox_mm':[[0,-5,-5],[300,5,5]]}
    c['material'].update(youngs_modulus_mpa=5000,poisson_ratio=0.)
    c['loads'][0]['selector']['position_mm']=300
    c['buckling']={'enabled':True,'modes':3,'safety_factor':2}
    before=copy.deepcopy(c);out=tmp_path/'level';out.mkdir()
    mesh=make_mesh(c,5,out);r=run_buckling(c,mesh,out,ccx,120)
    expected=math.pi**2*5000*(10**4/12)/(4*300**2)/(75*9.80665)
    assert r['lowest_positive_factor']==pytest.approx(expected,rel=.05)
    assert r['reference_normalization_verified'] and r['normalization_attempts']>=2
    assert c==before
    assert verify_buckling(c,mesh,out,r)==r
    normalized=sorted(out.glob('buckling-normalized-*.inp'))[-1]
    normalized.write_text(normalized.read_text()+'** tampered\n')
    with pytest.raises(ValueError,match='differs'):verify_buckling(c,mesh,out,r)


def test_reference_scale_leaves_fixed_preload_unchanged(tmp_path,monkeypatch):
    from simplecae import buckling
    monkeypatch.setattr(buckling,'write_deck',lambda c,m,p:p.write_text('*NODE\n1,0,0,0\n*STEP\n'))
    mesh=({},{},[],{1:np.array([-12.,0,0])},{'fixed_nodal_forces':{'1':[-2.,0,0]}})
    path=tmp_path/'load.inp';write_buckling_deck({'buckling':{'modes':3}},mesh,path,.01)
    text=path.read_text();static,eigen=text.split('*BUCKLE')
    assert '1,1,-2' in static and '1,1,-0.1' in eigen
