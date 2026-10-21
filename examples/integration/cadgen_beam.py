"""Real text-to-cad/cadgen export fixture; run with cadgen==0.7.21.

The thickness variant is a separate candidate under the same load contract.
"""
from cadgen import build123d as bd
from cadgen import step, glb, stl
from pathlib import Path
import shutil


@step(out="cadgen-beam.step")
@glb(out="cadgen-beam.glb")
@stl(out="cadgen-beam.stl")
def arm_link():
    return bd.Box(100,10,10,align=(bd.Align.MIN,bd.Align.CENTER,bd.Align.CENTER))


@step(out="cadgen-beam-thicker.step")
@glb(out="cadgen-beam-thicker.glb")
def thicker_link():
    return bd.Box(100,10,12,align=(bd.Align.MIN,bd.Align.CENTER,bd.Align.CENTER))


if __name__=="__main__":
    arm_link()
    thicker_link()
    # Package the native STL beneath the URDF folder for portable viewer URLs.
    project=Path(__file__).resolve().parent
    assets=project.parent/'robots'/'assets';assets.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(project/'cadgen-beam.stl',assets/'cadgen-beam.stl')
