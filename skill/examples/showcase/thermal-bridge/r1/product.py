# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "s03_heat_bridge"
# revision = "r1"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    mount = scad.use("mount.py")
    bridge = scad.use("bridge.py")
    heater = scad.use("heater.py")
    cover = scad.use("cover.py")
    return (mount, bridge, heater, cover,)

@app.cell
def _(mount, bridge, heater, cover):
    _assembly = scad.make_assembly_rassembly(assembly_id="s03_heat_bridge", name="s03_heat_bridge")
    _assembly = scad.add_component_rassembly(assembly=_assembly, item=mount, component_id="mount", placement=scad.identity_placement_rplacement())
    _assembly = scad.add_component_rassembly(assembly=_assembly, item=bridge, component_id="bridge", placement=scad.identity_placement_rplacement())
    _assembly = scad.add_component_rassembly(assembly=_assembly, item=heater, component_id="heater", placement=scad.identity_placement_rplacement())
    _assembly = scad.add_component_rassembly(assembly=_assembly, item=cover, component_id="cover", placement=scad.identity_placement_rplacement())
    _assembly = scad.ground_component_rassembly(assembly=_assembly, component_id="mount")
    _assembly = scad.add_fixed_constraint_rassembly(assembly=_assembly, constraint_id="mate-0", connector_a=scad.ConnectorRef(component_id="mount", connector_id="bridge"), connector_b=scad.ConnectorRef(component_id="bridge", connector_id="root"))
    _assembly = scad.add_fixed_constraint_rassembly(assembly=_assembly, constraint_id="mate-1", connector_a=scad.ConnectorRef(component_id="bridge", connector_id="heater"), connector_b=scad.ConnectorRef(component_id="heater", connector_id="root"))
    _assembly = scad.add_fixed_constraint_rassembly(assembly=_assembly, constraint_id="mate-2", connector_a=scad.ConnectorRef(component_id="mount", connector_id="cover"), connector_b=scad.ConnectorRef(component_id="cover", connector_id="root"))
    assembly = scad.solve_assembly_constraints_rassembly(assembly=_assembly, strict=True)
    return (assembly,)

if __name__ == '__main__':
    app.run()
