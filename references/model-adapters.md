# General model and generator adapters

`bind-regions MODEL --rules RULES --previous OLD_MANIFEST --out NEW_MANIFEST`
adds a `.binding-report.json` with current/previous region area, area-weighted
centroid, face count and their differences. Count/plane mismatches carry
structured candidate diagnostics; no nearest-face substitution occurs. A split
face can be admitted only by the declared count range, not by silently weakening
it. A successful match still requires preview to confirm design intent.

When the CAD generator exports current named selections, use `--native-manifest`
instead of `--rules`; model hash and every region signature must match the current
export. Previous manifests provide diagnostics only, not inherited selections.

Binding also creates `.binding-preview.png`. The report states whether actual
selected surfaces were visible; a bounds-only or unavailable preview is not a
visual acceptance. Rejected v2 bindings retain a diagnostic report and, when
possible, an inventory preview without claiming an accepted selection.

For assemblies use `schema: "simplecae.interface_manifold/2"`, with required
`frame: "part_local" | "world"`, `part` (`solid_id` and/or exact `step_label`),
`regions`, and `provenance`. Provenance contains `generator`, runtime
`generator_version`, `definition_id`, `revision`, and `content_hash` (STEP SHA-256).
Each region requires a positive integer `face_count`, a `faces` list of that
length, and surface types either in `surface_types` or each face's `surface_type`.
Face signatures contain `centroid_mm`, `area_mm2` and optionally `normal_hint`.

