"""Native tagged fixture; validated with SimpleCADAPI 2.2.6.post2.

Run in the CAD environment with repository scripts/ on PYTHONPATH.
Regenerate saved fixtures explicitly with --fixture-dir.
"""
from pathlib import Path
import argparse
import simplecadapi as scad
from simplecae_scad import export_for_cae


@scad.part(id="simplecae.reference.link",revision="1.0.0")
def beam():
    return scad.make_box_rsolid(width=100,height=10,depth=10,bottom_face_center=(50,0,-5),
                               back_face_tag="interface.mount",front_face_tag="interface.payload")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=Path('out/cae/beam'))
    parser.add_argument('--fixture-dir',type=Path)
    args=parser.parse_args()
    export_for_cae(beam(),args.out,required={
        'interface.mount':{'face_count':1,'surface_types':['Plane']},
        'interface.payload':{'face_count':1,'surface_types':['Plane']}})
    if args.fixture_dir:
        import shutil
        for source,target in [('part.step','simplecad-beam.step'),('source.scadpkg','simplecad-beam.scadpkg'),
                              ('interface_manifold.json','simplecad-beam.interfaces.json')]:
            shutil.copyfile(args.out/source,args.fixture_dir/target)
