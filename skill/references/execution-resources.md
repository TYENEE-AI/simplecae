# Resource-aware execution without changing engineering acceptance

`task run` additionally persists a cumulative branch allowance across checks and `task start --continue-from` revisions. `--budget-seconds` limits one worker; `--total-budget-seconds` sets the branch allowance on first execution. Revising that allowance later requires `--budget-reason`. The controller reserves before launch and charges measured execution/reporting time afterwards; final report/retention overhead can exceed the worker deadline and reduce the next attempt's allowance. See [agent-tasks.md](agent-tasks.md) for interruption and safe continuation. Standalone `design-check` has a per-run deadline, not a cross-workspace ledger.

## Retained-evidence advice

Default execution allowances are centralized in `scripts/simplecae/defaults.py`:

| Setting | Default | Override |
|---|---:|---|
| Task/design worker wall budget | 3000 s | `--budget-seconds` |
| Direct native solve timeout | 3000 s | `--timeout` |
| Structural/combined assembly elements | 500000 | `mesh.max_elements` |
| Solid thermal elements | 100000 | `mesh.max_elements` |
| Modal elements | 20000 | `mesh.max_elements` (no former 10000 schema ceiling) |
| Thermal retained field values | 30000000 | `mesh.max_field_values` |
| Display triangles | 250000 | `preview --max-triangles` |
| Imported surface triangles | 250000 | Bounded input guard; use source STEP for larger tessellations |
| Viewer file / expanded NPZ | 256 MiB | Shared structural, thermal and modal display guard |
| Advice planning headroom | 50% | Advisory, never an execution/accuracy gate |

Explicit existing case limits and task ledgers remain unchanged. Higher defaults
are planning room, not a promise that a machine can hold every allowed problem.
Finite positive timeouts use the platform's wait range rather than an arbitrary
24-hour ceiling. Keep deadlines finite. Do not inflate a user's explicit limit.
The 15-second owned-process termination wait is cleanup, not a solver cutoff.
Contact increment and quadrature caps remain computational guards: they do not
shorten the Agent wall budget, and increasing them without a contact study can
increase solve cost substantially. Calibration tolerances remain physics checks.
Source hashes, equilibrium, valid elements, contact signs and convergence gates
are unchanged. Preview coarsening attempts stay bounded and fall back to geometry
bounds; increasing retry counts would delay useful feedback without proving a mesh.

`advise CASE.json --evidence ANALYSIS_DIRECTORY --out FRESH.advice.json` returns
source-bound local-mesh and resource proposals without editing inputs or starting
retries. It accepts a result.json or a narrow analysis/mesh directory containing
mesh/resource diagnostics. Changed CAD hashes are rejected. For rejected curved
faces (or a nonconverged peak neighborhood), geometry requests h/2 or one quarter
of the measured face extent. Observed element counts and the declared budget can
limit that refinement: a tiny trimmed face must not imply an unbounded group-wide
mesh. `sizing_estimate` retains both the requested factor and the cost estimate.
If even the unrefined finest mesh exceeds that planning budget, a
`mesh_budget_conflict` replaces the sizing entry. These are trial heuristics,
not convergence or cost guarantees. `assembly_cost_coverage` sums observed bodies
and lists unobserved ones; a missing body keeps the total unknown. Local proposals
reserve headroom for observed other bodies against the combined assembly cap.
Merge entries with existing local sizing, retaining
stronger settings. A model-validity failure is not automatically a mesh problem.
If native high-order optimization fails without a located inverted element,
`location_basis` explicitly labels a broader trial over that body's curved faces;
it does not identify a defect or turn positive Jacobians into accepted numerics.

Element advice extrapolates observed counts to the finest requested h using
cubic scaling and 50% planning headroom. Field-budget advice uses actual retained
field counts. Same-run node/time observations reuse the existing cost projection.
All predictions are advisory and may underpredict. `execution-observation.json`
records actual stage intervals, total wall time, worker CPU and parent-process
high-water memory; solver-child peak remains explicitly unknown. Thermal stages
are emitted as well. `advise` includes this evidence and a same-workload planning
range, not a statistical confidence interval or a promise for changed meshes.
Native-only projections still exclude meshing/postprocessing, and available RAM
is not a sparse-matrix memory estimate.
The output never changes accuracy, loads or materials, and never retries. Once
numerics are resolved (whether design pass or fail), it stops suggesting mesh
repairs; unresolved cases without a located repair require inspection.

