# Bounded thermal-flux sensitivity review (dev11 follow-up)

This is a local software/numerical review, not a release, material validation or
general local-flux accuracy certificate. No solver, mesh, energy, temperature or
comparison gate was relaxed. The original curved-reference receipt remains
unchanged in `validation/multiphysics/unqualified-curved-flux.json`.

## Cases and measured errors

All cases use native C3D10, k=2 W/(m K), exact STEP geometry and natural
insulation on unspecified faces. All integration points are retained. Errors
below are the maximum absolute vector-component error against an independent
analytic solution, matching the original benchmark metric. Vector norms,
volume-weighted RMS, worst point/element and every mesh remain in the receipts.

| Geometry / condition | Mesh sizes (mm) | Maximum flux errors (W/m²) |
|---|---|---|
| 20×10×10 mm slab, both ends 20 °C, internal heating 1 MW/m³ | 5 / 3.5 / 2.5 | 0.0004969 / 0.0004982 / 0.0005000 |
| Radius 5 mm, length 50 mm cylinder along z, ends 20/100 °C | 3 / 2.4 / 1.8 | 0.670 / 0.354 / 0.188 |
| Radius 8 mm, length 20 mm cylinder along x, 20 °C sink and 0.25 W input | 4 / 3 / 2.25 | 3.778 / 2.921 / 2.143 |
| Same fixed-power cylinder, one further refinement study | 3 / 2.25 / 1.6875 | 2.921 / 2.143 / 1.666 |

The cylinder maxima and volume-weighted RMS both decrease at each refinement.
The slab error plateaus near 0.0005 W/m²; do not claim monotonic convergence
from those tiny changes. Flux normalization uses analytic characteristic
scales of 10000, 3200 and 1243.398 W/m² respectively, not a component that may
be zero. Finest-mesh cylinder errors are about 0.0059% and 0.134% of those
scales. These are measured reference errors, **not promised bounds for other
shapes or boundary conditions**.

The original 0.001 W/m² target is still explicitly tested and missed by every
cylinder row. The original 0.0001 °C analytic-temperature target is also
retained: finest errors are about 0.000005, 0.0000963 and 0.000340 °C. The
fixed-power cylinder therefore still misses that strict temperature reference.
Neither target is replaced by a new permissive "flux pass" threshold.

Runtime temperature acceptance has a different, existing scope: three-mesh
regional extrema, energy/field/integration gates, material range and a
0.10001 °C criterion guard. It is not the strict analytic accuracy benchmark.
The fixed-power refined case passes that runtime check with a 35 °C upper
limit and a predicted maximum near 32.434 °C. This is only a model-temperature
decision, not a flux or product pass.

## Did the outputs mislead design decisions?

- The internally heated slab correctly fails its 42 °C limit: its interior
  maximum is 45 °C, although both end faces are 20 °C.
- Coarser cylinder meshes fail existing integration and/or free-node energy
  gates. Temperature-looking-good does not override these: results remain
  indeterminate and have no CAD design hypothesis. The axial case also has a
  deliberately near-limit temperature requirement; that is not a scoped pass.
- The refined fixed-power case passes all existing runtime temperature gates.
  It still advertises `pointwise_heat_flux_qualified: false`.
- A separate near-limit regression isolates the numerical margin guard without
  failed integration gates. Unsupported flux requirements are rejected rather
  than silently replaced by temperature checks.

Three generic feedback gaps were repaired:

1. Machine-readable coverage now states `requested_temperature_extrema` and
   explicitly withholds pointwise-flux qualification. Design feedback and the
   Viewer preserve that scope. This is applicable to all solid thermal cases,
   not a geometry-name rule.
2. Lower-temperature failures now identify the cold location and suggest
   investigating heat loss/delivery. Upper failures identify the hot location.
   Simultaneous violations keep both. A near-limit or corrupted result cannot
   trigger a confirmed CAD hypothesis. Viewer cards show the controlling bound,
   while the temperature field is explicitly the hottest instant.
3. A prescribed temperature can directly contradict a requirement on the body
   or a selected face, including their shared-edge nodes. Such a valid model
   failure now blocks CAD-only iteration and requests boundary/requirement
   review; it stays failed, not passed or silently given a different limit.
   Remote faces are not falsely declared to share that fixed temperature.

## Limits and reproduction

These are smooth, single-material, steady analytic cases. They do not cover
reentrant edges, tiny heaters, thermal contact, radiation, convection-field
prediction, transient local-flux accuracy or temperature-dependent materials.
No unique root cause of the curved reference's error has been established;
the earlier higher-order quadrature diagnostic did not eliminate it. No new
mesher or thermal solver has been introduced.

Use `scripts/verify_thermal_flux.py --out FRESH_DIRECTORY` for the nine base
solves. Use `--case cylinder_power --mesh-scale 0.75 --out OTHER_FRESH_DIRECTORY`
for the bounded follow-up. Analytical geometry names live only in the
verification script; production calculations have no case-name routing.
The command's `workflow_checks_passed` validates decisions and safe withholding,
**not the strict flux target**. Each row retains its separate strict-target flag.

Final local evidence is under `outputs/multiphysics-dev/flux-study-final-05` and
`flux-study-final-refined-06`; compact receipts are under `validation/multiphysics`.
The sandbox DLL failure (`flux-study-01`) and initial review (`flux-study-02`)
are retained. The first review harness expected the fixed-power temperature
pass without accounting for rejected coarse meshes; that harness expectation
was corrected to require withholding whenever an existing numerical gate fails.
The solver gates and original target records were not changed.

The final full regression passed **728 tests**, with no failures, errors or
skips (`validation/multiphysics/flux-final-51.xml`). A targeted feedback/Agent
review passed 64 tests. The fixed-power CAD cross-section iteration passed all
nine workflow checks; the additional cold-region Agent/Viewer review passed all
six checks. The live Viewer was inspected: the cold case shows 20.5 °C as the
controlling lower bound, while retaining both its 20.5–25.5 °C range and failed
status. This is a workflow review, not evidence of a real device's thermal
performance.
