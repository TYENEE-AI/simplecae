# Native errors and curved-element quality

Generation, conversion to quadratic elements and HighOrder optimization retain native messages in each level's `mesh-native.log`. The wrapper temporarily uses Gmsh `General.AbortOnError=1` to abort a reported meshing operation, then restores the caller's policy. **Every logged Error becomes a Python exception and invalidates the analysis.** It does not allow a failed optimization to proceed. This handles reported native errors, not every possible process crash or loader failure. An abrupt process exit still requires retaining and reconciling its interrupted run.

After optimization, `high_order_quality` in `mesh.json` records Gmsh adaptive `minDetJac` and signed inverse condition numbers (`minSICN`). Nonfinite, incomplete or nonpositive values reject the mesh. Existing sampled Jacobian, volume, field coverage, equilibrium and convergence gates remain in force. Per-element values are stored in `mesh.npz`, aligned with `element_ids`; `peak_mesh_quality` and `strength_peak.mesh_quality` bind the actual peak element to those values. Older retained meshes without these arrays remain readable and return no added quality evidence.

The count of SICN below 0.1 is an investigation aid, not a newly calibrated acceptance threshold. Even acceptable shape cannot establish stress convergence or physical fixture validity. Compare successive whole-model peaks without cropping fixture, load or fillet regions. Refine the actual curved regions proportionally with every global mesh level; if the physical geometry changes, regenerate its native interfaces and repeat verification. If the fixture changes, give it a separate physical task contract and describe its actual meaning; a positional pin preset is not unilateral pin contact.

When high-order optimization fails, `mesh-diagnostic.json` retains rejected
element IDs, raw nonpositive quality values, their corner centroids and adjacent
CAD face IDs/types, bound to the geometry hash. Adjacency locates the problem;
it does not prove a CAD defect. If diagnostic extraction itself fails, the
original optimizer error still rejects the analysis. Use the located face IDs
for existing `local_refinements` (per body for assemblies) and keep refinement
factors fixed across the global mesh sequence. This can resolve a small hole
without paying for a fine mesh throughout a large flat base. Native quality,
full peak stress, convergence and resource limits are unchanged; there is no
automatic repair loop. The modal input now accepts the same source-bound
whole-face refinement fields without increasing its element cap.

If uncropped peaks continue rising at the end of an ideal fixed surface after their element shape improves, investigate the fixed/free transition and the omitted connection. This pattern is consistent with a constraint singularity, not proof of it. Check actual selected nodes and reaction paths, and retain every completed and failed attempt. Adding fillets or thickness cannot in itself regularize the termination of a prescribed displacement. A softer mounting model requires explained stiffness/contact data and a distinct task contract; do not invent it to obtain a pass. Leave strength indeterminate when the original peak convergence gate is unresolved. See [the primary discussion of constraint singularities](https://www.comsol.com/blogs/singularities-in-finite-element-models-dealing-with-red-spots).

Regression evidence for the PETG hook repair is under `outputs/hook-mesh-audit-20261015/`: the complete 391-test run passed, as did the real standard solver suite. The added failure-path test injects an Error through the real Gmsh logger and verifies an invalid terminal Viewer record with no solver invocation; it is a synthetic software regression, not a real nonlinear or geometry benchmark. These checks do not qualify printed PETG, screw/wall mounting, long-term creep or arbitrary curved CAD.

Primary API reference: [Gmsh manual](https://gmsh.info/doc/texinfo/gmsh.html), `General.AbortOnError` and `gmsh/model/mesh/getElementQualities`.
