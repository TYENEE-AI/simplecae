import numpy as np
import pytest
from simplecae.clearance import radial_clearance

def face():
    p=np.array([[3.,0,0],[3.,.2,0],[3.,0,1],[3.,.1,0],[3.,.1,.5],[3.,0,.5]])
    return {i+1:v for i,v in enumerate(p)},[list(range(1,7))]

def test_full_surface_bound_is_invariant_to_rigid_frame():
    coords,tri=face();zero={n:np.zeros(3) for n in coords}
    r=radial_clearance(coords,zero,tri,[0,0,0],[0,0,2],2.5)
    assert r['status']=='clear_under_stated_axis' and r['minimum_clearance_lower_bound_mm']==pytest.approx(.5)
    rotation=np.array([[0,0,1],[1,0,0],[0,1,0]]);shift=np.array([7.,-3,11])
    moved={n:rotation@p+shift for n,p in coords.items()}
    r=radial_clearance(moved,zero,tri,shift,rotation@np.array([0,0,2])+shift,2.5)
    assert r['minimum_clearance_lower_bound_mm']==pytest.approx(.5)

def test_mid_edge_motion_and_conservative_uncertainty_cannot_be_dropped():
    coords,tri=face();zero={n:np.zeros(3) for n in coords}
    coords[4][0]=2.4
    r=radial_clearance(coords,zero,tri,[0,0,0],[0,0,2],2.5)
    assert r['status']=='interference_at_sample'
    coords[4][0]=2.7
    r=radial_clearance(coords,zero,tri,[0,0,0],[0,0,2],2.5)
    assert r['status']=='unresolved' and r['minimum_sampled_clearance_mm']>0

def test_missing_fields_and_invalid_axes_fail_closed():
    coords,tri=face()
    with pytest.raises(KeyError):radial_clearance(coords,{},tri,[0,0,0],[0,0,2],2.5)
    with pytest.raises(ValueError):radial_clearance(coords,{},tri,[0,0,0],[0,0,0],2.5)
