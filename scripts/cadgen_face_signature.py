"""Run ONLY in cadgen's environment: canonical Viewer ref to native signatures."""
import argparse
import hashlib
import json
from pathlib import Path
from importlib.metadata import version


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model',type=Path)
    parser.add_argument('reference')
    parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    digest=hashlib.sha256(args.model.read_bytes()).hexdigest()
    if digest!=args.expected_sha256:raise ValueError('STEP changed since the selected Viewer reference; reopen and reselect')
    from cadgen import read_scene,build123d as bd
    scene=read_scene(args.model)
    selections=scene.resolve(args.reference)
    if len(selections)!=1 or selections[0].kind!='face':raise ValueError('Select exactly one canonical Viewer face reference')
    selection=selections[0]
    face=selection.shape()
    occurrence=scene.resolve(selection.occurrence_ref)[0]
    solid=occurrence.shape()
    if len(solid.solids())!=1:raise ValueError('Viewer occurrence must identify exactly one solid')
    solid=solid.solids()[0]
    mapping={'PLANE':'Plane','CYLINDER':'Cylinder','CONE':'Cone','SPHERE':'Sphere','TORUS':'Torus',
             'BSPLINE':'BSpline surface','BEZIER':'Bezier surface','REVOLUTION':'Surface of Revolution','EXTRUSION':'Surface of Extrusion'}
    kind=face.geom_type.name
    if kind not in mapping:raise ValueError(f'No verified CAD surface type mapping for {kind}; inspect native geometry')
    signature={'centroid_mm':list(face.center(bd.CenterOf.MASS)),'area_mm2':face.area,'surface_type':mapping[kind]}
    box=solid.bounding_box()
    body={'centroid_mm':list(solid.center(bd.CenterOf.MASS)),'volume_mm3':solid.volume,'bbox_mm':list(box.min)+list(box.max)}
    if hashlib.sha256(args.model.read_bytes()).hexdigest()!=digest:raise ValueError('STEP changed during native reference extraction')
    report={'schema':'simplecae.cadgen-face/1','generator':'cadgen','generator_version':version('cadgen'),
            'geometry_sha256':digest,'reference':args.reference,'canonical_reference':selection.ref,
            'occurrence':selection.occurrence_ref,'frame':'world','body':body,'face':signature,
            'meaning':'Native canonical face resolution and signatures; no Gmsh ordering assumption.'}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2,allow_nan=False)


if __name__=='__main__':main()
