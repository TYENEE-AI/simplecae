# One task file and mixed-method completion records

## Cumulative execution and qualified continuation

`task run --budget-seconds` limits one worker. The first attempt establishes a
persisted branch allowance (the same value unless `--total-budget-seconds` is
given). Later checks and retries consume its remaining time; increasing the
per-attempt value does not reset it. `task status --brief` exposes spent/remaining
time and `execution_next_action: review_execution_budget` when exhausted.
Use `task start NEW.json --out NEW --continue-from OLD` for a CAD revision of the
same task_id: it shares the allowance, not prior completion or numerical results.
An independent task starts an independent allowance; do not evade an exhausted
branch by renaming its workspace.

Plan enough total time for the chosen checks. A justified, authorized allowance
change uses `--total-budget-seconds NEW_TOTAL --budget-reason TEXT`. This is
separate from `--retry-reason`, which identifies an execution repair. Both the
old attempts and allowance changes remain in `execution-budget.json`.
The worker deadline remains hard. Report/retention overhead is charged afterwards
and can exhaust the branch; it is not itself interrupted mid-write. A killed
controller retains its full reservation. Confirm workers have stopped before
handling a leftover budget lock; never delete the budget ledger as cache.

For qualified linear solids and bonded assemblies, pass the same explicit
`--reuse-levels CACHE_DIRECTORY` on the first and subsequent `task run` or
`design-check`. Complete mesh levels are saved before the next level starts;
incomplete/corrupt levels are not reused. The cache is separate from outputs.
Requested-load-only and capacity/fixed-response modes have distinct keys.
Every reused level rechecks native decks/fields, and the new run still performs
the full convergence and task assessment. Contact history, thermal, modal and
robot continuation through these task entry points remain unsupported and are
rejected before launching a worker. Do not substitute simpler physics to resume.
Direct `design-check` remains one bounded attempt; use tasks for cumulative
branch accounting. Python uses `continue_from`, `total_budget_seconds`,
`budget_reason`, and `reuse_levels` with the same meanings.

Repeated `task run` on an unchanged computed check is rejected before a worker
starts. Read `task status --brief` first. An identified execution/environment
repair may be retried with `--retry-reason TEXT` (Python `retry_reason=...`);
the reason and every prior result remain in history. Selecting `--depth detailed`
after an explicit-depth refusal needs no extra reason. New CAD or numerical
inputs require a fresh revision. Set a small task-appropriate retry budget;
the reason records a decision and does not certify that the repair is valid.

`next_action: review_model_validity` distinguishes a failed linear small-response
or robot transfer screen from mesh refinement. Its compact evidence retains the
original thresholds and gate values. Unqualified displacements provide no
quantitative stiffness/thickness multiplier, while individually converged,
valid failed criteria remain visible even when another criterion is unresolved.

Use this optional entry for a usage-driven CAD iteration. Existing `plan`,
`design-check` and numerical APIs remain available. The calling Agent decides
what to check; no product-name routing, automatic load invention or all-part solve.

```powershell
python scripts/simplecae_cli.py task start examples/tasks/bench-fixture.task.json --out outputs/task-v1
# Preparation starts no solver. Select exactly one ready FEM or explicitly computed rigid calculation check:
python scripts/simplecae_cli.py task run outputs/task-v1 --check task-deflection
python scripts/simplecae_cli.py task status outputs/task-v1 --brief
# Explicit preparation plus one solve:
python scripts/simplecae_cli.py task start examples/tasks/bench-fixture.task.json --out outputs/task-other --run task-deflection
python scripts/simplecae_cli.py view --session outputs/task-v1/viewer --serve
```

The file has the same fields as `simplecae-use-plan-1.0`, with
`schema_version: "simplecae-task-1.0"` and these additions:

- `sources`: existing files defining this CAD revision and relevant inputs,
  relative to the task file. Include editable CAD sources. Cases, models and
  generated inputs are also tracked automatically; list other dependencies
  that cannot be inferred, such as local CAD helper modules and calibration data.
  Referenced URDF meshes are bound automatically in dev9; no directory scan.
- `cases`: optional map of check id to a complete inline case or case file path.
  Paths resolve against the containing file. All existing physical inputs and
  thresholds are preserved. A missing case task id derives from the task;
  a conflicting id is rejected. A planned FEM item without a case cannot run.
- `change_hypothesis`: optional concrete CAD change and mechanical reason.

The toolkit generates plan, cases and contexts, and creates a Viewer. Select
checks explicitly; loads, supports, materials and criteria are never guessed.
Use `--viewer-session EXISTING_SESSION` for several fresh CAD revisions in one
Viewer. Keep each revision's sources immutable; start a fresh task/workspace
after a CAD change. Existing `design-compare` accepts generated
`runs/*/design-review.json` only with matching task, context, physics, criteria
and numerical gates.

## External checks

CAD tools, scripts and people execute geometry, calculations, information
collection and physical tests. Record actual evidence with:

```powershell
python scripts/simplecae_cli.py task record outputs/task-v1 --check fit --evidence fit.evidence.json
```

An evidence file requires exactly:

