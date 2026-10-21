"""Local peaks cannot disappear behind a larger, converged global maximum."""
import numpy as np
import pytest
from simplecae.stress_regions import validate_regions, region_context, summarize_regions, compare_regions


def mesh():
    # Two separate quadratic tetrahedral connectivity sets, used only for selection.
    corners = np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],float)
    mid = np.array([(corners[i]+corners[j])/2 for i,j in ((0,1),(1,2),(0,2),(0,3),(1,3),(2,3))])
    points = np.vstack([corners,mid])
    coords={i+1:p for i,p in enumerate(np.vstack([points,points+[10,0,0]]))}
    tets={1:list(range(1,11)),2:list(range(11,21))}
    meta={'body_reports':[{'name':'left','material_id':'A'},{'name':'right','material_id':'B'}],
          'element_material':{'1':'A','2':'B'}}
    return coords,tets,[],{},meta


def test_selects_all_raw_points_and_does_not_average():
    spec={'name':'joint','body':'left','min_mm':[-.1,-.1,-.1],'max_mm':[.1,.1,.1]}
    keys=[(e,i) for e in (1,2) for i in range(1,5)]
    regions=region_context({'stress_regions':[spec]},mesh(),keys)
    stress=np.zeros((8,6));stress[3,0]=19;stress[7,0]=99
    ctx={'materials':{'A':{'failure_criterion':'von_mises_yield','yield_strength_mpa':20},
                      'B':{'failure_criterion':'von_mises_yield','yield_strength_mpa':20}},
         'element_material':{'1':'A','2':'B'},'safety_factor':2}
    result=summarize_regions(stress,keys,ctx,regions)[0]
    assert result['integration_point_count']==4
    assert result['max_von_mises_mpa']==19
    assert result['peak']['integration_point']==4
    assert result['strength_utilization']==1.9
    assert result['peak']['element_centroid_mm']==[.25,.25,.25]


def test_empty_or_incomplete_region_is_not_success():
    case={'stress_regions':[{'name':'void','min_mm':[20,20,20],'max_mm':[21,21,21]}]}
    with pytest.raises(ValueError,match='no intersecting'):
        region_context(case,mesh(),[])
    case['stress_regions'][0].update(min_mm=[-1,-1,-1],max_mm=[2,2,2])
    with pytest.raises(ValueError,match='complete C3D10'):
        region_context(case,mesh(),[(1,1)])


@pytest.mark.parametrize('change',[
    {'name':''}, {'min_mm':[float('nan'),0,0]}, {'max_mm':[0,1,1]},
    {'body':'missing'}, {'tolerance':.5},
])
def test_invalid_region_rejected(change):
    spec={'name':'root','min_mm':[0,0,0],'max_mm':[1,1,1]}
    spec.update(change)
    with pytest.raises((ValueError,TypeError)):
        validate_regions({'stress_regions':[spec]})


def record(stress):
    return {'name':'root','max_von_mises_mpa':stress,'strength_utilization':stress/100,
            'peak':{'element':1,'integration_point':1,'element_centroid_mm':[0,0,0]}}


def test_local_comparison_uses_existing_tolerance_and_requires_coverage():
    pairs=compare_regions([record(10)],[record(15)],{'root'},.1)
    assert not pairs['root']['converged']
    with pytest.raises(ValueError,match='coverage'):
        compare_regions([], [record(15)], {'root'}, .1)


def test_global_pass_does_not_mask_unconverged_region():
    from test_signals import result
    from simplecae.assessment import assess
    r=result()
    c=r['case']
    c['stress_regions']=[{'name':'root','min_mm':[0,0,0],'max_mm':[1,1,1]}]
    levels=r['levels']
    for item,stress in zip(levels,[1,1.2,1.5]):
        item['results']['stress_regions']=[record(stress)]
    assessment=assess(c,levels,predict_capacity=False)
    assert assessment['status']=='indeterminate'
    assert assessment['criterion_assessments']['strength']['status']=='indeterminate'
    assert assessment['criterion_assessments']['stiffness']['status']=='pass_under_stated_model'


def test_signal_rejects_missing_regional_evidence_in_apparent_pass():
    from test_signals import result
    from simplecae.signals import design_signal
    r=result()
    r['case']['stress_regions']=[{'name':'root','min_mm':[0,0,0],'max_mm':[1,1,1]}]
    signal=design_signal(r)
    assert not signal['valid_for_comparison']
    assert signal['feasible_under_stated_model'] is None
