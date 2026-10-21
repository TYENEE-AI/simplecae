# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "heater"
# revision = "r2"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    # ---- feature: board-heater-envelope (build) ----
    feature_0 = scad.make_box_rsolid(width=4.0, height=20.0, depth=6.0, bottom_face_center=(2.,0.,0.))
    print({"feature": "board-heater-envelope", "faces": len(scad.ql.faces().resolve(feature_0))})
    return (feature_0,)

@app.cell
def _(feature_0):
    # ---- feature: datums (annotate) ----
    _part = scad.make_part_rpart(part_id="heater", body=feature_0, name="heater")
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="root", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    heater = _part
    return (heater,)

if __name__ == '__main__':
    app.run()
