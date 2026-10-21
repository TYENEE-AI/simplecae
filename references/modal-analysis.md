# Modal and excitation-band checks (local, unreleased)

Use `modal-solid-1.0` when a user's experience depends on a structure's natural
frequencies: a sensor bracket near a motor, a flexible mount, or a part whose
low stiffness may cause vibration. First identify the operating excitation
bands and the actual mounting, material/density and attached masses. A part
frequency without its required attached equipment is a scoped part result.
The current contract is one homogeneous isotropic STEP solid; it does not
silently attach payload masses, fuse assemblies or replace flexible mounts
with fixed supports.

The Agent chooses the relevant part and writes a case, then uses the ordinary
`analyze`, API `analyze_case`, or a `method: fem` task check. Select the result
criterion IDs in the task. Do not invent a universal "safe natural frequency".
If there is no acceptance criterion yet, `criteria: []` returns frequencies and
shapes as diagnostic information with an indeterminate use verdict.

## Contract and units

- `model`: existing single STEP, `units: mm`, explicit `expected_bbox_mm`.
- `material`: name, source/applicability `basis`, `young_mpa`,
  `density_kg_m3`, `poisson` in (-1, 0.49). Nearly incompressible, anisotropic
  and temperature-dependent materials are not qualified in this contract.
- `support_mode`: `supported` or explicitly `free_body`.
  Each support needs a name, target, basis and a whole-face plane or hash-bound
  face selector. Optional `dofs` select actual restrained translations.
  Supported models must restrain all six common rigid motions; free bodies
  have no added numerical fixtures.
- `elastic_mode_count`: 2–30. The solver also requests two guard modes and,
  for free bodies, six rigid modes. All returned modes are audited and stored.
- Three `mesh.sizes_mm`, each 0.35–0.85 times its predecessor; default
  20,000 quadratic tetrahedra per grid, explicitly adjustable through
  `mesh.max_elements` after resource planning. Keep supports geometrically unchanged.
  Optional `mesh.local_refinements` uses the existing whole-face selector,
  `size_factor`, `distance_mm` and optional `sampling` contract described in
  [local mesh refinement](local-mesh-and-reference.md). Targets scale with each
  global grid; this does not change the cap or mode/energy/convergence gates.
- `minimum_elastic_frequency`: `minimum_hz`, target and acceptance basis.
- `avoid_excitation_band`: increasing `band_hz: [low, high]`,
  explicitly justified `separation_ratio` greater than zero and at most one,
  target and basis. The exclusion band is
  `[low*(1-ratio), high*(1+ratio)]`. This is a frequency-separation screen,
  not a vibration-amplitude criterion.
- Assumptions, unassessed items, provenance and property/mounting verification
  declarations remain explicit. No static capacity extrapolation.

See `scripts/verify_modal.py` for a complete reproducible case, fixed-condition
CAD iteration and an actual Agent task. The script is a mathematical reference,
not an installation or printed-material qualification.

## Numerical evidence and boundaries

The mesh remains in mm; the CalculiX deck uses m, kg, s and Pa. Density creates
the consistent mass matrix. There are no applied service loads, prestress,
contact or fictitious damping in this normal-mode calculation.

The backend checks complete finite eigenpairs and native frequency units,
actual restrained DOFs, independent stiffness/mass matrix action, mass
normalization/orthogonality, Rayleigh quotients, total mass and higher-order
mass integration. It retains small negative eigenvalues: only six shapes
verified to span rigid motion with negligible eigenvalues can be classified
as free-body rigid modes. Negative elastic modes are not accepted.

Native ARPACK uses a shift of 1 rad²/s². The returned spectrum must extend
beyond 2 rad²/s² to establish coverage of lower nonnegative eigenvalues under
this positive-elastic single-solid contract. A wholly lower returned window
needs more modes; it cannot establish the lowest elastic mode by assertion.

Both successive mesh comparisons use every coarse integration point, evaluated
in the fine C3D10 field without nearest-node snapping. Correspondence uses
volume-weighted modal assurance; repeated/near-repeated modes are checked as
subspaces rather than arbitrary individual eigenvectors. Both frequency
differences must be at most 1%, and each matched subspace's minimum squared
overlap at least 0.95. Clusters use a 1% relative spectral gap. Rank deficiency,
unmapped points, a changed subspace dimension or missing eigenpairs prevent
acceptance.

Criteria retain the spectral range across all three meshes and a further 2%
numerical guard. This guard is not a bound on uncertain material or mounting.
A band pass requires coverage above the whole exclusion band. A mode interval
fully inside the band is a conflict. An interval touching its boundary, or
inadequate mode coverage, is indeterminate. Missing damping does not prevent a
frequency-only screen; it prevents an amplitude/noise/fatigue claim.

## Agent feedback and Viewer

A valid conflict identifies the criterion, mode frequencies and nodal antinode
coordinates. The antinode is a location cue, **not a stress/damage hotspot or a
continuous maximum**. Inspect the shape and mounting before editing:

- Shortening an unsupported span or increasing section inertia in the flexing
  direction can raise its bending frequency.
- Added mass can lower frequencies; stiffening one region can introduce another
  controlling mode. Recompute the full requested frequency range.
- Moving a mode out of a band can mean above or below it. Raising every
  frequency is not a universal optimization objective.

Preserve service frequency bands, separation requirements, density/material
and declared supports across a CAD comparison. Changed operating conditions
are a different task contract. Recheck fit, mounting access and static strength
where the change affects them. A scoped pass needs no cosmetic CAD iteration.
Invalid numerical evidence calls for analysis repair before design changes.

The Viewer stores one geometry and all elastic mode fields, allows choosing
and slowly animating a mode, and labels nodal normalization explicitly.
Animation amplitude and speed are arbitrary. Stress, displacement in mm and
strength utilization are disabled for modal fields. Different CAD revisions
do not automatically overlay their same-numbered modes: mode identities may
cross. Check results and unchanged task criteria remain comparable.

Native output is compacted losslessly. Full eigenvectors, input/deck, mesh,
checks, hashes and failed records remain; no `.eig` matrix cache is generated.
Global installation and public-release status must be established separately;
these numerical capabilities do not themselves establish release qualification.

Curved-solid verification found a shared native-deck formatting defect:
scientific-notation real tokens could exceed CalculiX's F20.0 read width and
lose an exponent digit. Modal and solid-thermal writers now preserve the
exponent within 20 characters; the shared executor rejects oversized numeric
fields before running. This neither clips small coordinates nor changes the
mesh or acceptance thresholds. Curved and repeated-mode references cover it.

## Primary references

- Author's CalculiX frequency manual (mirror):
  https://www.feacluster.com/CalculiX/ccx_2.18/doc/ccx/node276.html
- Author's frequency analysis and normalization:
  https://www.feacluster.com/CalculiX/ccx_2.18/doc/ccx/node166.html
- Native eigenvalue method and shift:
  https://github.com/Dhondtguido/CalculiX/blob/master/src/arpack.c
- Native element stiffness/mass quadrature:
  https://github.com/Dhondtguido/CalculiX/blob/master/src/e_c3d.f
- Native coordinate read width:
  https://github.com/Dhondtguido/CalculiX/blob/master/src/nodes.f

These sources inform the mathematics and native interpretation. No native
source code was copied into this skill, and no additional runtime was installed.
