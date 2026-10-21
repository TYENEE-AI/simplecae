import json,numpy as np
import pytest
from simplecae.interface_check import cylinder_axis,load_interface_case
from simplecae.case import sha256,write_json
from simplecae.robot import transform


class AnalyticCylinder:
    def __init__(self,rotation=None):self.model=self;self.r=np.eye(3) if rotation is None else rotation
    def getType(self,dim,face):return 'Cylinder'
    def getParametrizationBounds(self,dim,face):return [0,0],[2*np.pi,20]
    def getDerivative(self,dim,face,uv):
        return np.array([[*(self.r@[-3*np.sin(u),3*np.cos(u),0]),*(self.r@[0,0,1])] for u,v in np.asarray(uv).reshape(-1,2)]).ravel()
    def getValue(self,dim,face,uv):return np.array([self.r@[10+3*np.cos(u),7+3*np.sin(u),v] for u,v in np.asarray(uv).reshape(-1,2)]).ravel()


def test_cylinder_axis_extraction_is_not_a_surface_centroid_guess():
    r=transform([0,0,0],[.2,-.4,.6])[:3,:3];a=cylinder_axis(AnalyticCylinder(r),5)
    assert np.allclose(a['direction'],r@[0,0,1])
    assert np.linalg.norm(np.cross(np.array(a['point_mm'])-r@[10,7,0],a['direction']))<1e-9
    assert a['radius_mm']==pytest.approx(3)


def test_arbitrary_face_does_not_receive_an_invented_hole_axis():
    g=AnalyticCylinder();g.getType=lambda *_:'Plane'
    with pytest.raises(ValueError,match='not an analytic cylinder'):cylinder_axis(g,1)


def input_case(tmp_path):
    model=tmp_path/'model.step';model.write_text('read-only path validation fixture')
    doc=tmp_path/'reference.txt';doc.write_text('explicit interface reference')
    c={'schema_version':'simplecae-interface-1.0','model':{'path':'model.step'},
       'provenance':{'classification':'catalog_cad','part_number':'declared SKU','source_url':'https://example.test/catalog',
                     'reference_document':{'path':'reference.txt','sha256':sha256(doc)},'reference_pages':[1]},
       'checks':[{'name':'width','type':'extent','axis':'y','expected_mm':9,'tolerance_mm':.02}]}
    p=tmp_path/'case.json';write_json(p,c);return p,c,model,doc


def test_reference_document_is_bound_and_native_STEP_never_rescaled(tmp_path):
    p,c,_,doc=input_case(tmp_path);assert load_interface_case(p)['provenance']['classification']=='catalog_cad'
    doc.write_text('changed reference')
    with pytest.raises(ValueError,match='missing or changed'):load_interface_case(p)
    c['provenance']['reference_document']['sha256']=sha256(doc);c['model']['units']='m';write_json(p,c)
    with pytest.raises(ValueError,match='do not rescale'):load_interface_case(p)


def test_no_name_based_supplier_upgrade_and_unit_axis_required(tmp_path):
    p,c,_,_=input_case(tmp_path);c['provenance']['classification']='genuine_by_filename';write_json(p,c)
    with pytest.raises(ValueError):load_interface_case(p)
    c['provenance']['classification']='catalog_cad'
    c['checks']=[{'name':'hole','type':'cylinder_axis','selector':{'type':'plane','axis':'z','position_mm':0},'expected_axis':[0,0,2],
                  'expected_point_mm':[0,0,0],'axis_distance_tolerance_mm':.01,'angle_tolerance_deg':.1}]
    write_json(p,c)
    with pytest.raises(ValueError,match='unit length'):load_interface_case(p)
