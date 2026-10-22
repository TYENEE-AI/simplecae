# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["simplecadapi==2.2.6.post2"]
# [tool.simplecadapi]
# id = "simplecae.partitioned_hook"
# revision = "1.0.0"
# ///
"""Native hook: finish features, partition the load patch, then tag interfaces."""
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad
    from simplecadapi import ql


@app.cell
def _():
    # ---- params: root blend ----
    root_fillet_r = scad.var('root_fillet_r', 3.0, unit='mm')
    return (root_fillet_r,)


@app.cell
def _():
    # ---- feature: wall (build) ----
    wall = scad.make_box_rsolid(width=8,height=20,depth=80,bottom_face_center=(4,0,0))
    return (wall,)


@app.cell
def _(wall):
    # ---- feature: arm (add) ----
    arm = scad.make_box_rsolid(width=60,height=20,depth=8,bottom_face_center=(30,0,0))
    blank = scad.union_rsolid(wall,arm)
    return (blank,)


@app.cell
def _(blank,root_fillet_r):
    # ---- feature: root-blend (modify) ----
    _root = ql.edges().where(ql.and_(ql.prop('geom.center.x','==',8),ql.prop('geom.center.z','==',8)))
    blended = scad.fillet_rsolid(solid=blank,edges=_root.exactly(1),radius=root_fillet_r) if float(root_fillet_r)>0 else blank
    return (blended,)


@app.cell
def _(blended):
    # ---- feature: payload-partition (modify) ----
    # Cut/intersect are complementary. clean=False retains the exterior seam
    # when they are reunited into ONE connected solid, without changing volume.
    _tool = scad.make_box_rsolid(width=20,height=40,depth=100,bottom_face_center=(55,0,-10))
    _front = scad.intersect_rsolid(blended,_tool)
    _back = scad.cut_rsolid(blended,_tool)
    partitioned = scad.union_rsolid(_front,_back,clean=False)
    assert abs(partitioned.get_volume()-blended.get_volume())<1e-6
    return (partitioned,)


@app.cell
def _(partitioned):
    # ---- feature: mounting-interface (annotate) ----
    _mount = ql.faces().where(ql.prop('geom.center.x','==',0))
    mounted = scad.apply_tag_rselection(scope=partitioned,targets=_mount.exactly(1),tag='interface.mount')
    return (mounted,)


@app.cell
def _(mounted):
    # ---- feature: payload-interface (annotate) ----
    _payload = ql.faces().where(ql.and_(ql.prop('geom.center.x','>',45),ql.prop('geom.center.z','==',8)))
    tagged = scad.apply_tag_rselection(scope=mounted,targets=_payload.exactly(1),tag='interface.payload')
    return (tagged,)


@app.cell
def _(tagged):
    # ---- feature: product (annotate) ----
    hook = scad.make_part_rpart(part_id=scad.notebook_id(),body=tagged,name='partitioned hook')
    return (hook,)


if __name__=='__main__':app.run()