```json
{
  "schema_version": "simplecae-check-evidence-1.0",
  "task_id": "the-task-id",
  "check_id": "fit",
  "method": "geometry",
  "revision_sha256": "copy from task start/status",
  "outcome": "insufficient_evidence",
  "summary": "Actual observation and scope of the check",
  "observations": ["Measured facts, method, units and comparison with acceptance"],
  "limitations": ["Coverage limitations that still matter"],
  "artifacts": ["actual-measurement.json"]
}
```

`outcome`: `pass`, `fail` or `insufficient_evidence`. Artifacts must exist, with
paths relative to the evidence file. The artifacts and original evidence file
are hash-bound to the revision; only small metadata is copied. These are
**externally recorded assertions**, not independent certification. Never record
a simulated physical test as an actual test. FEM and computed calculation cannot use this path; only a
computed review can complete it. Unsupported checks need a new justified plan.

`task status` rechecks source/artifact hashes. Missing or changed evidence
withholds that check's result and cannot reveal an older pass. All attempts stay
in history. Changed CAD inputs invalidate checks and block new runs/records in
the old workspace. Checks without evidence remain pending, including deferred
required checks. Actual completed deferred external checks can be recorded.

The overview gives outcome, provenance, history and next action for each check
in `task-status.json/html` and the existing Viewer. Passing all declared required
checks gives `declared_checks_complete`, never product approval. Unknowns and
external limitations remain visible. A lock rejects concurrent mutations;
confirm owned workers have stopped before removing an interrupted `task.lock`.

## Reanalysis signals

`usage_feedback.cad_iteration.requires_reanalysis` is true for an effective model
failure motivating a CAD change, with `reanalysis_trigger: after_design_change`.
A scoped pass returns false / `none_for_this_check`; continue other checks.
Incomplete/invalid analysis returns false /
`after_input_or_analysis_repair_if_needed`; repair inputs or execution first,
then decide whether to rerun. False never authorizes skipping checks affected
by a later CAD, physics or criterion change.

`simplecae.api` exposes `start_task`, `run_task_check`, `record_task_check` and
`task_status`. Numerical runs retain the existing compact storage, budget,
full peaks and quality gates. Status reading starts no solver.

## dev8: shorter Agent calls, same evidence gates

All four task operations accept `--brief`: stdout omits repeated history and
limitations, but retains required pending items, unknowns, provenance, the
governing numerical criterion, meaningful next action and full-report path.
The complete report and all peaks/fields remain on disk. A passed body plus a
pending physical check stays insufficient overall, with separate completion
counts so this is not mistaken for a failed solver.

For an existing geometry/calculation/information/test artifact, the CLI also
supports direct recording without a second boilerplate JSON:

```powershell
python scripts/simplecae_cli.py task record WORKSPACE --check fit --artifact measurement.json --revision HASH_FROM_TASK --outcome fail --observation "Measured clearance 0.1mm < required0.3mm" --limitation "Nominal CAD only" --brief
```

`--artifact`, `--observation`, `--limitation` may repeat. The explicit expected
revision must match current unchanged inputs; stale/missing hashes, missing
artifacts, absent observations/outcomes and FEM overrides are rejected. The
record remains an external assertion. Python accepts these same named fields
through `record_task_check(..., revision_sha256=..., artifacts=[...], outcome=...,
observations=[...], limitations=[...])`; paths resolve against the current
working directory in direct mode. File evidence keeps its own relative base.
Do not mix the two input styles.

For human-readable progress, supply a short `summary` / `--summary` containing
the actual observation, comparison and scope (for example, measured clearance
versus its declared requirement). Keep detailed script JSON in the bound
artifact and observations. Brief stdout and Viewer show bounded explanations;
complete records and artifact hashes remain available.

State external-check coverage explicitly. A measured clearance or one wall
does not establish every required fit or minimum thickness; an overall
positive volume does not check them. If later review finds omitted coverage,
append corrected evidence/outcome to the unchanged revision and retain its
history. New CAD needs a new revision. The task recorder cannot independently
prove arbitrary external observations true.

Cases are checked with the existing static contract/semantic validators before
creating a task workspace and again before starting its worker. This catches
invalid units/types and unresolved references without meshing or guessing a
conversion. Model interface sidecars and URDF package-root paths preserve their
original base directory. Referenced URDF mesh assets are read with the existing
URDF resolver and bound automatically, including package roots. Missing assets
and invalid component templates stop preparation before a worker starts. Older
workspaces missing these bindings retain their history but withhold acceptance
and request a fresh revision. Arbitrary CAD helper dependencies still need
explicit sources; no unbounded directory scan is added.

If default depth withholds declared contact/preload/buckling, the check returns
`choose_analysis_depth` and a suggested explicit `task run ... --depth detailed`
argument list. This never starts detailed physics automatically or drops it.

For a valid controlling robot task-probe failure, an actual joint-only
contribution above that probe's limit returns `review_joint_compliance`.
Its link/joint/total values use the declared direction (or norm when absent).
They are not summed magnitudes and do not prove all possible redesigns fail.
Review output-side stiffness and held-state data, then allowed system changes;
link thickening alone is not guaranteed to solve the usage problem. The raw
result, failure criterion and comparison gates are unchanged.

For rigid statics without component FEM, read [calculation checks](rigid-calculation-checks.md). External calculations remain artifact receipts; explicit computed calculations bind named criteria and cannot use external overrides.
