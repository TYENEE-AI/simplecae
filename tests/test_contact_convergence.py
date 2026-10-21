"""Strict contact controls and located rejection of native opening springs."""
from pathlib import Path
import pytest
from simplecae.contact import validate_control,steps,summarize,ContactValidityError
from simplecae.schemas import contracts


@pytest.mark.parametrize('value',[-1e-9,.002,True,float('nan')])
def test_contact_change_control_rejects_invalid_or_looser_values(value):
    with pytest.raises(ValueError):
        validate_control({'connections':[{'type':'frictionless_contact'}],
                          'contact_control':{'contact_change_relative_tolerance':value}})


def test_strict_active_contact_count_control_is_present_in_each_load_stage():
    c={'bolts':[{}],'contact_control':{}}
    b={'adjustment_node':99,'preload_n':200.}
    deck=steps(c,{}, {'connection_data':{'bolts':[b]}})
    assert deck.count('*CONTROLS,PARAMETERS=CONTACT')==3
    for i,line in enumerate(deck):
        if line=='*CONTROLS,PARAMETERS=CONTACT':
            assert float(deck[i+1].split(',')[0])==0
    assert deck.count('*END STEP')==3


def test_service_ramp_can_change_without_rewriting_preload_or_lock_history():
    c={'bolts':[{}],'contact_control':{'initial_increment':1.,'maximum_increment':1.,
        'service_initial_increment':.1,'service_maximum_increment':.2}}
    validate_control(dict(c,connections=[{'type':'frictionless_contact'}]))
    deck=steps(c,{}, {'connection_data':{'bolts':[{'adjustment_node':99,'preload_n':200.}]}})
    intervals=[list(map(float,deck[i+1].split(','))) for i,line in enumerate(deck) if line=='*STATIC,SOLVER=SPOOLES']
    assert [v[0] for v in intervals]==[1.,1.,.1]
    assert [v[3] for v in intervals]==[1.,1.,.2]
    assert deck.count('*END STEP')==3 and '*BOUNDARY,FIXED' in deck


def test_constant_lock_step_keeps_loads_and_checks_without_redundant_ramp():
    c={'bolts':[{}],'contact_control':{}}
    b={'adjustment_node':99,'preload_n':200.}
    deck=steps(c,{1:[5.,0.,-50.]},
               {'fixed_nodal_forces':{'1':[0.,0.,-2.]},'connection_data':{'bolts':[b]}})
    stages='\n'.join(deck).split('*END STEP')[:3]
    assert '99,1,2.000000000000e+02' in stages[0]
    assert '*BOUNDARY,FIXED\n99,1,1' in stages[1]
    assert '1,3,-2.000000000000e+00' in stages[1]
    assert '1,1,5.000000000000e+00' in stages[2]
    assert '*CONTACT PRINT' in stages[1] and '*NODE PRINT,NSET=BOLT_STATE' in stages[1]
    intervals=[list(map(float,deck[i+1].split(','))) for i,line in enumerate(deck) if line=='*STATIC,SOLVER=SPOOLES']
    assert intervals[0][0]==.1 and intervals[1][0]==1 and intervals[2][0]==.1


def test_timeout_retains_intermediate_progress_without_claiming_full_load(tmp_path):
    from simplecae.solver import timeout_diagnostic
    p=tmp_path/"job.inp"
    p.with_suffix(".sta").write_text(
        "SUMMARY\n1 1 1 8 0.1 0.1 0.1\n1 2 1 5 0.2 0.2 0.1\n")
    p.with_suffix(".solver.log").write_text(
        "number of equations\n123\nNumber of contact spring elements=200\n"
        "Factoring the system of equations\nNumber of contact spring elements=170\n"
        "Factoring the system of equations\nTIMEOUT\n")
    d=timeout_diagnostic(p,120)
    assert d["status"]=="timeout" and d["completed_progress"]["1"]["step_time"]==.2
    assert d["maximum_contact_spring_count"]==200 and d["last_contact_spring_count"]==170
    assert d["factorization_count"]==2 and p.with_suffix(".solver-diagnostic.json").is_file()


@pytest.mark.parametrize('control',[{'service_initial_increment':0},
    {'service_initial_increment':.3,'service_maximum_increment':.2},{'service_maximum_increment':2}])
def test_invalid_service_increment_override_is_rejected(control):
    with pytest.raises(ValueError):
        validate_control({'connections':[{'type':'frictionless_contact'}],'contact_control':control})


def test_explicit_legacy_tolerance_is_discoverable_and_not_above_native_default():
    schema=contracts()['case']['$defs']['assembly']['properties']['contact_control']
    field=schema['properties']['contact_change_relative_tolerance']
    assert field['minimum']==0 and field['maximum']==.001
    c={'connections':[{'type':'frictionless_contact'}],'contact_control':{'contact_change_relative_tolerance':.001}}
    validate_control(c)
    deck=steps(c,{}, {'connection_data':{}})
    i=deck.index('*CONTROLS,PARAMETERS=CONTACT')
    assert float(deck[i+1].split(',')[0])==.001


def test_native_negative_pressure_is_rejected_with_every_offending_location(tmp_path):
    p=tmp_path/'job.dat'
    # Values from the small native partial-opening reproduction. Keeping p=-k*g
    # is diagnostic evidence of the old active spring, not a permission to clip.
    p.write_text('relative contact displacement (x) time 1\n373 1 1.129696E-10 0 0\n'
                 '374 2 2.000000E-10 0 0\ncontact stress (x) time 1\n'
                 '373 1 -1.129696E-05 0 0\n374 2 -2.000000E-05 0 0\n')
    contact={'name':'opening-pad','normal':[1,0,0],'initial_gap_mm':0,
             'surfaces':{'slave':[[373,1],[374,2]]},'gap_samples':[],
             'normal_stiffness_n_mm3':100000.}
    with pytest.raises(ContactValidityError,match='tensile pressure') as caught:summarize(p,[contact])
    d=caught.value.diagnostic
    assert d['contact']=='opening-pad' and d['output_time']==1
    assert d['minimum_pressure_mpa']==-2e-5
    assert d['rejection_threshold_mpa']==-1e-7
    assert [s['element_id'] for s in d['offending_samples']]==[373,374]
    assert all(abs(s['nominal_linear_law_residual_mpa'])<1e-18 for s in d['offending_samples'])
    assert p.read_text().count('-1.129696E-05')==1
