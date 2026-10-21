# Check the actual purchased geometry against its intended interface

A filename or catalog label is not enough to establish the correct part geometry. `interface-check` compares a native STEP solid with explicit source-bound reference values. It reports differences without scaling or replacing the source CAD.

```powershell
python scripts/simplecae_cli.py inspect rail.step --analytic-axes --out rail-faces.json
python scripts/simplecae_cli.py check interface.json --kind interface
python scripts/simplecae_cli.py interface-check interface.json --out outputs/interface-001
```

Declare `provenance.classification` as `manufacturer_cad`, `catalog_cad`, `interface_envelope` or `user_design`, plus part number, source URL, reference document path/SHA256 and reference page numbers. These are source declarations, not automatic supplier-authenticity verification. The file-bound reference prevents silently carrying reference values to a changed document; manually verify the quoted table/drawing before creating the checks.

```json
{
  "schema_version":"simplecae-interface-1.0",
  "model":{"path":"mgn9_rail.step"},
  "provenance":{
    "classification":"catalog_cad","part_number":"declared MGN9 rail",
    "source_url":"https://example.test/actual-part-page",
    "reference_document":{"path":"manufacturer.pdf","sha256":"<actual64hex>"},
    "reference_pages":[91]
  },
  "checks":[
    {"name":"width","type":"extent","axis":"y","expected_mm":9,"tolerance_mm":0.02},
    {"name":"height","type":"extent","axis":"z","expected_mm":6.5,"tolerance_mm":0.02}
  ]
}
```

The example tolerances are explicit comparison tolerances, not automatically extracted manufacturing tolerances. Imported STEP carries its own native unit declaration and is measured in millimetres; `model.units` may be omitted or annotated `mm`. Mesh-like rescaling of STEP is rejected.

Optional `frame: {"xyz_mm":[...],"rpy_rad":[...]}` is the **model-to-check** rigid transform. Rotation follows RzRyRx, then translation. It transforms actual geometry in memory using analytic-preserving rotations/translations; it never edits the source, estimates an alignment or swaps axes to make a match. Compare extents only in the appropriate declared frame. Extents alone do not identify holes or prove mating fit.

A `cylinder_axis` check selects actual faces with the same full-face selectors as CAE, including source-hash-bound face IDs. Provide a unit `expected_axis`, an `expected_point_mm` on the infinite reference axis, `axis_distance_tolerance_mm`, `angle_tolerance_deg`, and optionally both `expected_radius_mm` and `radius_tolerance_mm`. Parallel-axis comparison ignores the sign of the axis; circle fit locates the axis from actual analytic parameters rather than a surface centroid. Noncylindrical, ambiguous or triangulated surfaces do not receive guessed axes. Inspect a selected solid (`--solid-id`) first for a multi-solid STEP.

Result states are `matches_declared_reference`, `mismatch` and `invalid`; they are separate from structural pass/fail. The report lists actual dimensions, signed differences, axis distances, angular differences and radii. Matching means only the requested checks match those references. No purchasing authenticity, tolerancing stack, collision/fit, bearing stiffness, material strength or product rating is established.

The real DG250 example rejected the catalog rail's12.6×4.05 mm cross-section against the preserved manufacturer WR9/HR6.5 mm table. Its separate interface envelope remains classified `interface_envelope`. Positive hole-axis/radius checks, explicit rotated frames, wrong hole position and wrong radius were verified on that actual STEP, while a plane was rejected as an axis source. Original files remained unchanged.

Python integrations use `load_interface_case`, `measure_interface` and optional `geometry.inspect(...,analytic_axes=True)`. The `interface` schema is exported with the other canonical public contracts.
