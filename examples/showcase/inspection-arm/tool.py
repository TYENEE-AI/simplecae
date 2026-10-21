# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "tool"
# revision = "r1"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    # ---- feature: tool-plate (build) ----
    feature_0 = scad.make_box_rsolid(width=8.0, height=40.0, depth=24.0, bottom_face_center=(4.,0.,0.))
    print({"feature": "tool-plate", "faces": len(scad.ql.faces().resolve(feature_0))})
    return (feature_0,)

@app.cell
def _(feature_0):
    # ---- feature: tool-bores (subtract) ----
    feature_1 = scad.cut_rsolid(feature_0, scad.make_cylinder_rsolid(radius=2.25, height=26.0, bottom_face_center=(4.,-13.,-1.)), scad.make_cylinder_rsolid(radius=2.25, height=26.0, bottom_face_center=(4.,13.,-1.)))
    print({"feature": "tool-bores", "faces": len(scad.ql.faces().resolve(feature_1))})
    return (feature_1,)

@app.cell
def _(feature_1):
    # ---- feature: datums (annotate) ----
    _part = scad.make_part_rpart(part_id="tool", body=feature_1, name="tool")
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="root", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    tool = _part
    return (tool,)

if __name__ == '__main__':
    app.run()
