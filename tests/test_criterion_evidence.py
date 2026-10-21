import copy
from simplecae.assessment import assess
from simplecae.benchmarks import bar_case
from simplecae.signals import design_signal
from simplecae.schemas import check_contract

def test_converged_displacement_failure_is_visible_while_peak_stress_diverges():
    c=bar_case('unused',[-100,0,0],[5,4,3]);c['criteria']['max_displacement_mm']=.01
    levels=[]
    for u,s in [(0.0198,20),(0.0200,30),(0.0201,45)]:
        levels.append({'mesh':{'geometry':{'solid_count':1},'mesh_volume_mm3':1000,'mass_kg':None},
            'results':{'max_displacement_mm':u,'max_von_mises_mpa':s,'max_strain_norm':.0002,
                'minimum_bbox_extent_mm':10,'force_balance_relative_error':0.,'moment_balance_relative_error':0.}})
    a=assess(c,levels)
    assert a['status']=='indeterminate'
    assert a['criterion_assessments']['stiffness']['status']=='fail_under_stated_model'
    assert a['criterion_assessments']['strength']['status']=='indeterminate'
    r={'schema_version':'2.0','analysis':'linear_static','case':c,'levels':levels,'assessment':a,'status':a['status']}
    s=design_signal(r);check_contract(s,'signal')
    assert s['valid_for_comparison'] is False and s['bottleneck_margin'] is None
    assert any(f['kind']=='confirmed_criterion_failure' and f['scope']=='stiffness' for f in s['feedback'])
    assert not a['conditional_body_limit']['available']

def test_failed_equilibrium_cannot_produce_a_confirmed_criterion_pass_or_failure():
    c=bar_case('unused',[-100,0,0],[5,4,3])
    levels=[{'results':{'max_displacement_mm':.1,'max_von_mises_mpa':1,'max_strain_norm':.0002,
        'minimum_bbox_extent_mm':10,'force_balance_relative_error':.1,'moment_balance_relative_error':0.}} for _ in range(3)]
    a=assess(c,levels)
    assert a['status']=='invalid'
    assert all(e['status']=='invalid' for e in a['criterion_assessments'].values())
