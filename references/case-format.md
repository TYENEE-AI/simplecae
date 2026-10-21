# Case contract v1.0

The toolkit always uses mm, N and MPa. STEP's stored units are converted by OpenCASCADE; verify imported dimensions rather than guessing a scale. Only one positive-volume CAD solid with no loose surfaces is accepted. It uses homogeneous isotropic linear elasticity, fixed XYZ on selected full CAD faces, and uniform **vector traction** on selected full faces. This is a prescribed total force distributed by area, not normal pressure, a point force, bearing contact or self-weight.

Generate usable inputs with `simplecae examples --out examples-new` (fresh directory). `axial.case.json`, `cantilever.case.json` and `bracket.case.json` are complete executable examples with matching STEP files. Model paths are relative to the case file, not the shell directory.

Required top-level keys: `schema_version: "1.0"`, `model`, `material`, `supports`, `loads`, `criteria`, `mesh`, `conditions`. Optional `notes`. Unknown keys, nonfinite numbers and wrong types are rejected.

| Object | Fields |
|---|---|
| model | `path` (STEP/STP); optional `expected_bbox_mm: [[xmin,ymin,zmin],[xmax,ymax,zmax]]`, compared with 0.001 mm absolute tolerance |
| material | `name`, `youngs_modulus_mpa > 0`, `-1 < poisson_ratio < 0.5`, nonempty `source`; optional positive `yield_strength_mpa`; `failure_criterion: "von_mises_yield"` when applicable, otherwise omitted/`"not_specified"` |
| supports | Nonempty list of `{name, selector}`; each selected face fixes X,Y,Z; no prescribed nonzero displacements, springs, contact or bolt connectors |
| loads | Nonempty list of `{name, selector, total_force_n: [Fx,Fy,Fz]}`; nonzero vectors; distinct load faces; loads on a fixed face rejected |
| criteria | Explicit `yield_safety_factor >= 1` and positive `max_displacement_mm` enable the two checks; missing values suppress combined capacity. Optional positive `max_small_displacement_ratio` (default 0.05), `max_strain_norm` (default 0.01) |
| mesh | `sizes_mm`: at least three positive decreasing sizes, each <= 0.8 of the previous. Optional `displacement_relative_tolerance` (0.05), `stress_relative_tolerance` (0.10), `balance_relative_tolerance` (0.0005), `max_elements` (500000) |
| conditions | All five keys below explicitly true/false. `true` must have supporting evidence; it is not a substitute for evidence |

Conditions: `material_verified`, `dimensions_verified`, `supports_represent_actual_mounting`, `load_pattern_verified`, `self_weight_negligible`. The first includes applicability of the declared yield criterion and strength at the relevant manufacturing/service state. The last acknowledges that self-weight is not included and must be negligible for the modeled purpose.

Selectors:

```json
{"type":"plane", "axis":"x", "position_mm":0, "tolerance_mm":0.0001}
```

This selects all whole planar faces in that coordinate plane. Use the face inventory and preview to verify the actual selection. For arbitrary whole faces:

```json
{"type":"face_ids", "ids":[7], "geometry_sha256":"<actual 64-character STEP hash from inspect>"}
```

The hash prevents using stale face IDs after STEP edits. Surface areas and centroids are exported in the mesh report. High-order nodal load integration preserves the total force and its first moment; equal nodal shares are incorrect for C3D10 face traction.

Choose mesh sizes from thickness, radii and stress concentrations, not just the bounding-box diagonal. Convergence requires both of the last two refinement comparisons to meet displacement and peak stress tolerances. An adequate displacement result may coexist with an unresolved peak stress. Do not relax tolerances just to obtain a passing assessment.

All output files are contained in the fresh run directory: `case.resolved.json`, `result.json`, `report.html`, and per-level `mesh.msh`, `mesh.json`, `mesh.npz`, `job.inp`, `job.dat`, `job.frd`, `job.sta`, `job.solver.log`, `fields.npz`, `results.json`. The finest level also has `fields.png` if rendering succeeds. The static fields are actual solver outputs; display deformation is amplified and labelled. Preview failure does not change numerical validity but must be disclosed.
