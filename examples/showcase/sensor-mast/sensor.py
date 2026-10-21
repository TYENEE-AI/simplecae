# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "sensor"
# revision = "r1"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    # ---- feature: sensor-envelope (build) ----
    feature_0 = scad.make_box_rsolid(width=24.0, height=24.0, depth=12.0, bottom_face_center=(0.,0.,0.))
    print({"feature": "sensor-envelope", "faces": len(scad.ql.faces().resolve(feature_0))})
    return (feature_0,)

@app.cell
def _(feature_0):
    # ---- feature: datums (annotate) ----
    _part = scad.make_part_rpart(part_id="sensor", body=feature_0, name="sensor")
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="root", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    sensor = _part
    return (sensor,)

if __name__ == '__main__':
    app.run()
