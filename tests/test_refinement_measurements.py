import numpy as np
import pytest
from simplecae.local_mesh import measure_surfaces


def test_measured_local_sizes_use_the_selected_actual_surface_and_preserve_targets():
    records=[{'name':'pad','face_ids':[7],'target_size_mm':2.}]
    coords={1:[0,0,0],2:[3,0,0],3:[0,4,0],4:[50,0,0]}
    faces={7:[[1,2,3,99,98,97]],8:[[1,4,3,96,95,94]]}
    result=measure_surfaces(records,faces,coords)[0]
    assert result['target_size_mm']==2 and 'surface_mesh' not in records[0]
    measured=result['surface_mesh']
    assert measured['triangle_count']==1 and measured['corner_edge_mean_mm']==4
    assert measured['corner_edge_min_mm']==3 and measured['corner_edge_max_mm']==5
    assert measured['corner_edge_mean_to_target']==2
    moved={n:(np.array([-p[1],p[0],p[2]])+[17,-9,23]).tolist() for n,p in coords.items()}
    assert measure_surfaces(records,faces,moved)[0]['surface_mesh']==measured


def test_missing_surface_measurement_is_explicit_and_has_no_fabricated_size():
    report=measure_surfaces([{'face_ids':[9],'target_size_mm':1.}],{},{} )[0]['surface_mesh']
    assert not report['available'] and report['triangle_count']==0
    assert 'corner_edge_max_mm' not in report
