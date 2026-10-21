# Thermal networks

This bounded network model complements the separate solid thermal FEM path.
Installed versions depend on the user's installation; check `--version` rather
than inferring global state from this document. See
[platform evidence](platform-evidence.md) for current tested scope; the
[development checklist](multiphysics-development.md) is historical context.

## Choose the model by the decision

Use a thermal network when the decision is about an explicit heat path or
region-average temperature: insulating one region from a reservoir, comparing
heat rejection paths, or estimating a calibrated lumped body's warm-up time.
Use targeted solid thermal FEM when gradients/contact hot spots determine the
decision. No automatic material values, convection coefficient or contact
resistance are inferred from CAD or product names.

For a hot object on a polymer support, ask about contact area, temperatures and
dwell/cooling history, insulating layer dimensions and properties, heat loss,
and the polymer's permissible temperature for that use. A heat-generating device
has a different design direction: adding insulation may make it hotter.
Temperature alone never establishes strength or creep life at that temperature.

## Invocation

`check CASE.json`, `analyze CASE.json --out FRESH_DIRECTORY`, the Python
`check_case`/`analyze_case` API, and `task start/run/status` accept
`schema_version: "thermal-network-1.0"`. Use `method: "calculation"` in a task,
with the existing `result_criteria`, `load_path`, `load_basis`, `support_basis`
fields describing heat transport, heat/temperature inputs and thermal boundaries.
The schema exported with `scripts/export_schemas.py` (when available) or
`simplecae.schemas.export_schemas` contains its full typed contract.

The existing bounded `design-check` process budget applies. No thermal
cache/reuse or capacity prediction is offered. Keep input sources, assumptions,
required physical checks and criteria bound to a fresh revision. Viewer lists
temperature margins and named regions; it does not fabricate a 3D stress field.

## Physical inputs

- SI conductance/heat units: W, J, K differences, seconds and meters.
  Temperatures and property-range limits are explicitly degrees Celsius.
- Nodes require unique `id`, meaningful CAD/assembly `target`, and a `basis`
  explaining the represented region and why a lumped temperature is usable.
- A transient free node additionally requires `capacity_j_k` and
  `initial_temperature_c`. Capacity may be computed as mass × specific heat;
  retain how the mass and properties were obtained in the task sources/basis.
- Optional `biot_number` supports a conservative small-gradient screen: values
  over 0.1 withhold acceptance. Absence remains an explicit evidence gap, not a
  confirmed uniform temperature. This scalar screen alone is not sufficient for
  arbitrary localized heating; document the actual spatial assumptions.
- Each link is `resistance` (K/W), `conduction` (k A/L, all SI), or `convection`
  (h A). Supply `basis` and `target` for each. Finite contact conductance can use
  an explicit resistance; it is not silently treated as perfect bonding.
- Steady mode uses `fixed_temperature_c` and `heat_w` maps. Every connected
  component needs a reservoir. An uncooled floating steady network is rejected.
- Transient mode uses a complete boundary/heat map in each constant phase,
  with `duration_s`. Values are replaced per phase, not inherited implicitly.
  Reservoir membership is fixed throughout. Insulated finite-capacity bodies
  are allowed. A prescribed reservoir cannot have ignored capacity or initial
  temperature. No heat input is accepted on a reservoir.
- `property_temperature_range_c` declares where all constant model properties
  are applicable. An excursion outside it withholds acceptance.
- Each criterion references a node and its minimum and/or maximum allowable
  temperature. Neither a softening temperature nor a melt temperature is
  automatically a permissible continuous-use limit.

Conditions are assertions: `properties_verified`, `boundaries_verified`,
`lumping_verified`. Even all true do not make a product approved. Keep actual
material, convection/contact and real temperature measurements separate.

## Numerical and decision evidence

Steady networks use a symmetric conductance solve. Transients use backward
Euler at n, 2n and 4n steps per phase (`steps_per_phase`, default 100).
Compare every node at every shared time, minima and maxima, with both successive
differences <= 0.05 °C. The complete histories, including both sides of each
reservoir temperature jump, are retained. Nodal energy residual must be <=
1e-8 W. These gates cannot be loosened in an input case.

An unresolved time study calls for more time steps, not a CAD change. A
temperature margin within the numerical guard (0.05 °C transient, 1e-9 °C
steady) remains indeterminate. Kelvin/Celsius temperature ratios are not used
as fake utilization metrics.

Results report the target region, peak temperature/time, minimum temperature,
margin, energy balance, refinement differences, assumptions and unassessed
items. A valid failure suggests tracing incoming heat versus heat rejection;
the Agent then proposes one permitted geometric change. A pass requires no
automatic redesign and does not close outstanding physical checks.

For this first network layer, changes of resistance, capacity or thermal
boundary data are different contracts and are not ranked as verified CAD-only
improvements. Fresh results can be inspected independently. Geometry-to-network
binding and solid-field iterations are pending in the thermal-FEM stage.

## References

- https://doc.comsol.com/6.3/doc/com.comsol.help.heat/heat_ug_theory.07.035.html
- https://dhondt.de/ov_calcu.htm

Implementation is original and uses the existing NumPy/SciPy dependencies.