Use `doctor` to inspect logical CPUs and available/total memory. Missing memory
information is unknown, not zero. Core count alone does not predict sparse matrix
fill, contact overlay cost, operating-system load or solver thread safety.

`doctor.runtime_identity` identifies the active package/resource paths and Skill
hash; compare it to the intended checkout before assuming another task uses these
defaults. This does not install or upgrade another Skill copy.

`mesh-policy CASE.json`, task briefs and `advise` expose the physics-specific
mesh count/ratio contract, declared tolerances and a legal example. These are
planning diagnostics; no coarse-only result inherits converged acceptance.

`task run` / `design-check` now default to `--timeout auto`. This shares the
chosen `--budget-seconds` across the whole worker: meshing, all stages and mesh
levels. The supervisor still terminates owned processes at that deadline. It
does not extend a user cap or declare progress to be convergence. A numeric
`--timeout` still adds a strict per-native-job cap. Direct `analyze` retains its
numeric timeout. Default total budget is 3000 seconds, a configurable starting
point, not a universal CAE allowance.

Before a structural solve, `level-*/execution-plan.json` gives a rough native
time prediction from this run's completed node counts and wall times. With one
observation it assumes quadratic scaling; with two it fits an exponent bounded
to 1..3. This is advisory only, not a stopping condition or accuracy certificate.
Contact active sets, fill, Newton iterations, disk activity and other applications
can dominate. Include meshing, postprocessing and uncertainty when planning the
total allowance. Solves record actual elapsed seconds, factorization count,
equations, maximum contact springs and SPOOLES-reported threads. Old results
without timing are not silently treated as fast or free.

For an expensive task:

1. Select only checks that inform the user's decision. Keep the complete physical
   load path, required service endpoints and original acceptance thresholds.
2. Inspect mesh quality, contact spring growth, stage progress and elapsed cost.
   Use explicit local refinement to repair geometry representation or examine a
   hotspot; do not coarsen a hotspot to get a pass.
3. Measure parallel configurations on a representative completed native input
   before an expensive family of Agent tasks (see calibration below).
   `SIMPLECAE_SOLVER_THREADS=auto` is the default: it selects an applicable
   measured configuration, otherwise serial. A numeric value requests that
   count explicitly within CPU affinity. Never infer performance or correctness from
   the name `ccx_MT`, a CPU count, or a successful exit alone. Native pressure,
   Coulomb, preload locking, equilibrium and mesh checks remain mandatory.
4. Choose a finite total budget from these observations; allow auto sharing when
   a finer mesh reasonably costs more than a coarse one. Repeat an unchanged
   task only with a recorded execution repair. Stop on unresolved validity or
   resource limits; do not repeatedly increase the budget without new evidence.

## One retained calibration, automatic use in later tasks

Use the existing `job.inp` of a representative coarse or middle mesh. Do not run
a calibration for every CAD revision. A changed solver binary, machine or
different analysis family needs new evidence:

```text
simplecae calibrate PATH/job.inp --ccx PATH/ccx_MT --out NEW_CALIBRATION --threads 1 2 4 --timeout 120
```

The explicit finite allowance applies to each calibration job. Use a
self-contained SimpleCAE static deck (each step ends at native step-time 1),
with complete displacement, reaction, stress and strain
prints; staged contact/bolt prints are also compared. All candidate decks remain
byte-identical. At every printed time, displacement/reaction node IDs and all
four stress/strain integration points per C3D10 element must also cover the
exported NALL/EALL/FIXED input sets exactly. Matching two identically incomplete
outputs does not qualify a profile. Older profiles without this coverage record
fall back to serial. All printed times and field coverage are compared, including
contact and bolt rows, at `rtol=1e-6, atol=1e-9`; this is a numerical replay check,
not a change to engineering thresholds. Failures remain in `profile.json` and
cannot be selected. Native files are retained with lossless compression.

Set `SIMPLECAE_RESOURCE_PROFILE` to the resulting `NEW_CALIBRATION/profile.json`
in the Agent's process environment. Alternatively, explicitly request
`--profile .tools/parallel-windows.json` or `.tools/parallel-linux.json` when
calibrating a source installation. No global user configuration is modified.
Use the same solver (`--ccx`, environment, PATH or platform runtime configuration).

