# Robot format handoff

Robot statics reads URDF in SI units. A visual mesh does not establish link strength. `effort` is an actuator bound, never joint stiffness; an unverified holding model still needs `review_joint_compliance`.

## MJCF from SimpleCADAPI

For a flat native assembly of leaf parts with fixed/revolute/prismatic tree constraints, export from the evaluated notebook in its own CAD environment:

```text
<SCAD_PY> -m simplecae_scad arm.py --robot-materials densities.json --out out/cae/robot-native
<SIMPLECAE_PY> scripts/simplecae_cli.py import-mjcf out/cae/robot-native/robot.xml --reference out/cae/robot-native/handoff.json --out out/cae/robot-urdf
```

`densities.json` maps every component ID to an explicit `density_kg_m3` and `source`. A homogeneous density assumption must be labeled; CAD material names or an exporter's fallback density are not physical evidence. The helper uses exact native BREP volume/COM/inertia in the CAD environment, keeps the source package, and exports a source-bound MJCF reference. No OCP crosses into CAE.

Native live placements and connectors are authoritative. In testing SimpleCADAPI 2.2.6.post2, the package MJCF path emitted incorrect serialized connector distances. The helper preserves that raw export in `upstream/`, uses its mesh/group inventory, and regenerates delivered body/joint/geom frames and inertials from the live CAD objects. This is not a guessed numeric rescaling. Display-only sites are omitted and declared. The subsequent converter independently checks every moving joint against the native reference within 0.1 mm / 0.5 degrees. A stale hash or frame mismatch blocks handoff.

The evaluated CAD pose becomes `q=0`; limits are expressed relative to that pose. The tree must follow connector_a (parent) to connector_b (child). Closed loops, coupled mechanisms, nested occurrences and reversed constraint direction require an explicit supported CAD tree; they are refused instead of silently removed.

For other MJCF sources, `import-mjcf` accepts local `pos/quat` body frames, one hinge/slide per body, explicit inertials and file mesh geoms. It preserves off-origin joints, rotated inertias and mesh scale. Missing inertials require `--inertials records.json`: map body names to `mass_kg`, `com_m`, `inertia_kg_m2` (3×3, COM tensor in body axes) and `source`. Defaults, free/ball joints, actuators, springs, tendons and equality constraints are not discarded; unsupported models are refused. See [MuJoCo's XML reference](https://mujoco.readthedocs.io/en/stable/XMLreference.html) for source semantics. Conversion alone is not a dynamics simulation or CAD consistency qualification.

## URDF with 3MF visuals

Keep the original URDF and its explicit visual scale. For every link selected for FEM, regenerate a native STEP named exactly `<link_name>.step` in one directory:

```text
<SIMPLECAE_PY> scripts/simplecae_cli.py robot-link-models arm.urdf --step-dir STEP --link first --link second --out out/cae/robot-links
```

The report maps names to inspected, hashed STEP models and retains visual mesh scale/origin. It does not multiply STEP dimensions by `0.001`: STEP already declares its units and the FEM importer normalizes to mm. Association is not a frame/mesh qualification. Use each model in a component case, choose actual support/load ports, declare `link_from_component`, and run robot component FEM; the existing density/mass/COM consistency gates remain mandatory. Missing, duplicate or multi-solid link files need explicit selection; do not infer a link from an assembly's visual name.

Direct `.3mf` FEM input currently returns a STEP regeneration recipe. In the original cadgen Python model add `@step(out="STEP/model.step")` (`from cadgen import step`), then run `<CADGEN_PY> model.py` and inspect saved STEP dimensions. Both mm and inch 3MF files take this explicit route; no unsupported unit conversion is silently attempted.

MJCF file meshes are copied into the fresh output folder with relative URDF paths and output hashes. OBJ display meshes are converted to binary STL with unchanged coordinates and explicit scale, so the CAD Viewer can load them on Windows as well. This does not create FEM geometry. Unknown elements/attributes, duplicate inertials and missing or reversed bounded ranges are refused. Source gravity is recorded in `handoff.json`; choose it explicitly in the analysis case because URDF has no gravity field. Geom contact flags and visual materials are not a contact-dynamics handoff.

For a component port that truly transmits a bilateral joint couple, supply
`port_load_policies: {"port-name": {"allow_opposite_traction": true, "reference": "physical justification"}}`
in that robot component. Optional `distribution: "bearing_only"` instead requires a feasible one-sided contact resultant. A policy must name an existing port and is frozen in the comparison contract. No policy is inferred merely because a joint exists; actual joint/bolt capacity still needs evidence.
