---
name: simplecae
description: Plan use-driven engineering checks for CAD and robotics agents. Select relevant parts and conditions for structural or thermal FEM, modal screening, robot compliance and motion loads, or material-data fatigue and creep checks; return located CAD iteration feedback with explicit evidence gaps.
---

# SimpleCAE

Start with how the user will use the object and what could impair that use. Select checks that can change a design decision, then use the intact toolkit for reproducible analysis and CAD feedback. Gmsh meshes the model; external CalculiX solves the supported elasticity/buckling problem. Geometry, visual colors and a URDF joint do not establish actual material, mounting, actuator capacity or a product rating.

Use the same task workspace for selected FEM and numerical calculations, geometry
records, missing information and physical follow-up. Read only the method needed
for the current decision from the table below. With a working runtime, proceed
directly to the user task. An optional `quickstart --out FRESH_DIRECTORY` checks one
real solver example; `--example all` is only for learning the other outcomes and
iteration. Reuse existing example results. Do not run full pytest, license audits,
release verification or resource calibration as routine installation prerequisites.
Opening Viewer does not require a reference solve. Installation is in
[README](README.md); [feedback template](assets/feedback-template.md) collects
reproducible issues without automatic upload. Ordinary installation does not require
a release receipt or source SHA-256 checks. Do not block installation to regenerate
receipts, compare GitHub raw files or rerun release suites. Release qualification is
a separate maintainer action (`install_local.py --verify-release`); installing a
checkout does not certify it as a qualified release.

For a smaller flat bearing pad against a larger flat CAD face, read [contained planar contact](references/contained-planar-contact.md). It requires exact trimmed-face CAD coverage and actual quadratic-mesh projection; it does not support arbitrary partial overlap, cylindrical bore contact or anchor pullout. Curved planar bolt ports preserve the CAD resultant centroid. Keep omitted fastener shear/bearing and clearance applicability separate from axial bolt evidence.

For contact opening or a rejected negative pressure, read [contact convergence](references/contact-convergence.md). Native convergence alone does not establish a unilateral contact state. Keep the raw pressure gate, inspect the located `contact-diagnostic.json`, and use gradual load increments when contact changes. Do not clip pressure, add a fictitious support or lower stiffness merely to obtain acceptance. Native iteration logs remain readable while a solve runs.

## Establish the task

For open-ended design requests, read [use-driven checks](references/use-driven-checks.md) before constructing a solver case. Translate the user's use scenario into observable success criteria and likely experience problems (binding, deflection, slip, damage, effort or installation movement). Ask only missing facts that could change the next decision; the Agent writes the plan, not the nonexpert user. Distinguish user requirements from screening assumptions introduced by the Agent.

For a usage-driven task, prefer [one-file task workspaces](references/agent-tasks.md): `task start TASK.json --out WORKSPACE --brief` derives plan/cases/context and creates the existing Viewer; `--run CHECK` explicitly selects one FEM or declared rigid calculation check. Use `task record` with a complete evidence file or explicit artifact, revision, outcome and observations for external checks; `task status --brief` gives compact next actions while retaining the full report. Declared detailed physics remains an explicit depth choice. If a measured joint contribution itself exceeds a task-probe limit, review its stiffness/held-state and permissible system changes before proposing link thickening; vector contributions can cancel. Sources and artifacts are revision-bound; new CAD needs a fresh workspace. External records are assertions, not independently certified facts. A passed check needs no repeat solve; an invalid one needs analysis repair before considering CAD changes.

Choose geometry/motion checks, applicable calculations, targeted FEM, physical tests or missing-information collection by the question. Record a small plan with `plan PLAN.json --out FRESH_DIRECTORY`; it reviews data without running checks. Select the parts/interfaces and normal or justified adverse conditions on the load path. A CAD assembly is an inventory, not a list of mandatory FEM jobs. Start with the controlling uncertainty; retain the reactions, interfaces and flexibility needed for that question even when only one component needs a solid mesh. Use existing CAD/robot tools for geometric checks rather than rebuilding their engines.

