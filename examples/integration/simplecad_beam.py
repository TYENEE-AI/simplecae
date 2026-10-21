"""Real native tagged part/package/AP242 fixture; SimpleCADAPI==2.2.1."""
from pathlib import Path
import json
import hashlib
import simplecadapi as scad


@scad.part(id="simplecae.reference.link",revision="1.0.0")
def beam():
    return scad.make_box_rsolid(width=100,height=10,depth=10,bottom_face_center=(50,0,-5),
                               back_face_tag="cae.mount",front_face_tag="cae.payload")


if __name__=="__main__":
    out=Path(__file__).resolve().parent
    result=beam()
    captured=scad.capture(result,out/"simplecad-beam.scadpkg")
    report=scad.exporter.export_product_package_to_step(captured.package,out/"simplecad-beam.step")
    regions={}
    for role,tag in [('mount','cae.mount'),('payload','cae.payload')]:
        query=scad.ql.faces().where(scad.ql.tag(tag))
        faces=query.resolve(result.value.body)
        assert len(faces)==1,(role,len(faces))
        f=faces[0]; center=f.get_center()
        assert abs(float(center.x)-(0 if role=='mount' else 100))<1e-6,(role,center)
        regions[role]={'native_selector':query.to_dict(),'faces':[{'centroid_mm':[float(center.x),float(center.y),float(center.z)],'area_mm2':float(f.get_area())}]}
    manifest={'schema_version':'1.0','generator':'simplecadapi','generator_version':'2.2.1',
              'model_id':result.value.part_id,'revision':'1.0.0','parameters':{'length_mm':100,'width_mm':10,'height_mm':10},
              'model_path':'simplecad-beam.step','model_sha256':hashlib.sha256((out/'simplecad-beam.step').read_bytes()).hexdigest(),
              'package_path':'simplecad-beam.scadpkg','package_sha256':hashlib.sha256(captured.package_bytes).hexdigest(),
              'regions':regions,'export_report':report.to_dict()}
    (out/'simplecad-beam.interfaces.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'step':str(out/'simplecad-beam.step'),'regions':regions},indent=2))
