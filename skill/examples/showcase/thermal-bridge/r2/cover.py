# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "cover"
# revision = "r2"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    # ---- feature: cover-envelope (build) ----
    feature_0 = scad.make_box_rsolid(width=46.0, height=28.0, depth=12.0, bottom_face_center=(23.,0.,0.))
    print({"feature": "cover-envelope", "faces": len(scad.ql.faces().resolve(feature_0))})
    return (feature_0,)

@app.cell
def _(feature_0):
    # ---- feature: interior-clearance (subtract) ----
    feature_1 = scad.cut_rsolid(feature_0, scad.make_box_rsolid(width=48.0, height=24.0, depth=11.0, bottom_face_center=(23.,0.,-1.)))
    print({"feature": "interior-clearance", "faces": len(scad.ql.faces().resolve(feature_1))})
    return (feature_1,)

@app.cell
def _(feature_1):
    # ---- feature: datums (annotate) ----
    _part = scad.make_part_rpart(part_id="cover", body=feature_1, name="cover")
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="root", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    cover = _part
    return (cover,)

if __name__ == '__main__':
    app.run()
