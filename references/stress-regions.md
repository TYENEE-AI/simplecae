# Local stress convergence

Use named regions when distinct roots, bosses, mounting transitions or different
bodies can govern a design decision. A stable assembly-wide maximum does not
establish convergence at every local feature. Declare only the relevant checks,
and keep the region definitions fixed across a mesh study and CAD comparison.

Static solid `2.0` and `assembly-1.0` cases accept:

```json
"stress_regions": [
  {"name": "mount-root", "body": "bracket",
   "min_mm": [-12, -8, 2], "max_mm": [12, 8, 8]}
]
```

Omit `body` for a single solid. Boxes use millimetres in the **analysis frame**:
the placed assembly frame for an assembly, the imported/transformed model frame
for a solid. They have positive extent in all three directions. A box with no
intersecting material elements fails explicitly; it is never silently skipped.

Each region retains all four raw integration points of every C3D10 element whose
10-node bounding box intersects the box. This conservative element selection can
include points outside the box. No averaging, percentile filter or hotspot
exclusion is applied. Peaks report element and integration-point IDs, plus the
element corner-centroid for location (not an exact Gauss-point coordinate).

The existing stress-relative tolerance and two consecutive refined comparisons
apply to both the regional von Mises peak and applicable strength utilization.
Global stress/strength checks stay active. A declared region that does not
converge withholds strength acceptance, favorable ranking and capacity prediction,
while an independently converged stiffness result remains available. Contact
preload, locked and service endpoints each receive the same regional checks.
Fixed-plus-scalable capacity predictions recheck the combined local stress field.

Inspect `assessment.stress_regions`,
`assessment.verification.stress_region_mesh_comparisons`, and the corresponding
stage assessments. Locate a persistent peak against CAD, loads, constraints and
element quality before proposing a radius or a change to the load path. A
nonconverging peak alone does not prove a mathematical singularity. Unspecified
regions are not independently verified by a global pass.