For a specified load-bearing or precision claim, keep required checks and unresolved interfaces visible. Deferring FEM does not verify strength. A single body pass cannot satisfy unmeasured grip, actuator, joint, installation or motion requirements. An explicitly requested existing solver case may use the direct analysis entry without inventing a new planning ceremony.

Collect the actual model/occurrence, units/frame, material and manufacturing assumptions, loads/poses, mounting regions, and task criteria. Ask consequential missing facts together in practical language. Record authorized assumptions; leave unverified physical conditions false. Do not infer a material, friction coefficient, sensor error, mounting or continuous rating from appearance.

Select the supported contract:

- Solid `2.0` (legacy STEP `1.0`): inspect/import one intended body and use explicit material, supports, loads and criteria.
- Assembly `assembly-1.0`: explicit independent bodies, materials and connections; never silently fuse them.
- Robot `robot-1.0`: SI URDF coordinates, named poses, inertials, external loads and any required component FEM. Rigid statics alone does not give link strength.
- Gripper task: explicit per-finger force and contact/load facts, optionally a measured holding interval plus error, finite pads, measurements and drive attachments.

For nonexperts use [the Chinese guide](references/product-guide.zh-CN.md) and `prepare MODEL --out FRESH_DIRECTORY`. The solid form selects full material faces, explains directional seat/guide/pin-position/stop constraints, and diagnoses missing common rigid modes. It supplies no physical facts or structural verdict.

## Run and iterate

Choose an attempt/time budget from the decision, available machine resources and observed solve cost, not a fixed allowance for every mesh. Read [execution resources](references/execution-resources.md) for contact/performance problems. `doctor` reports CPU/memory; completed native solves record elapsed time and work counts; each structural mesh writes an advisory `execution-plan.json`. `task run` and `design-check` default to `--timeout auto`, sharing the explicit total budget instead of an additional fixed per-solve cutoff. An explicit numeric timeout remains a hard cap. Do not change required service loads, contact laws, accepted accuracy or convergence tolerances to fit a computer. Adjust selected checks, qualified solver/thread choice, numerical continuation and local mesh allocation; retain unresolved outcomes when resources are insufficient. An unchanged computed check does not need another solve. `task run` rejects a repeat unless `--retry-reason` identifies a real execution/environment repair; choosing detailed depth after an explicit-depth refusal is allowed. Input/CAD changes need a fresh bound workspace. A reason is an audit record, not proof of a repair or a license to loop. Stop a branch when its total budget is exhausted.

When `next_action=review_model_validity`, distinguish mesh uncertainty from small-response or whole-chain transfer limits. Refining an already converged mesh does not repair an out-of-range linear model. Do not derive quantitative thickness/stiffness multipliers from unqualified displacement. A separately justified new geometry hypothesis may be checked afresh; preserve the original failure and all thresholds.

When FEM is useful, default to a justified **linear design check** with an explicit question, model scope, assumptions and unassessed items. Read [bounded design checks](references/design-checks.md); use `design-check CASE --context CONTEXT.json --plan PLAN.json --check-id CHECK --out FRESH_DIRECTORY --budget-seconds 600` for one selected check. Define the load path, load basis, physical supports and intended result criteria first; forces/moments/displacements are inputs and stress is normally an output. Inspect the existing load/support preview before solving. Task precision needs a relevant task probe, not a substitute global body displacement. The command preserves all numerical gates; it does not simplify geometry or invent equivalent fixtures. Cross-check gross forces/moments and examine assumptions that could reverse the decision.

Default checks retain the full requested loads and gravity, without optional capacity extrapolation; request `--predict-capacity` only when needed. Contact preload/lock and requested buckling remain physical stages. Automatic threads use a matching measured resource profile, otherwise serial. Before an expensive family of static/contact jobs, use `calibrate` on a representative retained deck and set `SIMPLECAE_RESOURCE_PROFILE` as described in [execution resources](references/execution-resources.md); this avoids repeating tuning for every CAD revision. A CPU count or executable name is not qualification. Preserve all native-field gates and inspect the selected count/reason in each native result. Keep actuator, grip, connection and task displacement controls alongside body criteria. Use only task-permitted CAD edits; do not reduce required loads or inflate ratings to obtain a pass. `--version` reports the invoked source version, which may differ from metadata in a reused runtime.

