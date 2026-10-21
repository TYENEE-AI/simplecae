# Agent API and immutable task evidence

The CLI's `analyze` command calls `analyze_case` directly so physical dispatch,
validation and retention have one maintained entry. Failures preserve their
original text and expose `recovery.code`, `retryable_unchanged`, `fields`,
`next_action` and `details` where available. Schema diagnostics remain compatible.
Python callers may use `simplecae.diagnostics.diagnostic(exception)`; known
workflow refusals carry the same fields on `WorkflowError.diagnostic`.
Unknown errors remain inspectable, never guessed into an automatic retry.
`task status --brief` propagates execution recovery and the declared mesh policy.

`simplecae.api.prepare_plan(plan_path, out)` validates an Agent-authored use plan and writes a small non-executing JSON/HTML review; `read_plan(path)` returns the validated input. It infers no physical facts and grants no completed-check verdict. For a selected immediate FEM item, `design_check(..., plan_path=PLAN, check_id=ID)` binds usage purpose, explicit load/support basis, expected criteria and unassessed scope to the existing analysis. `usage_feedback` is separate from raw model validity; missing requested criteria or a changed plan withhold a usage conclusion. See [use-driven checks](use-driven-checks.md).

For ordinary design iteration use `simplecae.api.design_check(case_path, out, context_path=..., depth='design', budget_seconds=3000, ccx=None, timeout='auto', preview=True, predict_capacity=False)`. The synchronous supervisor invokes the existing solver in an owned process tree and produces `design-review.json/html`; it does not modify physics or numerical gates. `compare_design_checks(review_paths)` verifies completed task/result and scope bindings. See [bounded checks](design-checks.md) for context fields, detailed opt-in, budget exhaustion and conditional conclusions. `analyze_case(..., predict_capacity=True)` preserves its previous behavior; False checks full requested loads without extra linear capacity decomposition. Preload/lock and requested buckling remain intact. Complete-result cache remains rejected with False; qualified linear solved-level reuse is supported with mode-specific keys. See refinement-continuation.md.

For a stable human review surface use the [local Viewer](viewer.md): `view --out SESSION`, then `analyze ... --viewer-session SESSION --label V1 --change-note REASON`. Actual stage records remain data; `SESSION/feedback/*.json` contains source-bound user annotations for the agent to read and clarify, not executed commands. The Viewer uses the existing design signal and task contract and cannot grant product acceptance.

The source toolkit exposes the same file-based synchronous behavior through CLI and `simplecae.api`: `check_case(path)` and `analyze_case(path,out,ccx=None,timeout=3000,preview=True)`. Output must be fresh. Analyze consumes data files, not arbitrary solver scripts. Cases use versions `1.0`, `2.0`, `assembly-1.0`, `robot-1.0`; results preserve the solid/assembly version or use `robot-result-1.0`. Signal/comparison versions are `simplecae-signal-1.0` and `simplecae-comparison-1.0`.

The local multiphysics development also dispatches `thermal-network-1.0`,
`thermal-solid-1.0`, `modal-solid-1.0`, `motion-loads-1.0`,
`fatigue-data-1.0` and `creep-data-1.0` through these same entry points.
Use task method `fem` for solid conduction and modal analysis; use `calculation`
for networks, motion loads and material-data durability. Method references are
linked from `SKILL.md`. These checks reject structural capacity/lifetime
extrapolation and unsupported cache/reuse requests; they do not silently
convert to a static solid analysis.

Machine-readable syntax contracts live in `assets/schemas`. `check FILE --kind case|result|signal|comparison` checks those contracts; case checks also apply stricter semantic/path/unit/parameter rules. Schema success does not prove that geometry, loads, numerics or physical assumptions are valid. Full checks remain in inspect/analyze. Unknown case keys are rejected by the Python validators.

Version1.2 also exposes `evidence`, `evidence-review`, `interface` and `task-family` contracts. `analyze-gripper TASK --out FRESH_DIRECTORY` and `simplecae.task_family.analyze_gripper_task` compile the task, preserve the optional nominal input, run all required force endpoints with shared source guards, and produce `task-family.json/html` plus individual source/analysis reports and an application overview. `--include-nominal` also evaluates the reference; a known failure in that analyzed reference is never hidden. Missing numerical evidence keeps the family unresolved, and a zero-force lower uncertainty bound remains an explicit known failure. There is no family ranking margin or product capacity flag.

