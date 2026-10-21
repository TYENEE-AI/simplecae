# From use experience to targeted engineering checks

Use this route for an open-ended product or robot request before choosing a solver model. Existing explicit case execution remains available. The calling Agent interprets the user's words and authors the plan; the CLI validates and records it. There is no product-name classifier, hidden material assumption or automatic whole-assembly solve.

## 1. Identify what matters in use

Capture how it is held, installed, driven or loaded, the relevant operating states, what the user wants to observe, and what would make it unusable. Convert vague terms into the minimum useful checks: "smooth" can involve interference, backlash and friction; "accurate" can involve link, joint and installation displacement; "holds" can involve grip equilibrium and drive capacity as well as part strength. Do not turn every potential mechanism into a mandatory detailed simulation.

Ask consequential unknowns together in plain language. Reuse existing answers. A screening assumption is explicitly an Agent assumption, not a customer requirement or measured fact. Where no numerical acceptance is available, propose a justified preliminary check or a physical observation; do not invent a product rating.

Choose methods by information value and consequence:

- **geometry:** fit, insertion, clearance or kinematics, using existing CAD/robot capabilities. A discrete collision sample has a stated coverage boundary.
- **calculation:** an applicable balance, rigid motion-state load, thermal network, or material-data durability check. Record formula applicability and unmodeled mechanisms; a formula is not automatically a conservative bound.
- **fem:** stress, relevant task displacement, supported stability/contact mechanics, solid conduction or normal modes when this can change the next design choice.
- **physical_test:** running feel, print fit, uncertain friction/strength, wear or other behavior that the current model cannot establish.
- **information:** a missing fact or measurement that could reverse the answer.

The decision is `now`, `later`, `needs_information` or `unsupported`. For each check state why, the target region/components, acceptance meaning and whether it is required for the requested claim. An unresolved load-bearing claim stays unresolved even if a body alone passes. A noncritical deferred check can coexist with a fit/motion prototype delivery when its boundary is explicit.

Select new physics by the user's observable concern, not the product name:

| Concern | Smallest useful supported check | Consequential missing input | What a valid failure can guide |
|---|---|---|---|
| A region gets too hot, or heats over time | Lumped network if regional uniformity is justified; solid conduction for spatial variation | Heat input, heat path/boundaries, properties and permitted temperature/duration | Change conducting path, area or insulation placement; preserve heat duty |
| A structure may resonate near an operating frequency | Supported normal modes plus explicit excitation bands | Actual mounting, mass/density and frequency bands | Change section stiffness or unsupported span along the conflicting mode; recheck added mass |
| Acceleration/braking may overload a drive or mount | Prescribed motion-state loads, then selected structural checks | Inertials, q/qd/qdd, ratings and state coverage | Change permitted mass placement/lever arm; slowing down changes the requirement |
| Repeated use may cause damage | Located signed stress blocks with applicable S-N data | Cycle counts, stress ratio, temperature/manufacturing data | Reduce local cyclic stress and recompute the same duty |
| Sustained loading may cause drift | Constant-stress/temperature creep table check | Time, local stress, strain definition and applicable material data | Reduce local stress, then reassess the same duration; local strain is not global drift |

If the relevant input is absent, choose an information/measurement task rather
than inventing material data or running an unrelated FEM job. A coupled need
such as hot creep remains multiple explicit checks with an unresolved coupling
boundary; a computed temperature does not automatically qualify a creep model.

## 2. Model only the necessary load path

Choose the mechanism or interface likely to control the decision, then retain its input and reaction path. Some questions need a single critical part; others need equivalent supports, connection checks or first-order robot compliance. Omitting solid meshes does not authorize omitting controlling support flexibility, joint play or actuator/grip limits. Record omitted components, their reaction idealizations and why they cannot change the scoped decision, or retain them as unresolved required checks.

Before a FEM check, state:

1. Which use question and failure mechanism the model answers.
2. Load path: input to transmitting parts/interfaces to the actual reaction.
3. Force/torque/weight, direction, application region and source; relevant pose or normal/adverse state.
4. Support freedoms and basis: where physical motion is prevented and where it remains free.
5. Material/manufacturing applicability, result criteria and remaining uncertainty.

`load_basis`, `support_basis` and `load_path` are required for a plan check marked immediate FEM. They are explanations, not proof. Write the ordinary case and context with existing schemas and inspect `preview`; do not add fictitious constraints to make it solvable. Whole-face uniform traction is a declared idealization, not a resolved line contact or bolt bearing field.