Escalate with `--depth detailed` when declared contact/preload, slip or requested buckling can change the decision. Default mode detects these features, including robot components, and requests an explicit model/depth choice without removing physics. Detailed and simplified mounting are separate model scopes. Keep a finite total budget; an exhausted attempt retains evidence and withholds acceptance, comparison and capacity. Avoid repeated long solves that do not resolve the design question.

Lead feedback with the effect on the user's stated use, then the controlling criterion and located evidence. Translate a valid failure into one concrete CAD hypothesis: actual feature/parameter, direction, mechanical reason, unchanged task conditions and what the recheck must establish. When feature mapping is absent, report the bound component/coordinates rather than inventing a CAD feature name. Check mating, motion, installation access and manufacturing effects after the change. A scoped pass need not trigger an unnecessary CAD edit. Numerical/environment failure is not evidence that the geometry is weak; resolve the analysis first. Generate a fresh revision when justified, rerun `design-check`, then use `design-compare`. A missing result criterion or unresolved required check cannot become a successful usage claim.

Bootstrap once from the skill folder: on Windows use `powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1`; on Ubuntu use `bash scripts/bootstrap.sh --ccx PATH`. The scripts keep separate `.venv` and `.venv-linux` environments. A supplied solver can use the setup option, `--ccx PATH` or `SIMPLECAE_CCX`. Use the selected environment's Python/CLI, not an unrelated global Python. See [Agent installation](references/agent-installation.md) for host discovery; do not rerun installation for ordinary CAD iterations.

```powershell
.\.venv\Scripts\python.exe scripts/simplecae_cli.py prepare model.step --out outputs/intake-001
.\.venv\Scripts\python.exe scripts/simplecae_cli.py check case.json
.\.venv\Scripts\python.exe scripts/simplecae_cli.py preview case.json --out outputs/loads-001
.\.venv\Scripts\python.exe scripts/simplecae_cli.py analyze case.json --out outputs/run-001
# Compile and analyze every required grip-force endpoint, retaining the nominal reference
.\.venv\Scripts\python.exe scripts/simplecae_cli.py analyze-gripper task.json --out outputs/grip-001
```

Inspect dimensions, selected material regions and the pre-solve force/moment/pose preview. STEP carries its native units and imports into mm; mesh units and occurrences must be explicit. Face IDs require the inspected source hash. Whole-face selectors are not partial patches: partition upstream. Solid displacement DOFs use analysis axes; assembly DOFs use world axes. Directional presets are displacement idealizations, not automatic free hinges, clearance, one-sided contact or actual mounting verification.

Output directories must be fresh; retain old failures and indeterminate results. Use at least three successively refined mesh sizes with each at least20% smaller. Ordinary design iteration skips doctor/import/package smoke unless the runtime fails. Keep meaningful equilibrium, field coverage, Jacobian/volume, convergence and small-response checks. A Windows native-loader failure is an environment failure; retain its record and retry only in the authorized normal process environment.

Inspect `mesh-native.log` and the located `mesh-diagnostic.json` when HighOrder optimization fails: every native Error rejects that mesh. Prefer source-bound local refinement of the affected curved faces before global refinement; modal checks also accept this existing option. On a native timeout, inspect `job.solver-diagnostic.json` for completed load stages and contact cost before choosing a justified retry. The toolkit records adaptive high-order Jacobians and signed inverse condition numbers, including actual uncropped strength/stress peak elements. A positive Jacobian alone does not establish accurate stress; poor element shape is a diagnostic, not permission to discard a peak or loosen convergence. See [mesh diagnostics](references/mesh-diagnostics.md).

`analyze` exposes stage progress on stderr (`--quiet` suppresses it). `--cache PATH` optionally restores complete valid numerical evidence for normalized matching inputs. `--reuse-levels PATH` can continue correctly solved levels from an indeterminate run, with exact matching and independent deck/DAT checks. Keep caches outside output. Changed physics, criteria, source or tools cannot inherit qualification; do not lower gates simply to turn a candidate green.

