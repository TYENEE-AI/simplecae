# Targeted solid heat-transfer checks

This uses the existing Gmsh/CalculiX environment and task/Viewer commands,
without a separate desktop application. Check `--version` for the invoked
installation and [platform evidence](platform-evidence.md) for tested scope.

## Choose the question first

Use a [thermal network](thermal-network.md) when a few justified heat paths and
lumped temperatures answer the design question. Use solid FEM when temperature
variation inside/on a body can change the design decision: a local hot spot,
conducting section, heat-input region or cooling area. Do not mesh every object
in an assembly by default.

The Agent supplies the selected STEP body, real dimensions, material data and
its temperature range, explicit heat boundaries, temperature criterion and
unverified items. Appearance does not establish conductivity, specific heat,
convection coefficient or a safe touch temperature.

For a first reproducible run:

```powershell
.\.venv\Scripts\python.exe scripts/verify_thermal_solid.py --out outputs/my-thermal-demo
.\.venv\Scripts\python.exe scripts/simplecae_cli.py view --session outputs/my-thermal-demo/viewer --serve --port 8811
```

Use a fresh output directory. The script creates small analytical cases and an
actual CAD iteration with fixed requirements, plus a real Agent task. The
reference's material is mathematical data, not a qualified printable material.
Its case files are templates for an Agent to edit using the actual engineering
facts; their numerical values must not become defaults for unrelated products.

For a specific case, the usual `analyze`, `design-check`, `task start`,
`task run` and Python `analyze_case` entry points work. A usage-plan check uses
`method: "fem"` and explicit `result_criteria` matching the case criterion IDs.
Physical tests remain separate required checks. Prefer bounded `task run` /
`design-check` for Agent execution. Automatic capacity/lifetime extrapolation
and cache/reuse are unavailable for thermal cases.

## Supported model and units

`thermal-solid-1.0` supports one native STEP solid and one constant, homogeneous,
isotropic material. Model dimensions, selectors and mesh sizes are **mm**.
Thermal inputs are SI: W/(m K), kg/m³, J/(kg K), W, W/m², W/m³, seconds and °C.
The generated solver deck converts geometry to metres; it does not mix mm with
SI thermal coefficients. `expected_bbox_mm` is required to catch import scale
errors. Elastic properties and mechanical restraints are not required.

Each full CAD face may have one explicit boundary:

- `temperature`: prescribed `temperature_c`.
- `heat_power`: uniformly distributed `total_heat_w`, independent of patch area.
- `heat_flux`: prescribed `flux_w_m2`. Positive means inward heat.
- `convection`: declared `coefficient_w_m2k` and `ambient_temperature_c`.

Face selectors use a plane or current geometry-hashed face IDs. Shared edges of
different fixed temperatures are rejected. A flux/convection patch may share an
edge with a fixed-temperature face; distributed input at those nodes is retained
when calculating reactions. Unselected faces are insulated. The Agent must
justify that insulation assumption; it is not automatically true in practice.
Optional `volumetric_heat_w_m3` applies uniformly through the solid.

Steady analysis needs a temperature reference or convection heat path.
Transient analysis additionally needs density, specific heat, uniform initial
temperature, duration and `time_steps`. Constant boundaries apply for the whole
duration; initial temperature must match any fixed-temperature boundary.
Abrupt Dirichlet temperature jumps, arbitrary initial fields, multiple loading
phases, radiation, fluid flow, multi-body thermal contact and temperature-
dependent/anisotropic material models are not yet qualified by this backend.
Use an applicable separate model rather than silently replacing those effects.

## What acceptance means

Three successively refined meshes are mandatory (`mesh.sizes_mm`; successive
ratios 0.35–0.85). Transient checks use the finest time step on all three meshes,
plus two coarser time grids on the finest mesh. Both successive changes must
pass: 0.05 °C for each region's full-history minimum/maximum under spatial
refinement, and 0.05 °C for every common nodal/time sample under time refinement.
Spatial qualification applies to the requested temperature extrema, not a claim
of pointwise convergence everywhere or a converged heat-flux singularity.

Quadratic extrema search includes vertices, edges, faces and element interiors,
so an interior peak is not replaced by a favorable nodal maximum. Criteria use
the worst value across all retained refinements/times, with a 0.10001 °C numerical
guard. A margin inside the guard is indeterminate. All temperatures must stay
within the declared property range. Unsupported data or unqualified numerics
cannot return a favorable comparison signal.

