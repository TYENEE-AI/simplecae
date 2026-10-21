# Results and scope

The response is linear elastic. Strength uses maximum **integration-point** von Mises stress and an explicit yield safety factor, applicable to isotropic ductile yielding. Stiffness uses maximum nodal displacement magnitude anywhere in the body. It does not predict breakage, plastic redistribution or ultimate capacity.

`status`:

- `invalid`: geometry/mesh/solver/result coverage failure or equilibrium outside tolerance; do not use as physical evidence.
- `indeterminate`: nonconvergence, large-response screening or missing strength/displacement criteria; report available raw outputs with the unresolved reason, no favorable design score.
- `fail_under_stated_model`: a converged, balanced, sufficiently small linear response exceeds one of the supplied body criteria.
- `pass_under_stated_model`: those supplied criteria pass in the stated idealized body model. Physical conditions may still be unverified; read `conditions` and capacity availability separately.

`whole_installation_status` is always `not_assessed`. This version never returns whole-installation capacity.

## Conditional body limit

For a fixed support and proportional vector traction pattern, define `sigma_allow = yield_strength / yield_safety_factor`. At the reference load:

`a_strength = sigma_allow / max_von_mises`

`a_stiffness = max_displacement_allow / max_displacement`

`a_body = min(a_strength, a_stiffness)`

In current v2 cases, **only loads marked scalable increase**. Modeled gravity and `scalable:false` forces/couples stay fixed. The tool combines fixed and variable fields and searches the declared criteria; the simple ratios above apply only when there are no fixed loads. Requested elastic buckling adds its own converged screening constraint. A limit is issued only with applicable strength and displacement criteria, verified physical conditions, equilibrium, sustained mesh convergence and small-response screening at both reference and predicted load. Displacement/bbox and strain thresholds are screening heuristics, not nonlinear verification. A mass equivalent is available only for a supported pure vertical scalable pattern; an arbitrary force/couple is never converted into a hanging mass rating.

Legacy `schema_version:"1.0"` has only proportional force loading; use v2 for fixed loads, self-weight, moments and elastic buckling. Elastic eigenvalue modes are ideal bifurcation screening and do not assess nonlinear collapse, imperfections or contact changes. Actual bolts, anchors, substrate, welds, adhesives, fatigue, impact, creep and manufacturing effects require their own models or qualification. Retain the actual result's complete `not_assessed` list rather than a static version-dependent list. A body limit is never an installation or ultimate product rating.

## Support components and functional displacement

Support `dofs:[1,2,3]` means zero X/Y/Z translation; it is the default. Use a subset only when the real guide or fixture permits the other motion. For a straight X guide, `[2,3]` permits axial sliding; a separate real axial stop/nut restraint is needed to eliminate the remaining rigid mode. The solver checks the rank of all six rigid-motion modes before solving. Components are in the solid/component analysis axes, or world axes for an assembly; region selectors remain in each body's local frame. These are ideal kinematic constraints, not unilateral bearing contact or measured guide stiffness. No rotation DOFs exist on C3D10 nodes.

Maximum nodal displacement is a body metric. Its location and vector identify the direction and feature that needs investigation; it is not the whole jaw's positioning error. Guide play, bearing/mount flexibility, sensor compliance, backlash and pad compression must be included separately in a product's functional error budget. Approximate section-sizing suggestions are hypotheses and require a new solve under the same material, force and functional criteria.

## Numerical evidence

The tool checks one imported volume, supported node geometry, quadratic reference-node ordering, positive Jacobians at integration samples, CAD/mesh volume agreement (2%), DAT coverage at every node and all four C3D10 integration points, finite fields, a completed static increment, no solver error, and force/moment equilibrium. Sampled positive Jacobians and benchmark success do not establish universal meshing robustness.

The PNG stress surface is coloured by the adjacent volume element's maximum integration-point value; it is not an exact surface stress or a smoothed nodal stress. The stress peak location is reported as an element centroid, explicitly distinct from exact integration-point coordinates. Deformation scale affects the display only.

For a reentrant sharp corner, full-face fixation edge or concentrated load, peak stress can increase without converging. Investigate the actual rounding, load region and support model; preserve a real hotspot. This toolkit does not remove peaks or replace them with stress percentiles.

The benchmark checks tension `u=PL/EA`, `sigma=P/A`, cantilever `u=PL^3/(3EI)` and interior bending `sigma_xx=M z/I`, plus force/moment equilibrium, displacement convergence and doubled-load proportionality. Interior stress comparison avoids fixture and load end effects; it does **not** certify the cantilever peak as mesh independent. Benchmarks verify numerical implementation against ideal mathematical cases, not a real material, manufactured geometry or mounting system.

## Sources and implementation provenance

This toolkit is independently implemented; no SimpleCADAPI source was copied. The prior workflow inspired using explicit boundary-region identification and mesh convergence.

- [Gmsh official manual and API](https://gmsh.info/doc/texinfo/gmsh.html): STEP import, mesh, reference-node coordinates and Jacobians.
- [CalculiX official distribution](https://www.dhondt.de/) and [element/traction documentation](https://www.dhondt.de/ccx_2.21.pdf): C3D10 ordering, stresses, strains and equivalent nodal loads.
- [Windows binary source](https://github.com/calculix/CalculiX-Windows/tree/60c9a10b350ec813f4d493098f47f7a8b96cd276): version 2.23, archive hash recorded by bootstrap. CalculiX and Gmsh have their own upstream licenses; keep their license/source obligations when redistributing binaries. Local tools and Python environments are excluded from source packaging.
- [SimpleCADAPI example inspected during research](https://github.com/PhySpace/SimpleCADAPI/tree/59c6ed82a9616fb5360fc75dae1c865441863773/examples/ap242_gmsh_volume_mesh).

Contact and first-order elastic-tree modes assess explicitly requested loads and do not issue automatic capacity scaling. Applied clamping force alone is not locked bolt pretension; version1.5 provides a separately declared equivalent axial bolt with locked adjustment. Planar Coulomb contact requires explicit friction/stiffness parameters and a task motion limit. Approximate tree transfer remains separate from a coupled continuum/joint solution. See [mode-specific conditions](contact-and-transfer.md); retain their actual unassessed mechanisms.
