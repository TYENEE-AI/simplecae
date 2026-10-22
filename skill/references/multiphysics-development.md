# SimpleCAE: four ordered extensions

Historical implementation log, retained for traceability. The checkpoint and
installed-version statements below describe 2026-10-20, not the current release.
Use [platform evidence](platform-evidence.md) and the public receipt for current
verification; do not infer current global installations from this history.

Status: local dev11 development checkpoint; the installed dev10 skill remains
unchanged. This file is the implementation and verification checklist, not a
public-release qualification. The final [cross-feature audit](multiphysics-audit.md)
records capabilities, resolved issues and numerical limits.

Current checkpoint (2026-10-20):

- Thermal networks: steady/transient calculations, complete history verification,
  bounded Agent tasks and Viewer curves are implemented in the local source.
  The network-stage regression receipt is `outputs/multiphysics-dev/all-10.xml`
  (586 passing tests); `thermal-demo-03` retains the four outcome references.
- The 12 directories explicitly approved for cleanup were removed; receipt
  `outputs/multiphysics-dev/cleanup.json` records 332,400,960 bytes. Source tests,
  JUnit logs (including failed attempts) and the latest demo remain. Removed raw
  solver/test outputs are unavailable and must not be reused as live evidence.
- Solid conduction: the local `thermal-solid-1.0` CLI/API/task path now includes
  native STEP meshing, SI decks, temperature/flux completeness checks, independent
  heat-balance audits, three-mesh and three-time-grid qualification, quadratic
  interior/surface extrema, material-range checks and hash-bound compact fields.
  The Viewer shows a spatial field/peak marker and regional temperature histories.
  Standard references include asymmetric heating/reflection, internal heat peaks,
  a passing surface inside a failing whole-solid check and unresolved time steps.
  `scripts/verify_thermal_solid.py` exercises unchanged-requirement CAD iteration,
  an insufficient-property-range result and an actual Agent task with physical
  tests still pending. The limits in `references/thermal-solid.md` are explicit.
  Full regression and rendered-demo receipts are retained under the development
  output directory; this is still local source development, not a release.
- Modal: native single-solid CLI/API/task calculations, independent eigenpair
  audits, free-body diagnostics, frequency-band coverage, three-mesh shape/
  subspace matching, located feedback and normalized Viewer animation are now
  implemented locally. The final stage regression is `all-36.xml` (641 passed);
  `modal-demo-03/verification.json` passes all nine workflow checks, including
  an actual Agent call and retained physical-test pending state. The Viewer was
  exercised and screenshots retained. See `references/modal-analysis.md`.
  The global skill and release version have not been changed.
- Motion-state loads: local `motion-loads-1.0` CLI/API/Agent checks now compute
  fixed-base rigid-tree Newton–Euler loads, preserve simultaneous state wrenches,
  check explicit drive/installation limits and rating speed applicability, and
  expose a frame/unit checked load-case helper for separate stationary mounts.
  `all-41.xml` records 674 passing tests; after the final Viewer presentation
  changes, `viewer-43.xml` records 48 passing focused tests. The last comparison
  caption-only change was syntax checked and exercised in the live Viewer.
  `motion-demo-02/verification.json` passes eleven workflow checks; the Viewer
  state selector and pass/fail/insufficient cases were visually checked.
  See `references/motion-loads.md`. This is not full trajectory, moving-link
  continuum dynamics or physical drive qualification.
- Durability: local `fatigue-data-1.0` and `creep-data-1.0` calculations now
  consume source-bound signed stress, service and applicable material curves.
  The initial focused regression `durability-44.xml` passed 38 tests; the final
  full regression `all-46.xml` passes 719 tests, including 45 durability tests.
  `durability-demo-02/verification.json` passes fourteen workflow checks,
  including real Agent workers, same-duty section iteration and missing-data
  results. The live Viewer was checked for fatigue contributions, creep
  history/limits, missing-data gaps, comparison blocking and physical pending.
  `durability-stage-checkpoint.json` records the stage evidence. The subsequent
  final regression `final-48.xml` passes 720 tests with no skips, including
  invalid thermal-observation normalization and packaged-guide coverage. See
  `references/durability-data.md`; no physical life qualification or
  package/global installation update is implied.

The versioned delivery record is `validation/development-validation.json`;
compact numerical and packaged-runtime receipts reside in
`validation/multiphysics`. Local source/package checks are distinct from fresh
dependency installation, public release or physical product qualification.

The product remains an Agent engineering-check skill: understand the use,
select an appropriate model, execute a bounded calculation, locate the governing
result, propose a permitted CAD/robot change, and recheck unchanged requirements.
No product-name routing, invented physical properties, passing partial products,
or substitution of a solver success for evidence of applicability.

## 1. Heat

User decisions: insulation thickness, heat path, cooling area, permissible dwell
time. First support explicit linear thermal resistance/capacitance networks
(steady and piecewise-constant transient). Then add targeted solid conduction
FEM with prescribed temperatures, heat input and convection. No fluid solver,
automatic convection coefficient, radiation linearization, or thermal stress
claim. A network node is a declared lumped region, not a spatial hot spot.