The audit independently reconstructs conductive nodal terms and consistent
storage, subtracts applied distributed heat, and checks free-node and total
energy residuals. Native `RFL` alone is not reservoir heat loss. Native output
roundoff uses a fixed `1e-7 W + 1e-5 × exchange-scale W` residual tolerance,
recorded with the raw residuals; users cannot loosen it. Higher-order volume
integration also checks the native thermal quadrature, with a fixed 0.001
relative difference gate. Fixed-temperature outputs are checked separately.
The exchange scale includes the absolute supported nodal reactions. Equal
heating and cooling reservoirs do not become zero heat exchange merely because
their signed resultant cancels.
For fixed-step transient analysis, the energy audit uses the requested time grid
after checking every native timestamp against it; rounded DAT timestamps remain
recorded separately. Excessively small steps can still amplify rounded nodal
temperature noise enough to fail the unchanged energy gate. That attempt stays
indeterminate. A different step count is acceptable only if it independently
passes both successive full-field time-refinement checks and every other gate.

Case, STEP, mesh, fields, decks and result summaries are hash-bound. Compact
storage compresses redundant native text losslessly while retaining every
requested field history, mesh refinement, failed attempt and numerical check.
Explicit element/field budgets stop oversized jobs rather than silently dropping
times, regions or meshes. The existing bounded worker handles timeouts.

## Feedback and iteration

Outputs distinguish:

- **Model pass**: all declared temperature criteria and qualification gates pass.
- **Model failure**: a qualified temperature criterion fails, with region,
  coordinates, element, mesh and (for transient cases) peak time.
- **Insufficient/invalid evidence**: repair boundary data, property applicability,
  field completeness, mesh/time resolution or the analysis itself before ranking.

The feedback should explain the user's consequence and one permitted CAD
hypothesis: increasing heat rejection, changing conducting area/path length or
reducing incoming heat. Insulating a self-heating region can worsen temperature.
Maintain heat power, ambient/reservoir conditions, duration and acceptance limits.
The comparison contract freezes those conditions. Changed total power under
prescribed flux or volume heating is recorded as changed task conditions.
Geometry-hashed face selections can require new evidence/contract binding after
CAD changes; do not pretend renamed surfaces prove the same physical boundary.

The Viewer shows the finest-mesh field at its hottest recorded instant,
quadratic surface-peak mapping, the solid peak marker (possibly internal), and
the complete regional min/max histories. The overall criterion can be governed
by another refinement; its mesh and coordinates remain in the result. Steady
solver step time is not elapsed time and is labelled **稳态**. Temperature views
disable structural field/deformation controls. Same-contract CAD revisions share
a temperature scale; changed conditions and insufficient evidence block ranking.

A temperature pass does **not** establish hot strength, deformation, creep,
touch safety, friction, thermal-interface quality, durability or product approval.
Keep the corresponding usage checks and physical tests pending.

Pointwise heat-flux accuracy is not an acceptance claim of this temperature
screen. The retained curved-cylinder reference meets its 0.0001 C temperature
threshold but misses its original 0.001 W/m² pointwise flux threshold (about
0.188 W/m² maximum error on a 3200 W/m² reference field). That reference remains
unqualified for the stated flux accuracy; no limit was relaxed. Do not use the
temperature verdict as proof of a local flux specification.

The machine-readable signal and design feedback identify the acceptance
quantity as `requested_temperature_extrema` and always set
`coverage.pointwise_heat_flux_qualified: false`. Do not complete a user's local
heat-flux requirement using a temperature criterion, even when its numerical
value looks reassuring. Record that requirement separately as unresolved.
Unsupported flux criteria are rejected by the case schema, not silently ignored.

For temperature failures, read each hypothesis's criterion ID, violated `min`
or `max` bound and location. A cold region needs a heat-loss/delivery diagnosis;
blindly adding cooling can worsen it. Simultaneous upper/lower violations retain
both locations. `governing_*` identifies the controlling temperature bound,
while `peak_*` still describes the hottest point for compatibility. The Viewer
card shows the controlling bound; its field view shows the finest-mesh hottest
instant, which need not be the controlling time/mesh. Hypotheses require a
permitted CAD change and reanalysis; a flux pattern alone proves no improvement.
If a prescribed temperature inside the checked region already violates its
limit (including shared edges), feedback reports a `requirement_conflict`.
The model remains failed, but `cad_iteration_blocked` stops a futile CAD loop.
Review the actual boundary and intended region with the user before changing
the task; do not silently remove the region or alter its temperature limit.

The bounded [mesh/geometry study](thermal-flux-study.md) retains all original
precision targets, coarse-mesh rejections and measured error trends. Its results
are not a universal flux-error bound. Rerun it with
`python scripts/verify_thermal_flux.py --out FRESH_DIRECTORY`.
