"""Real SimpleCADAPI product assembly/AP242 fixture, two placed occurrences."""
from pathlib import Path
import json
import simplecadapi as scad


@scad.part(id='simplecae.reference.half',revision='1.0.0')
def half():
    return scad.make_box_rsolid(width=50,height=10,depth=10,bottom_face_center=(25,0,-5))


if __name__=='__main__':
    part=half()
    @scad.assemble(id='simplecae.reference.two_bodies',revision='1.0.0',definitions=(part,))
    def pair():
        assembly=scad.make_assembly_rassembly('simplecae.reference.two_bodies')
        assembly=scad.add_component_rassembly(assembly,part.value,'left',scad.make_placement_rplacement((0,0,0)),name='left')
        assembly=scad.add_component_rassembly(assembly,part.value,'right',scad.make_placement_rplacement((50,0,0)),name='right')
        return assembly
    out=Path(__file__).resolve().parent
    captured=scad.capture(pair(),out/'simplecad-assembly.scadpkg')
    report=scad.exporter.export_product_package_to_step(captured.package,out/'simplecad-assembly.step')
    (out/'simplecad-assembly.export.json').write_text(json.dumps(report.to_dict(),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report.to_dict(),indent=2))
