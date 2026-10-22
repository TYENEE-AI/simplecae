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
    # ---- feature: base-plate (build) ----
    feature_0 = scad.make_box_rsolid(width=50.0, height=60.0, depth=8.0, bottom_face_center=(0.,0.,0.))
    print({"feature": "base-plate", "faces": len(scad.ql.faces().resolve(feature_0))})
    return (feature_0,)

@app.cell
def _(feature_0):
    # ---- feature: lower-bolt-lands (add) ----
    feature_1 = scad.union_rsolid(feature_0, scad.make_cylinder_rsolid(radius=5.0, height=2.0, bottom_face_center=(-14.,0.,-2.)), scad.make_cylinder_rsolid(radius=5.0, height=2.0, bottom_face_center=(14.,0.,-2.)))
    print({"feature": "lower-bolt-lands", "faces": len(scad.ql.faces().resolve(feature_1))})
    return (feature_1,)

@app.cell
def _(feature_1):
    # ---- feature: bolt-bores (subtract) ----
    feature_2 = scad.cut_rsolid(feature_1, scad.make_cylinder_rsolid(radius=2.75, height=12.0, bottom_face_center=(-14.,0.,-3.)), scad.make_cylinder_rsolid(radius=2.75, height=12.0, bottom_face_center=(14.,0.,-3.)))
    print({"feature": "bolt-bores", "faces": len(scad.ql.faces().resolve(feature_2))})
    return (feature_2,)

@app.cell
def _(feature_2):
    # ---- feature: datums (annotate) ----
    _part = scad.make_part_rpart(part_id="base", body=feature_2, name="base")
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="root", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="foot", placement=scad.make_placement_rplacement(origin=(0.,0.,8.))))
    base = _part
    return (base,)

if __name__ == '__main__':
    app.run()
