# Contained planar CAD contact

Use for an explicit flat smaller bearing patch against a larger native CAD face, including holes or curved planar boundaries. Typical roles include washers, feet and fixture pads. All bodies and contact pairs still have to be declared.

Add `"footprint": "slave_within_master"` to an existing `frictionless_contact` or `frictional_contact` connection. The slave must be wholly contained in the master after rigid placement and the declared normal gap projection. Both must be native STEP faces with a valid isolated BREP; arbitrary partial overlap and mesh-only geometric containment are rejected. Default `matching` and the bonded/linear-interface segmented integrator retain their existing complete matching-footprint and straight-edge restrictions.

The toolkit recovers selected source faces by their area and centroid, uses exact OpenCASCADE trimmed-face difference to detect uncovered regions (including internal holes), and preserves conics with native rigid transforms. This proof is separate from actual FE projection. Every slave boundary node and positive isoparametric surface quadrature point must project onto the quadratic master mesh within the declared position tolerance. No node is moved and no uncovered point is skipped. Failure requires correcting placement, refining the master or upstream partitioning of a genuine physical port. CAD coverage tolerances are numerical geometry checks, never stress allowables.

Choose the actual bearing footprint upstream. A nominal washer's complete underside is not necessarily supported by material around a rounded clearance hole; a topology-only imprint may identify the planar land without removing the washer's unsupported inner region. Keep source/analysis-geometry binding and prove unchanged volume/centroid after imprinting. Initial nonpenetration, normals, full load stages, contact output coverage, all stage hotspots and small sliding gates remain required. Adjacent nonplanar contact, large sliding, contact-edge singularities and interference cannot be resolved by this mode. Coverage is for the declared initial small-response contact region, not a search for new contact partners.

Equivalent axial bolts accept planar curved boundaries. Their distributed weights integrate the actual P2 face, then preserve unit resultant and the CAD area-centroid using a conservative correction. The correction is reported per port; it is not a relaxed coaxiality check. The bolt still has axial stiffness only. No thread, transverse shank bearing, screw-head tilt contact, anchor slip/pullout or torque-to-preload inference is added. If transverse clearance or a missing contact mode becomes relevant, withhold the corresponding product/installation claim.

Assembly bodies may specify `local_refinements` with the same fields as a solid's `mesh.local_refinements`. Selectors are body-local and source-bound; target size equals that body's mesh size times its refinement factor. Global `mesh.local_refinements` is still rejected for assemblies because it does not identify a body. Combined element budgets and three-mesh convergence gates are unchanged.

The requested local size is a background-field target, not a guarantee of attained face edge lengths. In particular, a thin distance halo and sampled surface-distance field can give a coarser face than a uniform mesh with the same nominal target. `local_refinements[].surface_mesh` records the actual selected face's triangle count and corner-edge minimum/mean/maximum, separately from the target. Compare these measurements before claiming equal contact resolution; adjust the declared sampling, halo or target as appropriate and still verify every hotspot on three meshes. Generalized axial ports can create dense coupling when overrefined, but coarsening a remote port must not silently coarsen the bearing patch or bypass its stress/convergence checks.

Run the native analytic reference:

```powershell
python scripts/simplecae_cli.py validate --suite planar-footprints --out NEW_DIRECTORY
```

It checks a curved annular axial joint on nonmatching quadratic grids against an independently calculated two-spring preload/locked/service solution. The transverse guide belongs to that mathematical test fixture and must not be copied into a physical assembly unless it exists. Software guards additionally test a smaller pad inside a larger face, a hidden unsupported hole, misplacement and curved interpolation. Numerical reference success does not calibrate PETG, friction, residual preload, wall or anchor properties.

For an omitted straight shaft, `simplecae.clearance.radial_clearance(coords, displacements, triangles, axis_start_mm, axis_end_mm, shaft_radius_mm)` provides a separate conservative screen. Complete quadratic boundary triangles are bounded by their Bezier control hulls; checking mesh nodes alone can miss an intervening surface intrusion. A positive lower bound means clearance under the supplied axis assumption, a negative sampled value proves interference at that sample, and an inconclusive hull returns `unresolved`. The caller must bind the actual source faces/field and assess all relevant solved stages. It does not automatically promote a result, solve bearing contact, or account for shaft bending or unmeasured tolerances.

Execution defaults to automatic thread selection from an applicable measured
profile, otherwise serial. Select a compatible solver with `--ccx PATH`; this
does not install or automatically replace a solver. Follow
[execution resources](execution-resources.md) for complete-field calibration,
CPU affinity, explicit thread counts and recorded selection reasons. All
convergence thresholds remain unchanged. Contact history reuse remains disabled.

Native DAT output has finite printed precision. Bolt kinematic checks propagate the rounding interval of the actual scientific-notation tokens in addition to the original equation tolerance; genuine equation violations still fail. Both the raw residual and the output precision bound are reported. This is not a physical displacement allowance.

If a later contact/stage guard rejects a run after complete service field coverage has been verified, the workflow may preserve `diagnostic_levels` separately from accepted `levels`. The Viewer labels these fields as unaccepted diagnostics, retains raw peaks, and keeps the invalid verdict and ranking prohibition. A timeout or missing output cannot become a complete diagnostic field. Neither a completed solver run nor a small displayed displacement establishes an accepted model or product rating.