Subsequent native jobs automatically select the fastest completed configuration
that matches the solver hash, hardware identity and static/contact family, fits
current CPU affinity, and is at least 5% faster than the serial observation.
That 5% is a timing-noise policy, never a physical tolerance. Smaller decks remain
serial because threading overhead may dominate; larger decks reuse the measured
choice as a performance heuristic, not a speed guarantee. Defaults measure up
to 1/2/4 threads; `--threads` can include more when the task and machine justify it.
Every native result records its actual choice, profile hash, reason, available
memory observation and observed SPOOLES threads. Memory prediction is explicitly
unavailable: free RAM does not certify sparse-matrix fit. Concurrent task workers
should receive separate CPU affinities or explicit counts to avoid oversubscription.

Invalid/stale profiles fall back to serial with a recorded reason; they do not
crash or authorize numerical acceptance. Thermal, modal and buckling families
currently stay serial in auto mode until separately qualified. Explicit numeric
requests remain possible and still run all normal result checks.

Changing load *increments* controls numerical continuation, not the physical
load. Friction and opening may be path-dependent: retain stages, endpoints and
an incremental reference. Do not weaken a contact count/residual criterion,
ignore negative pressure, invent a lower service load or lower requested
accuracy to meet a time estimate. A lower-fidelity design model must be a
separate explicitly justified scope and must not inherit the detailed verdict.

## Root stress and CAD iteration

The raw full peak, its element-centroid location, corner edge lengths and
adaptive element quality remain available. When stress mesh comparisons fail,
Agent feedback preserves the three peaks and distinguishes stable displacement
from local strength. Its cause remains `unresolved`, not automatically
`singularity`, `weak part` or `pass`.

For a suspected reentrant sharp edge, hold CAD, physics and the remote mesh fixed
and refine locally. Check peak growth/location and actual element quality;
fixed physical offset stress samples can diagnose locality, but cannot replace
the full peak in acceptance. A documented physical radius or an explicit CAD
revision can remove the idealized corner. It requires a new analysis; no stress
clipping, percentile substitution or hotspot exclusion is permitted. Converged
global assembly maxima can still hide a growing secondary region: retain
identified local studies and unresolved task checks alongside the assembly
result. Do not interpret one converged three-mesh sequence as proof of
asymptotic convergence at every sharp edge.

## Evaluated existing approaches

Elastic buckling additionally verifies reference-load scale invariance. Some
CalculiX builds can miss factors below one ([upstream issue 74](https://github.com/Dhondtguido/CalculiX/issues/74)).
SimpleCAE retains the original eigenproblem and up to three normalized attempts,
checks the positive spectrum after converting factors back to the original
load units, and shares the native timeout across attempts. Only the scalable
eigenproblem reference is normalized: service loads, fixed preload, criteria
and the task contract stay unchanged. Failure to establish invariance withholds
acceptance. The native factor target of 100 is numerical conditioning, not a
required engineering safety factor. Old results without this qualification are
not ranked as valid buckling evidence.

Owned analysis workers also contain their native descendants: Windows uses a
kill-on-close Job Object; POSIX uses a guardian in the worker's private process
group. A direct worker kill therefore does not leave its solver running.
Startup and lock recovery share a launch lock, so a delayed worker cannot start
native tools after its abandoned launch has been cancelled. Interrupted attempts
retain their budget reservation and evidence; no elapsed-time guess resets it.

CalculiX supports parallel assembly/results and multithreaded SPOOLES only when
the build links the appropriate implementation. See the author's
[parallel execution documentation](https://www.dhondt.de/ccx_2.14.pdf) and
[SPOOLES interface source](https://github.com/Dhondtguido/CalculiX/blob/master/src/spooles.c).
Face-to-face contact overlays both surface meshes and introduces integration
springs; volume element count alone is a poor cost indicator.

[PaStiX4CalculiX](https://github.com/Dhondtguido/PaStiX4CalculiX) and the
[TUM integration study](https://mediatum.ub.tum.de/doc/1575696/1575696.pdf)
offer another direct-solver route. It needs a compatible build and numerical
qualification; no replacement binary, GPU stack or new dependency was installed
for this repair. The bundled threaded solver sufficed for the measured timeout.
Previously adverse iterative-solver results remain recorded, not retried as a
silent fallback.

The diagnostic pattern for a sharp corner is consistent with
[COMSOL's singularity explanation](https://www.comsol.com/blogs/how-identify-resolve-singularities-model-meshing/).
That explanation is not proof for a specific model; the mast-specific controlled
study and full-field evidence are in [the performance audit](mast-performance-audit.md).
