# Data-backed fatigue and creep

Local, unreleased development on the dev10 source. Use these checks when
repeated service or sustained loading could change the design decision. They
consume located stress evidence and applicable material data; they do not
automatically convert a static von Mises maximum into a life prediction.

## Choose the question and inputs

- Repeated, approximately uniaxial elastic stress: `fatigue-data-1.0`.
  Supply counted cycle blocks at each selected location, minimum/maximum signed
  axial stress in MPa, and cycles. Each point must cover every service block.
- Constant uniaxial stress at constant temperature: `creep-data-1.0`.
  Supply stress in MPa, duration in seconds, and a strain-versus-time table at
  measured stress levels. Distinguish `creep_only_magnitude` from
  `total_axial_strain_magnitude`; strain is dimensionless, not percent.
- Missing material curves, temperature coverage, manufacturing/orientation data
  or trustworthy local stress: collect evidence first. A static pass cannot
  supply missing fatigue or creep data.

The Agent selects locations from the load path and existing stress results,
including potential controlling transitions and interfaces. Record coordinates,
frame, axial direction and target names. Point selection is declared scope,
not automatic proof that the whole component was examined. Preserve separate
static strength, instability, interfaces and physical tests.

Geometry, stress and service evidence each require a path, SHA-256 and basis.
Material curves additionally require source, material ID, manufacturing process,
orientation, temperature and applicability basis. Hashes establish which files
were used; they do not independently validate curve transcription or the
declared stresses. `mathematical_reference` data tests software only. Do not use
it as PLA/PETG or any real-material data.

## Computation and boundaries

Fatigue uses amplitude `(maximum-minimum)/2`, mean stress and
`R=minimum/maximum`. It selects an explicitly matching R curve, interpolates
log stress amplitude versus log cycles to failure, and sums Miner damage
`D=sum(n/N)`. The user/Agent supplies a justified `max_damage` criterion.
Damage is not failure probability. No automatic mean-stress correction,
rainflow counting, endurance limit, extrapolation or infinite-life claim.
The caller must justify counted blocks and the signed uniaxial approximation;
multiaxial/nonproportional fatigue, plastic low-cycle fatigue, sequence effects,
crack propagation and fatigue-creep interaction remain outside scope.

Creep linearly interpolates a complete table in time and absolute stress,
within one stress sign and one fixed temperature. Tables start at time zero;
creep-only strain starts at zero. No smoothing of nonmonotone data, extension
past the last time, temperature interpolation, relaxation/recovery, variable
stress history, redistribution or rupture prediction. A local strain check
does not predict whole-part displacement. The `max_strain` criterion must use
the same strain definition as the data.

Outside-data requests remain `indeterminate`, including arbitrarily small
endpoint exceedances. Missing blocks cannot be silently omitted. Unsupported
locations prevent an overall favorable result; known partial fatigue damage
is retained as a lower bound. Threshold equality within the numerical guard
is unresolved. No criterion means no pass.

## Agent and Viewer workflow

Use the existing task workspace with `method: calculation`, bind the case to
one selected check and run `task run WORKSPACE --check CHECK --brief`.
`check`, `analyze`, `design-check` and result comparisons dispatch the same
schemas. Canonical fields are exported in `assets/schemas/case.schema.json`.
There is no additional service or native solver dependency for these screens.

On a valid failure, trace the named location to a permitted CAD change:
increase the carrying section, improve a transition, or reduce an allowed
lever arm. These are hypotheses, not guaranteed improvements. Recompute the
signed local stresses for the revised CAD and reassess all required points.
Comparison freezes material data, temperature, service, acceptance criteria
and point identities. Reducing the requested cycles/load duration or changing
material is a different scenario, not a geometry improvement.

An invalid analysis or missing curve requests evidence/analysis repair before
CAD redesign. A pass under the stated model leaves product acceptance and
physical validation separate. Source changes invalidate task evidence.

The Viewer displays a selectable location, fatigue block table and damage,
or a creep strain/time curve with the specified limit. Coordinates and frames
are retained without inventing a spatial field. History preserves failures,
revisions and missing-data attempts. The display uses percent for creep;
JSON retains dimensionless strain. Compact output keeps inputs, full relevant
history, signal and report; no mesh cache is generated.

Reproduce the bounded STEP/Agent iteration showcase:

```powershell
.\.venv\Scripts\python.exe scripts/verify_durability.py --out outputs/FRESH_DURABILITY
.\.venv\Scripts\python.exe scripts/simplecae_cli.py view --session outputs/FRESH_DURABILITY/viewer --serve --port 8814
```

This constructs uniform rectangular STEP sections, checks their CAD volume
against exact dimensions, and derives axial stress from F/A. Fatigue damage
changes from 0.30 to 0.03 at unchanged service and a 0.20 limit. Creep strain
changes from 0.02 to 0.005 at unchanged service and a 0.01 limit. The curves
are mathematical references, and connection hotspots are unassessed.

Method references:
[COMSOL cumulative damage](https://doc.comsol.com/6.4/doc/com.comsol.help.fatigue/fatigue_ug_sme.4.25.html)
and [ANSYS material model selection](https://ansyshelp.ansys.com/public/Views/Secured/corp/v251/en/ans_mat/selectmatmodel.html).
No external code or additional dependencies were copied.
