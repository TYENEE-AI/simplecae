# Bounded checks and CAD iteration

For an open-ended product request, first use [the use-driven workflow](use-driven-checks.md) to choose which question and load path needs FEM. `plan PLAN.json --out FRESH_DIRECTORY` records the Agent's reasoning without executing checks. `design-check ... --plan PLAN.json --check-id ID` binds one immediate FEM item; omitted/deferred scope stays explicit. Direct existing case execution below remains compatible.

Use `design-check` as the default agent entry for an explicit **linear design model**. It invokes the same `analyze` workflow, at least three mesh levels, all integration-point peaks and the same equilibrium, field, material, convergence and small-response gates. It changes no mechanical inputs or tolerances. Existing `analyze` and Python APIs remain available.

The default checks the **full requested load, including gravity**, without estimating maximum capacity. `--predict-capacity` explicitly requests the legacy conditional extrapolation and any extra fixed-load solves. Existing `analyze` / `analyze_case` keep their previous prediction default; use `analyze --no-capacity` or `analyze_case(..., predict_capacity=False)` for requested loads only. This option never removes physical contact preload/lock stages or requested buckling/prestress steps. Cache/reuse with prediction disabled is not qualified and is rejected. Capacity is explicitly unavailable when it was not requested, even if the requested model passes.

The existing robot task-point/section-transfer evaluator consumes full and fixed component fields for its displacement accounting and screens. Those auxiliary fields remain when robot probes require them; disabling capacity does not remove that evaluation or replace missing fields by zero. Conditional payload limits are still withheld. Ordinary solid probes do not require this extra decomposition.

The default `SIMPLECAE_SOLVER_THREADS=auto` uses an applicable measured profile,
otherwise one thread. A numeric value explicitly requests a CPU-affinity-bounded
count; design checks retain all ordinary numerical gates. Select a capable solver
build and compare every printed field/time on a representative retained input
before adopting its profile. Earlier inconsistent parallel experiments remain
failed evidence; a later successful replay does not retroactively qualify them
or establish every model/build combination. See
[measured resource selection](execution-resources.md) and
[tested platform scope](platform-evidence.md).

```powershell
python scripts/simplecae_cli.py design-check examples/preview/fail.case.json --context examples/preview/design-context.json --out outputs/design-001 --budget-seconds 600
python scripts/simplecae_cli.py design-check examples/preview/iteration.case.json --context examples/preview/design-context.json --out outputs/design-002 --budget-seconds 600
python scripts/simplecae_cli.py design-compare outputs/design-001/design-review.json outputs/design-002/design-review.json --out outputs/design-comparison.json
```

The small context JSON contains nonempty `question` and `scope`, and explicit `assumptions` and `not_assessed` string lists; optional `change_hypothesis` records the proposed edit. Lists may be empty when there is nothing to declare within that scope; entries must be meaningful, nonempty text. Record actual consequential assumptions, not boilerplate. Empty lists do not establish physical verification or expand the solver's supported scope. For a robot task the review also retains existing effort/component/pose feedback and coverage. A rigid-only robot calculation cannot acquire link-strength coverage through this wrapper.

The optional usage plan is a separate source-bound record. It links a scenario and user impact to targets, load/support basis, exact `result_criteria` and other required checks. Missing or unassessed selected criteria withhold the usage conclusion even if the raw body result passes. `usage_feedback` keeps raw numerical validity separate and never grants product approval. A changed scenario/acceptance or planned scope rejects comparison; a fresh geometry case path is allowed. Plan edits during the worker also withhold acceptance while preserving the original numerical files.

Choose the analysis depth by the decision:

- **Default `--depth design`:** explicitly justified linear solid, assembly or posed robot model. Use gross force/moment checks to cross-check the load path, and investigate sensitivity to the assumptions that could change the decision. Equivalent fixtures are scoped approximations, not measured real connections. A contact/bolt/buckling case produces `needs_explicit_model`; nothing is silently removed or substituted.
- **On demand `--depth detailed`:** run the supplied contact, bolt preload/locking or buckling case when its behavior can change the decision, or when requested. This is a separate declared model; do not rank it against a differently supported linear model. All existing detailed-physics limitations remain.

`--budget-seconds` bounds the **whole analysis worker**, including meshing, all mesh levels, fixed loads, component/pose tasks and native solves. Default 600 seconds; `--timeout auto` (the default) shares this total without an independent per-solve cutoff. A numeric `--timeout` adds a strict per-solve cap. Use [resource observations](execution-resources.md) to choose the total; there is no automatic deadline extension or criterion relaxation. On exhaustion the supervisor terminates its owned worker/descendant solvers, preserves logs and existing raw files, marks the review `budget_exhausted`, and withholds acceptance/ranking/capacity. Termination/report cleanup adds a small overhead. Native-loader failures remain environment failures. Startup/input validation before worker launch is not part of the solve budget.

CLI exit3 means budget exhausted or an explicit model/depth choice is required; exit2 means invalid input/failed execution. Exit0 means the worker completed, **not** that the structure passed: inspect `model_status` and criterion evidence, including expected failure and insufficient results.

Inspect `design-review.html` or `design-review.json`. They identify the decision scope, execution state, completed endpoint observations, individual criterion decisions, governing utilization, located findings, physical assumptions and next actions. Preload/locked findings remain separate from service findings. A geometry suggestion is a hypothesis to reanalyze, not a promised improvement. Review the unchanged `analysis/result.json`, `signal.json`, raw files and report for full evidence. An insufficient aggregate result can retain a confirmed individual failure, but cannot supply a favorable overall margin or design ranking.

Keep the task contract fixed when selecting an action. A generic suggestion to reduce a load or increase an actuator rating is not permission to change the user's requirement. Choose permitted geometry changes and rerun the task. Individual stiffness evidence can remain useful while strength is unresolved; a located peak still needs examination against the actual support/load transition. Unmeasured physical flags block capacity/product claims, not a declared mathematical model's useful conditional failure or CAD hypothesis. A budget stop is an execution result, not evidence of material failure. Interrupted or malformed result bytes and worker logs are retained; they never become accepted results.

Run the CAD generator on a fresh revision, preserve the old attempt, then repeat with the **same task, context, material, load, fixture, criteria and validity gates**. `design-compare` recomputes the existing numerical comparison and also checks review/result hashes and identical scope/assumptions/depth; only geometry and the recorded change hypothesis may vary. Changed support/preload/material or physical scope defines a separate task contract. Do not search for a mesh, fixture or parameter set just because it gives green output.

Use `--viewer-session SESSION --label NAME --change-note REASON` for actual stage/revision history. The Viewer shows the design question, scope, budget and next actions with the fields. A budget interruption ends its stage record and retains the logs; it does not leave a false running/completed analysis.

**Conditional model pass is never product pass.** Unverified PETG, print direction/infill, creep, anchors, friction/preload and wall capacity remain explicit wherever relevant. The useful outcome can be a verified model improvement or a precise next measurement; more digits, a green contour or a completed solver do not verify physical assumptions.
