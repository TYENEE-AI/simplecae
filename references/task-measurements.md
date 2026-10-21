# Functional displacement measurements

Use named measurements when the task depends on a contact location, alignment or
relative separation. Global maximum displacement remains in the result and in
the small-response/field-quality screening. These measurements do not infer
omitted joint, sensor, guide, pad, adhesive or mounting compliance.

## Solid and assembly cases

`probes` is optional in `2.0` and `assembly-1.0` cases:

```json
"probes": [
  {"name":"grasp", "type":"point", "point_mm":[36.5,2,57.5],
   "direction":[1,0,0], "max_displacement_mm":0.10},
  {"name":"interface", "type":"surface_average",
   "selector":{"type":"plane","axis":"x","position_mm":-1.5}},
  {"name":"gap_change", "type":"relative", "from_probe":"interface",
   "to_probe":"grasp", "direction":[1,0,0], "max_displacement_mm":0.06}
]
```

The values above illustrate the syntax, not a universal allowable gap. Use the
task's actual tolerance. In an assembly, each point/surface probe requires a
`body`. Point coordinates and selectors then refer to that body's input CAD
coordinates; displacement vectors and `direction` use assembly world axes.
For a single solid they use the analysis mm coordinates.

A point uses the actual C3D10 quadratic isoparametric geometry and displacement
field. A point in a hole, inside an omitted pad, or outside the selected material
is rejected before the static solver. It is not snapped to the nearest node.

A `surface_average` integrates displacement over the selected **whole material
faces** with quadratic surface shape functions. Its area centroid can lie in a
hole; the readout is an average over material, not displacement at that centroid.
Partial face patches still require upstream CAD partitioning. This is useful for
bolted/annular interfaces where a geometric center is not a material point.

`relative` subtracts the from-measurement's displacement vector from the
to-measurement's. With `direction`, the absolute projection is the criterion and
the signed projection is also retained. Without it, the vector norm is used.
Directions must be explicit unit vectors. Probes without a limit are descriptive.

Each required measurement and its contributing relative-measurement dependencies
need two consecutive converged refinements. `convergence_required: true` also
requests convergence for a descriptive measurement. Near-zero values use a
recorded absolute tolerance (default `1e-9 mm`); `absolute_convergence_tolerance_mm`
can declare a task-appropriate numerical tolerance. Vector changes are checked
when no projection was requested, so a changing direction cannot fake convergence.

If functional criteria alone are intended, `criteria.max_displacement_mm` may be
null and at least one probe must have an explicit limit. Global displacement,
stress, equilibrium and small-response checks remain. Fixed-load-plus-payload
limits evaluate the actual probe's affine displacement, not its reciprocal
reference margin, and check limiting-response convergence too.

## Robot cases

Robot measurements require explicit component FEM for all contributing links:

```json
"probes": [
  {"name":"fixed", "type":"surface_average", "link":"fixed_finger",
   "component_selector":{"type":"plane","axis":"x","position_mm":-1.5}},
  {"name":"moving", "type":"point", "link":"moving_finger",
   "point_m":[0.0365,0.002,0.0575]},
  {"name":"metal_gap", "type":"relative", "from_probe":"fixed",
   "to_probe":"moving", "direction":[1,0,0], "max_displacement_mm":0.06}
]
```

Robot point coordinates are **m in the named link frame**. A robot
`component_selector` is explicitly **mm in that component's CAD frame**, and
uses the same face/interface selector contract as its component case. Robot
directions and reported vectors use world axes; readouts and limits use mm.
`link_from_component` is applied before sampling, then displacement vectors are
rotated to world axes. A rigid URDF link alone provides no elastic readout.

Relative robot measurements combine the refined component fields, check the
combined measurement's convergence and include applicable limits in the pose
verdict and conditional payload limit. This describes modeled metal-interface
deformation at the frozen pose. Calling it an assembled gripper gap or accuracy
requires the missing compliance models or actual measurements.

## Criterion confidence

`assessment.criterion_assessments` and the design signal retain criterion-specific
pass/fail/unresolved states. A converged stiffness failure stays visible when
stress is unresolved. Overall invalid/indeterminate computation still receives
no favorable comparison margin or capacity. Failed component diagnostics reach
the robot's public `error` field rather than disappearing in a child directory.

By default, even if additional links have separate FEM, their deflection is not automatically carried into a measured finger through the URDF chain. Robot probes combine only the explicitly measured link fields at their independently fixed upstream interfaces. A full opening-error claim needs a coupled structural/connection model or physical measurements, not merely adding rear-mount FEM coverage.

For explicit first-order parent-section translation and rotation transfer, use the optional [elastic tree mode](contact-and-transfer.md). It checks complete declared FEM/rigid paths, planar section fits, warping, rotations and convergence. It remains distinct from coupled continuum/joint elasticity and withholds automatic chain capacity.
