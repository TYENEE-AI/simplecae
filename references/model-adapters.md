# General model and generator adapters

Solid cases use `schema_version: "2.0"`. The input file path remains relative to its case file. STEP preserves its stored units and coordinates. GLB defaults to metres and Y-up per glTF 2.0; its occurrence transform is applied and the geometry is rotated to the analysis Z-up frame. Declare `source_up_axis: "z"` only for an export intentionally authored that way. `expected_bbox_mm` checks the normalized dimensions. STL/OBJ require explicit `model.units: "mm" | "m" | "cm"`.

Use `inspect MODEL --out faces.json`, with `--units`, `--source-up-axis` and `--scene-node` when applicable. GLB files with more than one geometry occurrence require a specific `model.scene_node`; the adapter never implicitly merges an assembly. Animated rigid GLB requires explicit `model.pose: "rest"`; skinned or morphing meshes are rejected. A URDF pose is a separate robot analysis, not an inferred GLB animation frame.

The mesh path welds coincident tessellation vertices, checks finite coordinates, closedness, consistent winding, one connected shell, positive volume and triangle intersections with recorded tolerances/budget. It never fills holes, takes a convex hull or substitutes collision geometry. Gmsh reconstructs parameterized discrete surfaces and remeshes them at each requested size. Faceted input remains faceted: mesh convergence does not establish fidelity to unknown original CAD curvature. Unresolved features below intersection tolerances are disclosed.

## Native generation interfaces

`examples/integration/cadgen_beam.py` is a real `cadgen==0.7.21` decorated build123d model that exports STEP/GLB/STL and a thicker candidate. `simplecad_beam.py` is a real `simplecadapi==2.2.1` tagged `@part`, captures `.scadpkg`, exports AP242 STEP and writes an interface manifest from native QL tag selections. Their source and exported files are retained for reproducible interoperability checks. A visual material or URDF inertia does not supply constitutive or failure data.

For SimpleCADAPI, a generator-side manifest carries `schema_version: "1.0"`, `generator`, `model_id`, `revision`, the exact `model_sha256` and named `regions`. Each region contains native selector provenance and whole-face signatures `{centroid_mm, area_mm2}`. Set `model.interface_manifest` in the solid case and use selectors `{type: "interface", name: "mount"}` / `{type: "interface", name: "payload"}`. Each signature must uniquely match one imported whole face. Edited exports require regeneration of the native selection and manifest; stale hashes or ambiguous matches are rejected. This avoids inheriting unstable Gmsh face numbers across designs.

The generator scripts require their actual SDK/runtime; ordinary SimpleCAE analysis of their saved exports does not. SDKs are optional integration-test dependencies, not required solver dependencies. Source models are not executed by the analysis adapter.

The cadgen URDF snapshot server resolves mesh URLs beneath the URDF artifact folder. The integration fixture copies its native STL under `robots/assets/` with identical bytes, avoiding a parent-relative URL that passed URI validation but returned HTTP 404 in that viewer. SimpleCAE itself supports explicit local/package paths and records their hashes.

## Agent feedback

Each completed solid/robot run produces `signal.json` with `schema_version: "simplecae-signal-1.0"`. It separates numerical validity, feasibility under the model, physical-condition verification and coverage. It includes raw utilization/margins, located feedback and omitted items; invalid/unresolved analyses have no favorable scalar margin or feasibility value. Whole-installation rating availability is always false.

Set an explicit shared `provenance.task_id` and preserve materials, fixtures/load/pose pattern, criteria and validity thresholds between candidates. `compare result-a.json result-b.json --out comparison.json` refuses ranking when this contract differs or a candidate is unresolved. Geometry and generator revision may change; the generation engine chooses objectives and edits. A strength hotspot location is an element centroid, not an exact integration-point coordinate. Feedback suggestions are design hypotheses that require reanalysis.