Interpret these fields according to the selected physics. For conduction,
record heat input in W, the heat path, and temperature/convection boundaries;
do not invent mechanical restraints. For modal screening, record mass/mounting
and excitation bands; force amplitudes are not required for normal modes and
are not inferred. Supported multiphysics results have their own Viewer panels.

## 3. Record and select one check

For fewer files and a mixed-method completion overview, prefer [Agent tasks](agent-tasks.md). That wrapper generates the inputs below and binds external evidence to this CAD revision. The direct entry remains available.


The JSON contract is demonstrated by `examples/use-plans/*.json`. The Agent writes it; users can stay in ordinary language.

```powershell
python scripts/simplecae_cli.py plan examples/use-plans/manual-mechanism.json --out outputs/use-plan-001
python scripts/simplecae_cli.py design-check examples/preview/fail.case.json --context examples/preview/design-context.json --plan examples/use-plans/bench-fixture.json --check-id task-deflection --out outputs/focus-001
```

`plan` writes a small JSON/HTML review. It starts no worker, executes no geometry check or physical test, and grants no structural/product pass. `next_checks` is a work list, not completed evidence. Required deferred/unsupported checks remain open. Call a CAD tool or appropriate existing calculation/test procedure for non-FEM checks and keep its source-bound evidence.

`design-check --plan ... --check-id ...` selects exactly one `fem`/`now` item. Other methods, deferred checks, unknown ids, a different case `provenance.task_id`, or a mismatching optional `case_path` are rejected before the worker. `case_path` is relative to the plan and can be omitted while planning; when present it binds the input file. The plan snapshot, hash and selected check are saved in the design review. Changed plan bytes during execution withhold acceptance. A plan has no authority to weaken case criteria, thresholds or numerical gates. The Agent still checks that the actual numerical conditions represent its written plan; a matching id alone cannot prove that semantic judgment.

`result_criteria` names the exact criterion keys expected from `design_signal`: common single-solid keys are `strength` and `stiffness`; task probes and robot poses use their actual named/prefixed keys. Missing or unassessed selected criteria produce insufficient usage evidence even when a broader body result is a model pass. A successful link-local displacement cannot stand in for requested end-effector precision. Plan ids and names are descriptive, not keyword routes or executable code.

Plan comparisons require the same scenario, chosen check, acceptance, assumptions, required/deferred scope and iteration constraints, in addition to the existing physical task gates. Only `case_path` can vary for geometry revisions; record a change hypothesis separately in the design context. A different operating condition or relaxed acceptance is a new task.

## 4. Give useful human and CAD feedback

The report and Viewer show scenario, desired experience, selected targets, impact, scoped outcome, missing criteria and other required checks. `usage_feedback` links that information to existing governing criterion and located observations. It never changes the solver's original result or elevates component evidence into product approval.

For a valid failure, the Agent completes a specific iteration brief from the actual CAD source:

- usage problem and governing load/pose/criterion;
- bound model/region and the evidence supporting the hypothesis;
- actual feature/parameter and proposed direction, with a mechanical reason;
- user constraints to preserve and the next numerical or physical verification;
- mating, motion, tool access and manufacturability checks affected by the change.

Example: a converged bending displacement failure may motivate increasing the section depth in the bending direction. A tooth-root failure may motivate a real root transition or face-width change, with mating and axial stack rechecked. These are hypotheses, not automatic edits or guaranteed solutions. Keep full peaks; a support/load-boundary hotspot needs investigation, not automatic dismissal or automatic thickening.

A passing scoped check can retain the geometry and move to the next requirement. Missing material data calls for a consequential measurement. An invalid mesh or solver startup failure calls for analysis repair, not a diagnosis of insufficient strength. Preserve any independently confirmed individual failure when the aggregate is unresolved.

## Illustrations, not product rules

- A hand-operated printed mechanism used to observe motion can prioritize tooth compatibility, insertion, axial clearance and a fit test. A specified stall-torque or durability claim changes the plan and may require tooth/pin/interface checks. A named mechanism is not automatically exempt from structural analysis.
- A wall fixture explicitly required to hold a load has a structural claim from the start. Body FEM may be useful, while the fastening/substrate path remains separately required; body pass cannot resolve it.
- A robot positioning task starts with target error, pose/load and the compliance/reaction path. Use available joint/link models and explicit component coverage; do not mesh cosmetic shells merely because they exist in the URDF.

Keep planning evidence small. Reuse the existing compact numerical retention and Viewer; no separate CAD engine, broad optimization campaign or default all-part batch is introduced.
