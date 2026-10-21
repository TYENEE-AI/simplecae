# Resource-aware execution without changing engineering acceptance

Use `doctor` to inspect logical CPUs and available/total memory. Missing memory
information is unknown, not zero. Core count alone does not predict sparse matrix
fill, contact overlay cost, operating-system load or solver thread safety.

`task run` / `design-check` now default to `--timeout auto`. This shares the
chosen `--budget-seconds` across the whole worker: meshing, all stages and mesh
levels. The supervisor still terminates owned processes at that deadline. It
does not extend a user cap or declare progress to be convergence. A numeric
`--timeout` still adds a strict per-native-job cap. Direct `analyze` retains its
numeric timeout. Default total budget is 600 seconds, a configurable starting
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