Required tests: analytical series/parallel resistances, energy conservation,
Newton cooling, multi-node transient and changing load phases, spatial/time
refinement, manufactured 3D slab solution, asymmetric heating, missing thermal
path, inconsistent units, invalid material data, temperature-range violation,
pass/fail/insufficient evidence, source mutation and real Agent/Viewer iteration.
Unverified contact resistance, convection, material/print data and physical
temperature tests remain visible.

## 2. Modal / vibration risk

User decisions: bracket rigidity, sensor vibration risk, resonance avoidance.
Add normal modes for supported linear solids, mass/density consistency, rigid
mode and constraint diagnostics, converged eigenvalues and mode matching.
Compare explicit excitation frequency intervals with declared exclusion bands.
Modes are not response amplitudes. Do not predict vibration comfort/noise
without excitation, damping and a response model.

Required tests: analytical cantilever and axial modes; free-body rigid modes;
mass/stiffness scaling; mode crossings/repeated modes; incomplete eigenpairs;
mesh convergence; inadequate restraints; resonance conflict and absent
excitation. Verify field display, animated amplitudes explicitly arbitrary.

## 3. Motion loads

User decisions: speed/acceleration limits, payload placement, link/drive sizing.
Use explicit motion states and SI inertial data to generate reaction/load cases
for existing statics/FEM. Start with prescribed rigid-body kinematics and open
robot trees; preserve gravity, angular acceleration and centripetal terms.
An equivalent-static load check is not coupled flexible dynamics or impact.

Required tests: translating mass, rotating eccentric mass, accelerated rigid
body, two-link inverse dynamics cross-check, zero-motion static equivalence,
coordinate-frame covariance, joint reactions, missing inertia, unsupported
closed loops, multiple limiting motion states. No arbitrary universal dynamic
factor or silent sampling that misses known extrema.

## 4. Durability

User decisions: repeated-use stress and dwell-induced deformation.
Separate fatigue and creep. Require applicable material curves, stress ratio,
temperature, manufacture and units. Implement bounded S-N damage calculations
and bounded data-backed creep response; unsupported extrapolation and absent
curves produce insufficient evidence, not infinite life. Retain fatigue stress
location/history and creep load/duration/temperature applicability.

Required tests: analytical constant-amplitude damage, mixed cycle counts,
range/amplitude distinction, mean stress applicability, curve endpoints,
out-of-range requests, creep reference solutions/data interpolation, uncertain
or absent material evidence, CAD iteration versus changed service conditions.

## Cross-cutting acceptance

- Existing task/CLI/API and Viewer records must cover all four methods.
- Standard cases + failures + unfamiliar use cases; no benchmark-specific logic.
- Review numerical gates, source bindings, units, feedback and overall claims.
- Regression tests on existing mechanics and Agent task paths.
- Keep examples small, cache opt-in, and data cleanup explicit. Only after a
  feature passes, remove its own disposable bulky test directories if useful;
  retain reproducible cases/scripts, tool/version hashes, checks/thresholds,
  outcome summaries, representative fields, and failure diagnostics. Deleted
  raw evidence must be marked archived/unavailable, never silently reusable.
- Update version/docs/package only against completed qualification. No upload.

## Primary method references

- CalculiX analysis capabilities: https://dhondt.de/ov_calcu.htm
- CalculiX reference manual: https://www.dhondt.de/ccx_2.23.pdf
- Thermal networks: https://doc.comsol.com/6.3/doc/com.comsol.help.heat/heat_ug_theory.07.035.html
- Material-data evaluation: https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication960-11.pdf
- Native thermal output semantics (manual):
  https://www.dhondt.de/ccx_2.22.pdf
- Native thermal integration conventions:
  https://github.com/Dhondtguido/CalculiX/blob/master/src/e_c3d_th.f

The solid backend retains the native four-point tetrahedral integration used by
CalculiX C3D10 heat-transfer matrices alongside higher-order independent volume
integration. Its energy audit subtracts applied distributed heat and includes
transient storage before interpreting prescribed-temperature reactions; summing
native RFL alone is not a heat-balance check. Nodal temperature fields also
reconstruct the conductive matrix action, so unrelated RFL and temperature
fields cannot pass only by cancellation. Native field-output precision is
visible in the reference tests. These conventions are physics/numerics, not
product-specific routing; no CalculiX source code was copied.

These references guide implementation; no proprietary code is copied.

Durability references:
https://doc.comsol.com/6.4/doc/com.comsol.help.fatigue/fatigue_ug_sme.4.25.html
https://ansyshelp.ansys.com/public/Views/Secured/corp/v251/en/ans_mat/selectmatmodel.html
The implementation uses supplied cycle counts and constant-stress creep tables;
it does not add rainflow, general viscoplastic FEM or automatic material data.

