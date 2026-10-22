from pathlib import Path
import math
import numpy as np
import pytest
from simplecae.case import selector
from simplecae.geometry import session,inventory,select_faces
from simplecae.region_rules import select_region


def test_tilted_65_degree_plate_outward_normals_and_oriented_plane(tmp_path):
    step=tmp_path/'tilted.step'
    angle=math.radians(65)
    with session() as g:
        solid=g.model.occ.addBox(0,-30,0,100,60,4)
        g.model.occ.rotate([(3,solid)],0,0,0,0,1,0,angle)
        g.model.occ.synchronize();g.write(str(step))
        info=inventory(g,step)
        center=np.array(info['center_of_mass_mm'])
        for face in info['faces']:
            assert np.dot(np.array(face['centroid_mm'])-center,face['normal'])>0
        direction=[math.sin(angle),0,math.cos(angle)]
        spec={'type':'by_normal','dir':direction,'max_angle_deg':1}
        selector(spec);ids=select_faces(info,spec)
        assert len(ids)==1
        plane={'type':'plane','normal':direction,'offset_mm':4,'tol_mm':.001}
        selector(plane);assert select_faces(info,plane)==ids
        assert select_region(info,{'normal_within':{'dir':direction,'max_angle_deg':1},
            'surface_type':'plane','area_range_mm2':[5999,6001],'face_count':[1,1]})==ids
        assert select_faces(info,{'type':'by_normal','dir':[-v for v in direction],'max_angle_deg':1})!=ids


def test_default_cylinder_geometry_selects_radius_not_all_cylinders(tmp_path):
    step=tmp_path/'bored.step'
    with session() as g:
        block=g.model.occ.addBox(0,0,0,30,20,10)
        holes=[(3,g.model.occ.addCylinder(x,10,-1,0,0,12,r)) for x,r in [(8,2),(22,3)]]
        g.model.occ.cut([(3,block)],holes);g.model.occ.synchronize();g.write(str(step))
        info=inventory(g,step)
        ids=select_region(info,{'surface_type':'Cylinder','radius_mm':[1.99,2.01],'face_count':[1,1]})
        face=next(f for f in info['faces'] if f['id'] in ids)
        assert face['normal'] is None
        assert abs(face['analytic_cylinder']['direction'][2])==pytest.approx(1)


@pytest.mark.parametrize('spec',[
    {'type':'by_normal','dir':[0,0,0],'max_angle_deg':3},
    {'type':'by_normal','dir':[0,0,1],'max_angle_deg':181},
    {'type':'plane','normal':[0,0,1],'offset_mm':0,'axis':'z'},
    {'type':'plane','normal':[0,0,0],'offset_mm':0},
])
def test_invalid_oriented_selectors_are_rejected(spec):
    with pytest.raises(ValueError):selector(spec)
