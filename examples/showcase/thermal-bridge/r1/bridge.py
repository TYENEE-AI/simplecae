# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "bridge"
# revision = "r1"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    THICKNESS = scad.Var(name="thickness", default=2.0, unit="mm")
    return (THICKNESS,)

@app.cell
def _(THICKNESS):
    # ---- feature: heat-path (build) ----
    feature_0 = scad.make_box_rsolid(width=40.0, height=20.0, depth=THICKNESS, bottom_face_center=(20.,0.,0.))
    print({"feature": "heat-path", "faces": len(scad.ql.faces().resolve(feature_0))})
    return (feature_0,)

@app.cell
def _(THICKNESS, feature_0):
    # ---- feature: datums (annotate) ----
    _part = scad.make_part_rpart(part_id="bridge", body=feature_0, name="bridge")
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="root", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="heater", placement=scad.make_placement_rplacement(origin=(40.,0.,0.))))
    bridge = _part
    return (bridge,)

if __name__ == '__main__':
    app.run()
