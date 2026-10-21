# dev11 multiphysics audit

Follow-up: the [bounded thermal-flux study](thermal-flux-study.md) adds three
analytic geometries/boundary cases and one refined follow-up, preserves strict
failed targets, and repairs machine-readable flux scope, lower-bound feedback
and prescribed-boundary conflicts. Final source regression now passes 728 tests;
the 720-test and staged-package evidence below describes the earlier checkpoint.
This follow-up changes local source only; that earlier ZIP and global install
have not been replaced.

This is a local development checkpoint, not a public-release, physical-material
or product qualification. The installed global skill is not updated by this
work. The user-facing workflow remains: understand use, select a bounded check,
retain located evidence, propose a permitted revision and recheck unchanged
requirements.

## Requirement-to-evidence review

| Requirement | Implementation and reviewed evidence | Boundary |
|---|---|---|
| Thermal networks and solid steady/transient conduction | `thermal_network.py`, `thermal_solid.py`, `thermal_solid_solver.py`; analytical resistance/Newton cooling, complete phase histories, slab/internal heating/convection, asymmetric reflection, independent energy, three mesh/time levels and located extrema tests | No CFD, guessed convection, thermal-contact or thermal-stress claim |
| Modal/vibration screening | `modal.py`, `modal_solver.py`; cantilever/axial references, free-body six modes, mass/stiffness scaling, eigenpair audits, crossing/repeated-subspace matching and frequency-band coverage | Arbitrary mode amplitude; no damped response, noise or comfort prediction |
| Motion-state loads | `motion.py`, `motion_solver.py`; analytic translating/eccentric/gyroscopic/Coriolis and two-link checks, branched-tree power balance, static equivalence, frame covariance and mount transfer | Listed states only; no flexible dynamics, impacts, closed-loop robot or full trajectory envelope |
| Data-backed fatigue and creep | `durability.py`; amplitude/ratio/Miner references, curve endpoints, missing blocks, single/multiple locations, time/stress interpolation, source mutation and unchanged-duty comparison | Signed uniaxial elastic stress; supplied counted cycles; constant-stress/temperature creep; no invented curves or extrapolation |
| Agent selection and completion records | `use-driven-checks.md`, `use_plan.py`, `task.py`, existing CLI/API; native worker tests for pass/fail/insufficient outcomes and physical pending | Agent authors the engineering interpretation; no product-name classifier |
| Actionable feedback | Located temperature/criterion/mode/state/material-point observations and explicit reanalysis triggers | A numerical failure asks for analysis repair; only established physical/model failures justify a CAD hypothesis |
| Iteration integrity | Frozen service, criteria and applicability contracts; source guards, evidence hashes, recomputation and invalid-evidence tests | Different materials, loads, duty or missing evidence cannot be ranked as a geometry improvement |
| Viewer and storage | Live views of thermal histories/fields, modal animation, motion tables and durability histories; actual stage and revision records | Local display does not grant product acceptance; compressed evidence is retained losslessly |
| Regression and packaging | Final source regression: 720 tests passed, no skips; 9 focused audit tests passed. Entry-point guide delivery is now tested | Source package qualification and extracted runtime receipts are separate from a new-environment bootstrap or public release |

Tests are independent analytical/contract checks where applicable, not merely
assertions that a solver returned success. Generated references exercise real
STEP/URDF files, comparisons and Agent workers. They demonstrate software/model
behavior; none is a physical test of a manufactured product. Generality also
has frame, branched-tree, asymmetric-field, mode-crossing, renamed location and
multiple-service coverage, rather than relying only on one showcase geometry.

## Findings resolved

1. **Invalid thermal feedback retained a favorable category.** The top-level
   comparison gate already rejected changed evidence, but nested located
   observations/metrics could still say pass. They now consistently become
   indeterminate; raw values remain diagnostic. The native field-mutation and
   summary-mutation regression verifies this without modifying saved results.
2. **A routed guide was missing from the package.** The development checklist
   moved from the excluded research folder to references. A test follows every
   local link in SKILL/README and checks membership in the delivered source set.
3. **Mechanical wording obscured method selection.** The use guide now maps
   observed heat, vibration, motion and durability concerns to supported methods,
   missing inputs and permissible edits. Thermal boundaries and modal excitation
   are distinguished from mechanical forces. CLI task help covers all supported
   calculations.
4. **Benchmark arithmetic exceeded material-data endpoints.** The rectangular
   durability reference uses exact dimensions for analytical F/A, independently
   checked against CAD volume. Both are retained. The generic engine still
   rejects even one-ULP curve-domain exceedances; the initial unresolved attempt
   remains available in the development workspace.
5. **URDF inertia orientation and native numeric-token width.** Earlier stage
   fixes rotate COM inertia into link axes and preserve native numeric exponents.
   Analytical rotated-inertia and curved-geometry regressions protect them.

No product names or showcase result values route production calculations. No
stress/temperature/mesh/contact/refinement limit was relaxed. No extra library,
material database or external service was introduced.

## Unqualified numerical reference retained

The naturally insulated curved-cylinder mesh at 1.8 mm satisfies the original
0.0001 C temperature reference but not the original 0.001 W/m² pointwise flux
reference: maximum flux error is about 0.188 W/m² against 3200 W/m².
This remains a failed accuracy target, not a qualified result.

An independent sparse assembly on the same mesh reproduced about 0.1877 W/m²
flux error with native four-point quadrature; higher-order quadrature gave
about 0.1910 W/m². Thus simply increasing integration order does not repair
this case. The diagnostic does not replace the native result or prove a unique
root cause. A separate prescribed-linear-temperature gradient patch passes;
it is explicitly a different boundary problem.

The solid thermal API assesses temperature criteria and keeps flux as field
evidence; it does not offer an arbitrary pointwise flux-accuracy qualification.
This numerical limit is relevant when selecting the method. A user requiring
that strict local-flux accuracy needs additional geometry/mesh study. It must
not inherit a favorable conclusion from a temperature pass.

## Reproduction and evidence

Run `pytest` for the source regression and the existing
`verify_thermal_network.py`, `verify_thermal_solid.py`, `verify_modal.py`,
`verify_motion.py`, `verify_durability.py` scripts into fresh output directories.
Each script retains cases, outcomes, comparisons and Agent/Viewer evidence.
The compact `validation/multiphysics` receipts record this checkpoint.
`validation/development-validation.json` binds the delivered sources; the
packager rejects stale source/version records. Raw native demonstration files
remain local or are regenerated, not embedded as large caches in the archive.

The four methods are intentionally separate bounded checks. No automatic
multiphysics coupling, raw-history rainflow, full creep FEM or product lifetime
prediction has been claimed or smuggled into this iteration.