Part-local placement is resolved in order: explicit `placement.matrix_4x4` in mm;
source-bound SimpleCAD occurrence metadata; standard STEP assembly-tree rigid
placements. The latter uses the pure Python
[STEPutils Part 21 reader](https://steputils.readthedocs.io/en/latest/p21.html),
including declared length units. Unknown or ambiguous trees require an explicit
matrix. A transform must be finite, rigid and right-handed; there is no fallback
to treating local coordinates as world coordinates. Only the selected solid is
searched. Binding requires unique centroid/area/type signatures and separation
from the second candidate. The binding report retains the transform and matching
evidence. v1 manifests remain accepted for source-bound single-solid exports,
including files created by geometric `bind-regions` rules; these bindings need no
migration. Multi-solid or part-local handoff requires a v2 native manifest from
CAD and `bind-regions --native-manifest`. v1 is rejected for multi-solid source
STEP files, even after selecting one constituent.

Solid cases use `schema_version: "2.0"`. The input file path remains relative to its case file. STEP preserves its stored units and coordinates. GLB defaults to metres and Y-up per glTF 2.0; its occurrence transform is applied and the geometry is rotated to the analysis Z-up frame. Declare `source_up_axis: "z"` only for an export intentionally authored that way. `expected_bbox_mm` checks the normalized dimensions. STL/OBJ require explicit `model.units: "mm" | "m" | "cm"`.

Use `inspect MODEL --out faces.json`, with `--units`, `--source-up-axis` and `--scene-node` when applicable. GLB files with more than one geometry occurrence require a specific `model.scene_node`; the adapter never implicitly merges an assembly. Animated rigid GLB requires explicit `model.pose: "rest"`; skinned or morphing meshes are rejected. A URDF pose is a separate robot analysis, not an inferred GLB animation frame.

The mesh path welds coincident tessellation vertices, checks finite coordinates, closedness, consistent winding, one connected shell, positive volume and triangle intersections with recorded tolerances/budget. It never fills holes, takes a convex hull or substitutes collision geometry. Gmsh reconstructs parameterized discrete surfaces and remeshes them at each requested size. Faceted input remains faceted: mesh convergence does not establish fidelity to unknown original CAD curvature. Unresolved features below intersection tolerances are disclosed.

Adjacent triangles are checked by their shared edge/vertex topology without
contracting sliver triangles. True folds, crossings and duplicates remain errors,
with coordinates, areas and aspect diagnostics. The default candidate budget grows
with triangle count; an explicitly supplied API budget remains binding. The Python
diagnostic API `check_self_intersection(mesh, algorithm="legacy")` retains the old
algorithm for regression comparison only, not as a bypass of import validation.

## Native generation interfaces

Native STEP inventory includes outward unit normals for planes and analytic
cylinder axis/radius data. Curved faces have no single constant `normal`. Select a
plane by `{type:"plane",normal:[nx,ny,nz],offset_mm:d,tol_mm:0.05}` (offset is along
the normalized normal), or select outward-facing planes by
`{type:"by_normal",dir:[nx,ny,nz],max_angle_deg:5}`. Rules also accept
`normal_within:{dir:[...],max_angle_deg:5}`, `surface_type`, `radius_mm:[min,max]`
and `area_range_mm2:[min,max]`, with the required explicit `face_count` range.
For a copied cadgen Viewer face, use [source-bound reference mapping](face-references.md).

The current generators are validated with cadgen 0.7.26 and SimpleCADAPI 2.2.6.post2. `examples/integration/cadgen_beam.py` exports STEP/GLB/STL and a thicker candidate. `simplecad_beam.py` exports persistent `interface.*` tags using [the native handoff tool](simplecad-handoff.md); `scad_partitioned_hook.py` demonstrates final tagging after fillets and a real load-patch partition. A visual material or URDF inertia does not supply constitutive or failure data.

For SimpleCADAPI, `simplecae_scad.export_for_cae` writes the v2 manifest described above, using native QL queries in the CAD environment. Set `model.interface_manifest` in the solid case and use selectors `{type: "interface", name: "mount"}` / `{type: "interface", name: "payload"}`. Edited exports require regeneration of the native selection and manifest; stale hashes or ambiguous matches are rejected. The solver never reads package BREP or executes the CAD source.

The generator scripts require their actual SDK/runtime; ordinary SimpleCAE analysis of their saved exports does not. SDKs are optional integration-test dependencies, not required solver dependencies. Source models are not executed by the analysis adapter.

## Repeated region binding across CAD revisions

`bind-regions MODEL.step --rules RULES.json --out FRESH.interfaces.json` reruns
explicit whole-face predicates on each saved single-solid export. Use stable
`model_id` and region names. Rules have `schema_version: simplecae-region-rules-1.0`,
`model_id`, and `regions`, for example:

```json
{"schema_version":"simplecae-region-rules-1.0","model_id":"instrument/coldplate",
 "regions":{"heater":{"plane":{"axis":"z","position_mm":0},"face_count":[1,1]},
            "fins":{"centroid_bounds_mm":{"z":[6.01,null]},"face_count":[29,29]}}}
```

Rules combine an optional `plane`, `surface_types` (Gmsh type names), and inclusive
`centroid_bounds_mm` with x/y/z ranges. `face_count: [min,max]` is mandatory;
choose it from the intended region, not after a mismatch merely to bypass review.
This selects complete faces by their centroids, not a trimmed spatial patch.
There is no closest-face guess or inherited face number. Missing regions,
unexpected counts, ambiguous signatures, stale hashes and rule/signature
disagreement are rejected. Each manifest retains signatures and the exact STEP
hash. Review its preview; a broad rule is a user/Agent assertion of intent, not
automatic feature recognition. Changed topology or reference frames may require
a deliberate new rule/task rather than unverified automatic correspondence.

Set `model.interface_manifest` and use `{type: interface, name: fins}` in the case.
This now also works for solid thermal boundaries/criteria/local meshes. Assembly
bodies each have their own manifest. Existing `compare` and `design-compare`
compare the stable rule definitions, namespace and assembly placement alongside
unchanged task physics/criteria. CAD shape/face numbers may change; changing a
rule under the same name does not hide a changed task. Legacy manifests without
rules remain usable for solving but their comparison identity includes the CAD
hash, so cross-CAD ranking requires an explicit rule and fresh solves. Existing
results are not retroactively promoted to this workflow.

The cadgen URDF snapshot server resolves mesh URLs beneath the URDF artifact folder. The integration fixture copies its native STL under `robots/assets/` with identical bytes, avoiding a parent-relative URL that passed URI validation but returned HTTP 404 in that viewer. SimpleCAE itself supports explicit local/package paths and records their hashes.

## Agent feedback

Each completed solid/robot run produces `signal.json` with `schema_version: "simplecae-signal-1.0"`. It separates numerical validity, feasibility under the model, physical-condition verification and coverage. It includes raw utilization/margins, located feedback and omitted items; invalid/unresolved analyses have no favorable scalar margin or feasibility value. Whole-installation rating availability is always false.

Set an explicit shared `provenance.task_id` and preserve materials, fixtures/load/pose pattern, criteria and validity thresholds between candidates. `compare result-a.json result-b.json --out comparison.json` refuses ranking when this contract differs or a candidate is unresolved. Geometry and generator revision may change; the generation engine chooses objectives and edits. A strength hotspot location is an element centroid, not an exact integration-point coordinate. Feedback suggestions are design hypotheses that require reanalysis.
