# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "base"
# revision = "r1"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    # ---- feature: base-foot (build) ----
    feature_0 = scad.make_box_rsolid(width=40.0, height=50.0, depth=8.0, bottom_face_center=(-20.,0.,-8.))
    print({"feature": "base-foot", "faces": len(scad.ql.faces().resolve(feature_0))})
    return (feature_0,)

@app.cell
def _(feature_0):
    # ---- feature: drive-envelope (add) ----
    feature_1 = scad.union_rsolid(feature_0, scad.make_box_rsolid(width=20.0, height=30.0, depth=24.0, bottom_face_center=(-10.,0.,0.)))
    print({"feature": "drive-envelope", "faces": len(scad.ql.faces().resolve(feature_1))})
    return (feature_1,)

@app.cell
def _(feature_1):
    # ---- feature: mount-bores (subtract) ----
    feature_2 = scad.cut_rsolid(feature_1, scad.make_cylinder_rsolid(radius=2.75, height=10.0, bottom_face_center=(-30.,-16.,-9.)), scad.make_cylinder_rsolid(radius=2.75, height=10.0, bottom_face_center=(-30.,16.,-9.)))
    print({"feature": "mount-bores", "faces": len(scad.ql.faces().resolve(feature_2))})
    return (feature_2,)

@app.cell
def _(feature_2):
    # ---- feature: datums (annotate) ----
    _part = scad.make_part_rpart(part_id="base", body=feature_2, name="base")
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="root", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="arm", placement=scad.make_placement_rplacement(origin=(0.,0.,12.))))
    base = _part
    return (base,)

if __name__ == '__main__':
    app.run()
