import json
import pytest
from simplecae.bridge import resolve_interfaces


def test_native_interface_hash_and_unique_geometry_binding(tmp_path):
    info={'geometry_sha256':'a'*64,'faces':[{'id':8,'area_mm2':100,'centroid_mm':[0,0,0]},{'id':3,'area_mm2':100,'centroid_mm':[100,0,0]}]}
    manifest={'schema_version':'1.0','generator':'simplecadapi','model_id':'link','revision':'r1','model_sha256':'a'*64,
              'regions':{'mount':{'faces':[{'area_mm2':100,'centroid_mm':[0,0,0]}]}}}
    p=tmp_path/'interfaces.json';p.write_text(json.dumps(manifest))
    assert resolve_interfaces(p,info)['regions']['mount']==[8]
    info['geometry_sha256']='b'*64
    with pytest.raises(ValueError,match='different model hash'):resolve_interfaces(p,info)
    info['geometry_sha256']='a'*64;info['faces'].append({'id':4,'area_mm2':100,'centroid_mm':[0,0,0]})
    with pytest.raises(ValueError,match='matched 2'):resolve_interfaces(p,info)
