# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "mast"
# revision = "r2-fillet"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    DEPTH = scad.Var(name="depth", default=6.0, unit="mm")
    return (DEPTH,)

@app.cell
def _(DEPTH):
    # ---- feature: foot-plate (build) ----
    feature_0 = scad.make_box_rsolid(width=40.0, height=40.0, depth=6.0, bottom_face_center=(0.,0.,0.))
    print({"feature": "foot-plate", "faces": len(scad.ql.faces().resolve(feature_0))})
    return (feature_0,)

@app.cell
def _(DEPTH, feature_0):
    # ---- feature: mast-web (add) ----
    feature_1 = scad.union_rsolid(feature_0, scad.make_box_rsolid(width=16.0, height=DEPTH, depth=100.0, bottom_face_center=(0.,0.,6.)))
    print({"feature": "mast-web", "faces": len(scad.ql.faces().resolve(feature_1))})
    return (feature_1,)

@app.cell
def _(DEPTH, feature_1):
    # ---- feature: sensor-seat (add) ----
    feature_2 = scad.union_rsolid(feature_1, scad.make_box_rsolid(width=24.0, height=24.0, depth=4.0, bottom_face_center=(0.,0.,106.)))
    print({"feature": "sensor-seat", "faces": len(scad.ql.faces().resolve(feature_2))})
    return (feature_2,)

@app.cell
def _(DEPTH, feature_2):
    # ---- feature: upper-bolt-lands (add) ----
    feature_3 = scad.union_rsolid(feature_2, scad.make_cylinder_rsolid(radius=5.0, height=2.0, bottom_face_center=(-14.,0.,6.)), scad.make_cylinder_rsolid(radius=5.0, height=2.0, bottom_face_center=(14.,0.,6.)))
    print({"feature": "upper-bolt-lands", "faces": len(scad.ql.faces().resolve(feature_3))})
    return (feature_3,)

@app.cell
def _(DEPTH, feature_3):
    # ---- feature: bolt-bores (subtract) ----
    feature_4 = scad.cut_rsolid(feature_3, scad.make_cylinder_rsolid(radius=2.75, height=10.0, bottom_face_center=(-14.,0.,-1.)), scad.make_cylinder_rsolid(radius=2.75, height=10.0, bottom_face_center=(14.,0.,-1.)))
    print({"feature": "bolt-bores", "faces": len(scad.ql.faces().resolve(feature_4))})
    return (feature_4,)

@app.cell
def _():
    # ---- params: root transition ----
    ROOT_RADIUS = scad.Var(name="root_radius", default=0.8, unit="mm")
    return (ROOT_RADIUS,)

@app.cell
def _(ROOT_RADIUS, feature_4):
    # ---- feature: root-transition (modify) ----
    _root_edges = scad.ql.edges().where(scad.ql.and_(
        scad.ql.prop("geom.type", "==", "LINE"),
        scad.ql.prop("geom.center.z", ">=", 5.99999),
        scad.ql.prop("geom.center.z", "<=", 6.00001),
        scad.ql.prop("geom.center.x", ">=", -8.001),
        scad.ql.prop("geom.center.x", "<=", 8.001),
        scad.ql.prop("geom.center.y", ">=", -3.001),
        scad.ql.prop("geom.center.y", "<=", 3.001),
    )).exactly(4)
    for _edge in _root_edges.resolve(feature_4):
        _center = _edge.get_center()
        print({"root_edge_length_mm": _edge.get_length(), "center_mm": [_center.x, _center.y, _center.z]})
    root_transition = scad.fillet_rsolid(solid=feature_4, edges=_root_edges, radius=ROOT_RADIUS)
    return (root_transition,)

@app.cell
def _(DEPTH, root_transition):
    # ---- feature: datums (annotate) ----
    _part = scad.make_part_rpart(part_id="mast", body=root_transition, name="mast")
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="root", placement=scad.make_placement_rplacement(origin=(0.,0.,0.))))
    _part = scad.add_connector_rpart(part=_part, connector=scad.make_placement_connector_rconnector(connector_id="seat", placement=scad.make_placement_rplacement(origin=(0.,0.,110.))))
    mast = _part
    return (mast,)

if __name__ == '__main__':
    app.run()