`analyze_case(...,reuse_levels=PATH)` propagates through solid, assembly, envelope and component robot analyses. Unlike complete-result cache normalization, solved-level keys match exact input floating values and recheck DAT/decks. Read [refinement-continuation.md](refinement-continuation.md). Family caches must be outside the family's fresh output root.

Evidence review uses `simplecae.evidence` and optional `summarize --ledger FILE`. Individually referenced evidence files up to10MiB are copied with hashes into the review output, keeping links inside a narrow report directory. Bindings remain the tested original sources; copied records never grant measurement truth or update old versions. Larger files retain their original path/hash in JSON rather than requiring broad workspace serving. Interface measurements use `simplecae.interface_check` and explicitly declared source references; their match/mismatch states are not structural feasibility scores.

JSON files and CLI output useUTF-8, including Windows pipe output. Python consumers should specify `read_text(encoding="utf-8-sig")`. Results preserve source hashes and individual criterion records; requests for unsupported physics need a new model/contract, not reinterpreting an existing model pass.

Contract failures remain `ValueError`-compatible in Python (`ContractError.details`).
CLI errors include a `diagnostic` with a code, located issues and a next action.
Supported case versions come from the actual schema; changing a version label
cannot make CFD or coupled thermal stress into a supported calculation. A task
preflight retains the selected check id with this diagnostic. Compact task status
retains the Agent's reason, acceptance, assumptions and unassessed scope even
before a solver runs. These are declarations, not verified physical facts.

The analyzed task contract is recorded before execution; robot component physics and source hashes are captured before pose execution. Case files, all model files, semantic interface manifests, component templates and URDF assets are checked throughout one run; a changed or missing source invalidates that analysis and withholds its limit. These checks also span load-case and robot-pose envelopes. Posthoc comparison uses the saved contract and never silently reloads a changed template. Geometry/provenance revisions may change between candidates, while material, load/support/pose pattern, criteria, conditions and quality thresholds must remain comparable. Face-number selectors retain their source hash; regenerated geometry needs a new inspect/selector, and native interface/plane selectors are preferable for verified comparable regeneration.

Robot contracts include effective independent-joint actuator limits after applying explicit overrides to parsed URDF defaults, along with joint types. Changing a rating is a changed task criterion and is refused by the current fixed-actuator comparison; hardware replacement needs a separately declared task, verified hardware data and any relevant mass/cost changes. Robot records from 1.0.0 lack this evidence and must be reanalyzed before automatic comparison. `metrics.max_actuator_utilization` contains only actuator items; the overall bottleneck also includes requested component FEM criteria. Load-case envelopes include all requested child criteria, including elastic buckling and its validity gates.

Read `analysis_status`, `valid_for_comparison`, `feasible_under_stated_model`, `physical_conditions_verified`, `coverage` and `not_assessed` before metrics. `invalid` and `indeterminate` have no scalar favorable margin and no feasibility value. A valid infeasible design can provide negative constraint feedback. Unknown physical conditions prevent real-world load predictions even when the assumed-model numerical comparison is usable. `whole_installation_rating_available` is always false.

Use `compare A/result.json B/result.json --out comparison.json` with a shared explicit `provenance.task_id`. A changed load/material/fixture/criterion or invalid candidate is refused. No universal optimization reward is imposed: the engine may trade off measured mass/volume, stiffness, strength or actuator effort under its own declared task. Located strength feedback identifies the actual material/component criterion; its coordinate is an element centroid, not an exact integration point. Proposed edits remain hypotheses and require a new analysis.

Saved SDK fixtures demonstrate actual export/package interoperability and candidate iteration. SimpleCADAPI's own CAE demo and third-party solver wrappers do not replace this toolkit's numerical checks. Optional SDK generation is separate from core analysis and never executes uploaded generator code automatically.

For revision-bound mixed-method workspaces use `simplecae.api.start_task`, `run_task_check`, `record_task_check`, `task_status`; see [Agent tasks](agent-tasks.md).
