# Local refinement and self-balanced solids

## Local meshes

In solid `2.0`, add a list under `mesh.local_refinements`:

```json
{"name":"root-radius","selector":{"type":"interface","name":"root_blend"},"size_factor":0.4,"distance_mm":5,"sampling":50}
```

The selected full material faces use a Gmsh Distance/Threshold field. `size_factor` is positive and at most1; the target is `global_h * size_factor` at **every** level. `distance_mm` is the physical halo to return to global sizing; sampling controls the distance field discretization. Mesh reports record resolved faces and actual target sizes. Whole-face IDs retain a geometry hash; semantic interfaces need a current generator manifest. Overlapping fields take the smallest size. All existing Jacobian, volume, field coverage, equilibrium, budget, stress and two-pair convergence gates apply. This is explicit local control, not automatic adaptive error estimation. Smaller local elements do not repair a mathematically sharp stress singularity. Development dev3 allows `bodies[].local_refinements` in assembly cases, in that body's local frame. Unqualified assembly-wide selectors remain rejected.

## Self-balanced internal loads

`reference_only:true` is limited to one connected solid in a static `2.0` case. It is useful for a free C-frame with internal closing forces, tensile coupons loaded at both ends, or other self-balanced parts. It requires exactly six independent translation equations at source-bound **material points**:

```json
{"name":"reference-A","point_mm":[2,2,2],"dofs":[1,2,3],"geometry_sha256":"CURRENT_STEP_SHA256"}
```

Use another point with two DOFs and a third with one, arranged to remove all six rigid modes. Points must lie on/in the actual C3D10 body; no nearest-node snapping. The solver uses quadratic interpolation and algebraically reduces the equations so dependent DOFs are unique. Source hash, equation rank, wrench balance, displacement residual and negligible reference forces are checked. Reference forces are numerical diagnostics; they are not fixture or actuator reactions.

The resultant force **and** moment must vanish, including gravity and any fixed-load subcase. Unbalanced weight needs an actual physical support or balancing load; this mode is not inertial relief. Buckling and assembly/robot reference constraints are unsupported. Do not suppress a real external load simply to satisfy this gate.

Global displacement depends on the gauge, so `criteria.max_displacement_mm` must be null. At least one explicit `relative_length` criterion is required. It references two point or surface-average samples, derives direction from their initial separation and computes its first-order length change. Rigid translation and infinitesimal rotation cancel; a transverse relative norm does not have this property. Global displacement remains raw diagnostic data. The small-response screen removes best-fit rigid motion from all mesh nodes before measuring deformation; this is a linear screening heuristic, not nonlinear verification.

This mode does not add bolt preload, contact, joint play or pad deformation. Physical condition evidence and product acceptance remain separate.

Algorithm references: [Gmsh size fields](https://gmsh.info/doc/texinfo/gmsh.html#Specifying-mesh-element-sizes), [CalculiX linear equations](https://www.feacluster.com/CalculiX/ccx_2.18/doc/ccx/node269.html).
