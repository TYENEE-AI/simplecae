# /// script
# dependencies = ["simplecadapi"]
# [tool.simplecadapi]
# id = "s04_inspection_arm"
# revision = "r1"
# ///
import marimo
app = marimo.App()
with app.setup:
    import simplecadapi as scad

@app.cell
def _():
    base = scad.use("base.py")
    first = scad.use("first.py")
    second = scad.use("second.py")
    tool = scad.use("tool.py")
    return (base, first, second, tool,)

@app.cell
def _(base, first, second, tool):
    _assembly = scad.make_assembly_rassembly(assembly_id="s04_inspection_arm", name="s04_inspection_arm")
    _assembly = scad.add_component_rassembly(assembly=_assembly, item=base, component_id="base", placement=scad.identity_placement_rplacement())
    _assembly = scad.add_component_rassembly(assembly=_assembly, item=first, component_id="first", placement=scad.identity_placement_rplacement())
    _assembly = scad.add_component_rassembly(assembly=_assembly, item=second, component_id="second", placement=scad.identity_placement_rplacement())
    _assembly = scad.add_component_rassembly(assembly=_assembly, item=tool, component_id="tool", placement=scad.identity_placement_rplacement())
    _assembly = scad.ground_component_rassembly(assembly=_assembly, component_id="base")
    _assembly = scad.add_fixed_constraint_rassembly(assembly=_assembly, constraint_id="mate-0", connector_a=scad.ConnectorRef(component_id="base", connector_id="arm"), connector_b=scad.ConnectorRef(component_id="first", connector_id="root"))
    _assembly = scad.add_fixed_constraint_rassembly(assembly=_assembly, constraint_id="mate-1", connector_a=scad.ConnectorRef(component_id="first", connector_id="tip"), connector_b=scad.ConnectorRef(component_id="second", connector_id="root"))
    _assembly = scad.add_fixed_constraint_rassembly(assembly=_assembly, constraint_id="mate-2", connector_a=scad.ConnectorRef(component_id="second", connector_id="tip"), connector_b=scad.ConnectorRef(component_id="tool", connector_id="root"))
    assembly = scad.solve_assembly_constraints_rassembly(assembly=_assembly, strict=True)
    return (assembly,)

if __name__ == '__main__':
    app.run()