Motion reference:
https://modernrobotics.northwestern.edu/nu-gm-book-resource/8-3-newton-euler-inverse-dynamics/
The world-frame implementation adds no dependencies and copies no external code.

## Modal-stage audit findings

- Native real-token width: curved geometry exposed exponent truncation in
  `.15g` scientific notation. The shared executor now rejects numeric tokens
  longer than 20 characters; thermal/modal writers adapt precision to preserve
  the exponent. No coordinate zeroing or geometric projection was used.
- Matrix mass checks compare assembly and volume using the same quadrature.
  The separate existing 0.5% modal mass quadrature gate also checks total
  native-vs-higher-order mass; curved elements no longer confuse an integration
  discrepancy with a failed algebraic mass identity.
- Mode correspondence maps use string keys so JSON round trips remain stable
  beyond ten modes. A regression protects source/evidence digest verification.
- Missing excitation/criteria, inadequate frequency coverage and failed
  numerical evidence have distinct next actions. Mode amplitude is arbitrary;
  neither same-numbered CAD modes nor nodal antinodes imply damage.
- Curved-cylinder thermal reference: at 1.8 mm mesh, temperature satisfies the
  original 0.0001 C reference threshold, but pointwise heat flux does not meet
  the original 0.001 W/m2 threshold (observed maximum error about 0.188 W/m2).
  That strict flux reference remains unqualified and is retained explicitly,
  separate from the passed manufactured linear-temperature gradient patch test.
  Temperature criteria never imply an independent pointwise heat-flux accuracy
  rating. No runtime thermal acceptance threshold was relaxed.

## Motion-stage audit findings

- URDF inertia tensors were previously stored without applying the inertial
  origin's rotation. That omission did not change existing gravity-only loads,
  but is consequential for angular dynamics. The reader now rotates COM tensors
  into link axes without an additional translation/parallel-axis shift; rotated
  inertias and gyroscopic moments have an analytical regression.
- Public checks require every joint's q/qd/qdd, physical inertials, explicit
  load frames and declared rating applicability. No URDF effort value, arbitrary
  acceleration multiplier, omitted Coriolis term or universal motor envelope is
  used as a substitute for those inputs.
- Returned reactions have explicit action direction, axes and reference points.
  Installation transfer converts N·m to N·mm, preserves whole simultaneous
  states, and refuses to represent moving-link inertia as a concentrated load.
- Comparison freezes inertials, topology/axes, operating states and limits.
  Joint-origin geometry can vary, but equal joint states do not establish equal
  end-effector reach. Reach/clearance and structure remain separate checks.
- A showcase copied from an existing task template retained irrelevant beam
  wording. `motion-demo-02` corrects its use scenario and checks scenario binding;
  the original `motion-demo-01` is retained as a superseded showcase, not the
  final presentation evidence. No numerical acceptance limit changed.
- Viewer load checks show state tables, not stress/deformation colors. Comparison
  text no longer claims a shared spatial color scale for motion calculations.
- An additional sandboxed HTTP test run (`viewer-42.xml`) was rejected by Windows
  socket permissions (WinError 10013). The authorized normal-process repeat
  (`viewer-43.xml`) passed; no HTTP/security behavior was disabled to pass it.
- Cleanup receipt `cleanup-motion-tests.json` removes six superseded raw test
  directories (168.69 MiB), retaining all JUnit logs/source, latest full raw
  `pytest-all-41`, latest focused raw `pytest-viewer-43`, all key showcases and
  the explicitly unqualified curved thermal-flux evidence `pytest-curved-35`.

## Durability-stage audit findings

- The first showcase (`durability-demo-01`) did not meet its original/failure
  expectations: native CAD volume integration yielded a rectangular area a
  few floating-point bits below its exact dimension-based value, pushing F/A
  beyond the supplied curve endpoint. The engine correctly withheld a verdict.
  The fresh showcase uses exact rectangular dimensions for the analytical
  F/A reference and independently checks CAD volume at relative tolerance
  1e-12. Both areas are retained in stress evidence. Runtime material-domain
  gates remain unchanged; regression explicitly rejects one-ULP exceedances.
- S-N interpolation uses amplitude, stress ratio and each service block.
  Missing blocks cannot be dropped, and unsupported locations cannot yield
  an overall pass. Creep keeps stress sign, temperature, strain definition
  and complete requested history. No material-domain extrapolation is used.
- Hashes identify sources but cannot certify declared local stress or curve
  transcription. Reports disclose this, physical verification remains false,
  and the mathematical showcase cannot qualify real-material life.
- Sandboxed full regression `all-45.xml` recorded 31 failures involving native
  DLL loading, owned-process termination and local socket permissions. The
  normal-process run `all-46.xml` passes all 719 tests with no skips; no tests
  or physical gates were disabled for that repeat.
- Cleanup receipt `cleanup-durability-tests.json` removes four superseded raw
  test directories (252.27 MiB). All JUnit logs, source, both durability
  showcases, latest full raw `pytest-all-46` and the explicitly unqualified
  curved thermal reference remain. Deleted raw directories are not live proof.
