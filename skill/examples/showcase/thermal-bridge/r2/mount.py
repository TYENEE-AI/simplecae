# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "mount"
# revision = "r2"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    # ---- feature: cold-mount (build) ----
    feature_0 = scad.make_box_rsolid(width=8.0, height=34.0, depth=12.0, bottom_face_center=(-4.,0.,-2.))
    print({"feature": "cold-mount", "faces": len(scad.ql.faces().resolve(feature_0))})
    return (feature_0,)

@app.cell
def _(feature_0):
    # ---- feature: mount-bores (subtract) ----
    feature_1 = scad.cut_rsolid(feature_0, scad.make_cylinder_rsolid(radius=2.5, height=14.0, bottom_face_center=(-4.,-12.,-3.)), scad.make_cylinder_rsolid(radius=2.5, height=14.0, bottom_face_center=(-4.,12.,-3.)))
    print({"feature": "mount-bores", "faces": len(scad.ql.faces().resolve(feature_1))})
    return (feature_1,)

@app.cell
def _(feature_1):
    # ---- feature: datums (annotate) ----
    _part = scad.make_part_rpart(part_id="mount", body=feature_1, name="mount")
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="root", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="bridge", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="cover", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    mount = _part
    return (mount,)

if __name__ == '__main__':
    app.run()
