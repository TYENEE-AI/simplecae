"""Runnable final-face partition recipe; validated with cadgen 0.7.26."""
from cadgen import build123d as bd, step


@step(out='cadgen-partitioned-plate.step')
def partitioned_plate():
    plate = bd.Box(60,20,8,align=(bd.Align.MIN,bd.Align.CENTER,bd.Align.MIN))
    # Apply any bores/fillets before this final partition.
    with bd.SkipClean():
        front,back = plate.split(bd.Plane.YZ.offset(45),keep=bd.Keep.BOTH)
        result = front.fuse(back)
    assert len(result.solids())==1 and abs(result.volume-plate.volume)<1e-6
    tops=[f for f in result.faces() if f.geom_type==bd.GeomType.PLANE and abs(f.center().Z-8)<1e-6]
    assert len(tops)==2
    assert len([f for f in tops if f.center().X>45])==1
    return result


if __name__=='__main__':partitioned_plate()
