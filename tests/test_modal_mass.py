import copy
import numpy as np
import pytest
from test_modal_solver import beam,solve
from simplecae.modal_mass import compile_masses
from simplecae.geometry import make_mesh


def attachment():
    return {'name':'tip-mass','mass_kg':.02,'selector':{'type':'plane','axis':'x','position_mm':100},
            'basis':'Prescribed nonstructural distributed tip mass for a beam reference; no remote offset'}


def test_native_attached_mass_changes_modes_and_passes_independent_matrix_audit(beam):
    _,bare,_,_=solve(beam,count=4,label='bare')
    beam[0]['attached_masses']=[attachment()]
    mesh,loaded,audit,path=solve(beam,count=4,label='loaded')
    assert loaded[2][0]<bare[2][0]
    expected=np.sqrt(3*2e9*(.01*.006**3/12)/(.1**3)/(.02+.236*.0072))/(2*np.pi)
    assert loaded[2][0]==pytest.approx(expected,rel=.04)
    assert audit['passed'],audit
    assert audit['attached_mass_kg']==pytest.approx(.02)
    assert audit['total_mass_kg']==pytest.approx(.0272)
    assert audit['geometric_mass_kg']==pytest.approx(.0072)
    assert audit['attached_mass_reports'][0]['center_mm']==pytest.approx([100,5,3])
    assert '*ELEMENT,TYPE=MASS' in path.read_text()
    assert all(m>0 for m in mesh[-1]['attached_nodal_mass_kg'].values())
    damaged=copy.deepcopy(mesh);damaged[-1]['attached_nodal_mass_kg']={}
    from simplecae.modal_solver import audit as audit_again
    assert not audit_again(path.parent,beam[0]['material'],damaged,loaded)['passed']


def test_mass_cannot_be_hidden_on_a_fixed_support(beam):
    case,directory=beam;case['attached_masses']=[attachment()]
    case['attached_masses'][0]['selector']['position_mm']=0
    mesh=make_mesh(case,5,directory)
    with pytest.raises(ValueError,match='restrained'):compile_masses(case,mesh,directory)


def test_mass_is_frozen_in_comparison_contract(beam):
    from test_modal import case_file
    from simplecae.case import write_json
    from simplecae.modal import read_case
    p,c=case_file(beam);c['attached_masses']=[attachment()];write_json(p,c)
    accepted=read_case(p);assert accepted['attached_masses'][0]['mass_kg']==.02
    for field,value in [('mass_kg',-1),('mass_kg',0),('basis','')]:
        bad=copy.deepcopy(c);bad['attached_masses'][0][field]=value;write_json(p,bad)
        with pytest.raises(ValueError):read_case(p)