For many cases use `campaign MANIFEST.json --out DIRECTORY`, with explicit case hashes and optional source-bound evidence ledgers. It isolates native process failures and writes per-attempt completion receipts. `--resume` checks source, tool and artifact hashes before reusing finished attempts; a partially written result is not a completed analysis. See [campaigns](references/campaigns.md). CAD construction and optimization remain the calling agent's responsibility.

If a genuine local radius or bore controls convergence, declare whole-face `mesh.local_refinements`; their target size scales with every global mesh level. For a single unmounted solid under self-balanced internal loads, use exactly six `reference_only` material-point equations and a `relative_length` displacement criterion. Reference points establish a numerical gauge, not a fixture or actuator reaction. Read [local refinement and reference supports](references/local-mesh-and-reference.md) before using these modes.

When separate roots, bosses or mounting transitions can control the design, read
[local stress regions](references/stress-regions.md) and declare the relevant
regions. A stable global maximum does not verify every local feature. Keep region
definitions fixed across revisions; inspect all preload/locked/service endpoint
checks and located raw peaks before recommending CAD changes.

Read individual criterion confidence and located task measurements before proposing a CAD change. Send the generator a concrete hypothesis with its input conditions, source/result paths, affected region/criterion and unresolved gaps. Reanalyze the generated revision. Comparisons need the same task ID and unchanged task physics/criteria; a changed material, fixture, load or actuator rating is a new task contract.

## Interpret and deliver

Use the [local Viewer](references/viewer.md) for a stable model/field view, revision history and user annotations. Create a fresh session with `view --out SESSION`, then add `--viewer-session SESSION --label NAME --change-note REASON` to `analyze`. Review completed evidence and real stage records; do not infer completion from an old stage timestamp. Read `SESSION/feedback/*.json` as user review data bound to a result and region, not as automatically executed instructions. Resolve the user's intended change in conversation, preserve the previous result, then analyze a fresh revision. Viewer colors and display amplification do not alter solver verdicts, task comparability or product acceptance.

Daily CLI/API checks default to compact storage: after all readers/solvers stop, losslessly gzip native DAT/FRD/MSH, retaining every mesh, full field, input, decision and failed diagnostic. Read [storage](references/storage.md). Use `--storage full` / `storage='full'` for direct native-file debugging; ordinary design iteration needs no explicit cache. Never clean active outputs or discard a failure to obtain passing evidence. Check volume before a campaign; preflight is an estimate, not a storage guarantee. [Audit corrections](references/audit-1.3.md) define exact source-bound resume and incomplete-result rejection.

Read [interpretation](references/interpretation.md) before any capacity claim. `invalid` and `indeterminate` have no favorable comparison margin or feasibility value. A converged stiffness failure can remain explicit when strength is unresolved. `pass_under_stated_model` means the declared assessed criteria pass, with coverage and physical assumptions separate. Do not discard a hotspot by percentile/clipping.

Use a conditional limit only when `available` is true. In linear cases, fixed weight and declared fixed forces remain fixed while scalable loads increase together; geometry, distribution, pose, material and fixture remain those analyzed. Carry all conditions and `not_assessed` items with the value. A mass-equivalent or model pass is not an installation/product rating.

For planar compression/separation, Coulomb friction, equivalent axial bolt preload locking, or first-order URDF elastic transfer, read [contact and section transfer](references/contact-and-transfer.md). Supply bolt attachment patches, world axis, axial stiffness, target preload, axial allowable and source/applicability; do not infer torque, threads or fastening strength. Bolts use force-controlled tightening, locked adjustment and service stages; preserve any stage failure. Supply friction coefficient, tangential penalty stiffness and task motion limit. Evaluate actual requested loads without capacity extrapolation, contact cache/reuse or contact buckling. Relative material motion is not accumulated irreversible slip. Tree transfer defaults to rigid/locked joints; [equivalent joint compliance](references/joint-compliance.md) adds explicit scalar joint springs with source and held-state applicability. Joint torque, URDF effort, damping or friction does not provide stiffness. Cover every joint as compliant or explicitly rigid, reject coupled mimic/closed drive paths, preserve small-response screens and assess total task displacement. Keep numerical references separate from physical verification.

