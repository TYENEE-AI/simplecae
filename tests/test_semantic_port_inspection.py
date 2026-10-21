from pathlib import Path
from simplecae.geometry import inspect,select_faces
from simplecae.component_transfer import add_surface_centers
import numpy as np


def test_actual_SimpleCAD_native_interfaces_are_available_to_inspection_and_transfer(tmp_path):
    root=Path(__file__).resolve().parents[1];model={'path':str(root/'examples/integration/simplecad-beam.step'),
         'interface_manifest':str(root/'examples/integration/simplecad-beam.interfaces.json')}
    info=inspect(Path(model['path']),tmp_path/'geometry.json',model)
    assert select_faces(info,{'type':'interface','name':'mount'}) and select_faces(info,{'type':'interface','name':'payload'})
    transfer={'world_from_component':np.eye(4).tolist(),'ports':[{'port':'tool','point_mm':[0,0,0],
               'force_n':[0,0,-10],'moment_n_mm_at_application':[0,1000,0]}]}
    add_surface_centers(transfer,info,{'tool':{'type':'interface','name':'payload'}})
    assert np.allclose(transfer['ports'][0]['world_surface_centroid_m'],[.1,0,0])
    assert np.allclose(transfer['ports'][0]['moment_n_mm_about_surface_centroid'],[0,0,0])
