# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "first"
# revision = "r1"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    LENGTH = scad.Var(name="length", default=180.0, unit="mm")
    DEPTH = scad.Var(name="depth", default=8.0, unit="mm")
    return (LENGTH, DEPTH,)

@app.cell
def _(LENGTH, DEPTH):
    # ---- feature: link-web (build) ----
    feature_0 = scad.make_box_rsolid(width=LENGTH, height=24.0, depth=DEPTH, bottom_face_center=(LENGTH/2.,0.,0.))
    print({"feature": "link-web", "faces": len(scad.ql.faces().resolve(feature_0))})
    return (feature_0,)

@app.cell
def _(LENGTH, DEPTH, feature_0):
    # ---- feature: datums (annotate) ----
    _part = scad.make_part_rpart(part_id="first", body=feature_0, name="first")
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="root", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="tip", placement=scad.make_placement_rplacement(origin=(LENGTH,0.,0.))))
    first = _part
    return (first,)

if __name__ == '__main__':
    app.run()