Deliver `report.html`, `result.json`, `signal.json`, source/input evidence, and concise actionable feedback. Gripper tasks also provide `task-family.html/json`: both low and high force endpoints require structure/effort/contact checks; nominal alone is insufficient. No endpoint result proves unmodeled interval buckling/contact/nonlinear behavior. Robot coverage lists links with and without FEM and unrouted drives. Visualization amplification and eigenmode amplitudes are display choices.

Use `summarize RESULT.json ... --ledger EVIDENCE.json --out FRESH_DIRECTORY` for a product evidence overview. Computed/software, unassessed, pending physical and externally recorded physical evidence remain distinct. A recorded test may fail, and hashes bind it to its tested revision without certifying its truth. Narrow report folders contain individually referenced small evidence snapshots; do not serve an entire workspace merely to view a report.

## Read only what the task needs

| Topic | Reference |
|---|---|
| Heat path or lumped temperature; spatial temperature when it changes the decision | [thermal networks](references/thermal-network.md), [solid conduction](references/thermal-solid.md). Temperature acceptance does not qualify local heat flux or hot strength. |
| Excitation-frequency separation; natural modes, not response amplitudes | [modal screening](references/modal-analysis.md) |
| Acceleration, braking, rotation; named rigid states, not a trajectory envelope | [motion loads](references/motion-loads.md), [typed rigid calculations](references/rigid-calculation-checks.md) |
| Repeated or sustained use; applicable stress history and material curves | [fatigue and creep](references/durability-data.md). Missing curves never imply infinite life. |
| Distinct local roots or interfaces, hardware resources and expensive solves | [stress regions](references/stress-regions.md), [execution resources](references/execution-resources.md) |
| One task file, mixed-method completion records and reanalysis signals | [Agent tasks](references/agent-tasks.md) |
| User scenarios, whether FEM is useful, load-path planning, targeted checks and iteration feedback | [use-driven checks](references/use-driven-checks.md) |
| Default design check, on-demand detailed verification, total budget and CAD feedback | [bounded design checks](references/design-checks.md) |
| Loads, gravity, moments, envelopes, buckling / legacy STEP | [advanced cases](references/advanced-cases.md), [case format](references/case-format.md) |
| STEP/GLB/STL/OBJ, transforms and generator interfaces | [model adapters](references/model-adapters.md) |
| Independent bodies and explicit connections / directional materials | [assemblies](references/assemblies.md), [materials](references/materials.md) |
| Planar friction, bolt preload locking / first-order elastic URDF tree | [contact and section transfer](references/contact-and-transfer.md), [joint examples](examples/joints/USE.md) |
| URDF statics and component coverage / closed drive paths | [robot cases](references/robot-cases.md), [actuation paths](references/actuation-paths.md) |
| Equivalent joint stiffness plus existing link deformation | [joint compliance](references/joint-compliance.md) |
| Gripper facts / finite pad force-torque closure / sensor force budget | [gripper tasks](references/gripper-tasks.md), [finite pads](references/finite-pad-grasps.md), [force uncertainty](references/force-uncertainty.md) |
| Material points, surface averages and relative displacement | [task measurements](references/task-measurements.md) |
| Directional support recipes / refine without overwriting evidence | [support presets](references/support-presets.md), [continuation](references/refinement-continuation.md) |
| Local whole-face sizing / self-balanced single solids | [local mesh and reference supports](references/local-mesh-and-reference.md) |
| Many cases, native crashes, completion and resume | [campaigns](references/campaigns.md) |
| Purchased dimensions/axes/source class / product evidence | [interface metrology](references/interface-metrology.md), [evidence ledger](references/product-evidence.md) |
| Python/CLI orchestration and canonical JSON contracts | [agent API](references/agent-api.md), [schemas](assets/schemas/case.schema.json) |

The file APIs consume data, not arbitrary uploaded executable solver code. [README](README.md) provides first use and local installation; [contribution guidance](CONTRIBUTING.md) describes meaningful checks. [Release requirements](references/release-requirements.md) bind qualification to actual delivered files. Current public releases carry `validation/public-release.json`; older previews use `public-preview.json`. Both omit private history. Reproduce release suites with `python scripts/verify_release.py --out outputs/verification-001`; do not run them for every ordinary CAD candidate. This is numerical/software verification, not physical material, hardware or product certification.
