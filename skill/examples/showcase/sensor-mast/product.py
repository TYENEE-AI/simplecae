# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "s02_sensor_mast"
# revision = "r2-fillet"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    base = scad.use("base.py")
    mast = scad.use("mast.py")
    sensor = scad.use("sensor.py")
    return (base, mast, sensor,)

@app.cell
def _(base, mast, sensor):
    _assembly = scad.make_assembly_rassembly(assembly_id="s02_sensor_mast", name="s02_sensor_mast")
    _assembly = scad.add_component_rassembly(assembly=_assembly, item=base, component_id="base", placement=scad.identity_placement_rplacement())
    _assembly = scad.add_component_rassembly(assembly=_assembly, item=mast, component_id="mast", placement=scad.identity_placement_rplacement())
    _assembly = scad.add_component_rassembly(assembly=_assembly, item=sensor, component_id="sensor", placement=scad.identity_placement_rplacement())
    _assembly = scad.ground_component_rassembly(assembly=_assembly, component_id="base")
    _assembly = scad.add_fixed_constraint_rassembly(assembly=_assembly, constraint_id="mate-0", connector_a=scad.ConnectorRef(component_id="base", connector_id="foot"), connector_b=scad.ConnectorRef(component_id="mast", connector_id="root"))
    _assembly = scad.add_fixed_constraint_rassembly(assembly=_assembly, constraint_id="mate-1", connector_a=scad.ConnectorRef(component_id="mast", connector_id="seat"), connector_b=scad.ConnectorRef(component_id="sensor", connector_id="root"))
    assembly = scad.solve_assembly_constraints_rassembly(assembly=_assembly, strict=True)
    return (assembly,)

if __name__ == '__main__':
    app.run()
