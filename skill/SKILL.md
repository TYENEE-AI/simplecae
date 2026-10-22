---
name: simplecae
description: Plan use-driven engineering checks for CAD and robotics agents. Consume STEP plus source-bound interface.* manifests and scadpkg identity metadata; return structural, thermal, modal, robot or material-data screening and located CAD feedback with explicit evidence gaps.
---

# SimpleCAE

先按用途选检查，再计算，最后解释边界。三步：①写清需求、假设和缺项；②执行最小有用检查；③按状态修分析或改 CAD，并保留新旧证据。五条底线：不猜物理事实；不改载荷求绿；不把无效当弱；不把局部通过当产品通过；不把未做的实测记成通过。

Plan from use → run a selected check → act on qualified evidence. The Agent writes the inputs; the user can stay in ordinary language. Numerical screening helps a design decision and does not certify a product.

## 1. Choose the next useful check / 先选检查

Read [use-driven checks](references/use-driven-checks.md) for an open-ended request. Start with the question, relevant load path and observable acceptance. Choose geometry, an applicable calculation, targeted FEM, information collection or a physical test by what can change that decision. An assembly inventory is not a mandatory list of FEM jobs. A beam estimate or motion-only prototype need not start a solver. An explicit existing solver case may use `analyze` directly.

Ask consequential missing facts together, normally the few that change the next step. Reuse prior answers. When the user authorizes a preliminary screen, state its assumptions and proceed within that scope instead of repeatedly asking. A material family alone does not determine strength or manufacturing applicability. Missing S–N data cannot establish fatigue life.

Use existing fields: `request`/scenario `success` are requirements; `acceptance` is the declared criterion; `assumptions` names **用户授权假设 / user-authorized assumption** or **Agent 筛查假设 / Agent screening assumption**, including its source and applicability; `unknowns` and `not_assessed` keep the gaps. Keep unverified `conditions` false. No new provenance schema is required. A user-supplied friction or preload value can be an assumption without becoming a measurement. Check its relevance using actual material, geometry and rating data; bolt diameter alone gives no preload limit.

For missing material, mounting or load locations, use `prepare MODEL --out FRESH` and [model adapters](references/model-adapters.md) to inspect the geometry without granting strength. For unsupported physics, record an `unsupported` planning decision and the needed information/method. Do not relabel hyperelasticity, large deformation or curved contact as supported linear physics.

## 2. Execute and iterate / 执行与迭代

### 与 SimpleCADAPI / text-to-cad 联用

In a joint workflow, SimpleCAE owns strength, stiffness, thermal, modal, buckling and fatigue judgments; route analysis here instead of SimpleCADAPI's standalone gmsh/CalculiX examples. For a request with known operating conditions, write the required `interface.*` regions, partition locations and expected face counts into the CAD requirements before modeling, even if the CAD skill normally loads analysis guidance later. Read only the references needed for that check. Use STEP plus source-bound interfaces for this joint geometry handoff; apply tags after all CAD features. See [native handoff](references/simplecad-handoff.md) and [partition recipes](references/cad-partitioning.md).

Keep `indeterminate`, `needs_information` and `unsupported` as valid conclusions. Structural qualification still needs at least three mesh levels and two successive convergence comparisons; a requested safety factor does not override that evidence. Return geometric changes to the corresponding CAD skill, then regenerate, rebind and recheck the same physical contract.

Prefer [one-file Agent tasks](references/agent-tasks.md) for mixed checks and CAD iteration:

```text
<SIMPLECAE_PY> scripts/simplecae_cli.py task start TASK.json --out out/cae/WORKSPACE --brief
<SIMPLECAE_PY> scripts/simplecae_cli.py task run out/cae/WORKSPACE --check CHECK --budget-seconds 3000 --brief
<SIMPLECAE_PY> scripts/simplecae_cli.py task status out/cae/WORKSPACE --brief
```

`task start` records the plan and creates Viewer without solving. The Agent selects a check explicitly; `task run` uses the bounded `design-check` workflow. Read [bounded design checks](references/design-checks.md) before selecting FEM. Explain loads, materials, support freedoms, task probes and criteria; review the boundary preview before solving. `calculation` remains distinct from FEM, and external formulas are recorded with their derivation and applicability.

Choose a finite budget from the task and observed cost; the default is 3000 seconds, while explicit limits remain binding. `--timeout auto` shares the total budget. Check `doctor.runtime_identity` when multiple Skill copies exist; inspect `mesh-policy` and structured `recovery` fields before retrying. Contact, bolt preload or requested buckling needs an explicit `--depth detailed` choice. Explain this scope, then execute the declared physics; a depth prompt does not authorize replacing contact by a fixed face. See [contact convergence](references/contact-convergence.md) and [execution resources](references/execution-resources.md).

Set decision-appropriate accuracy **before** running. Structural FEM requires three successively refined meshes, each at least 20% smaller; thermal/modal use their own mesh contracts. One coarse run is not a qualified pass. Structural/probe tolerances and [thermal temperature accuracy](references/thermal-solid.md) are explicit inputs. A coarse temperature tolerance widens the undecidable band. Preserve equilibrium, full-field coverage, geometry, raw stress peaks and model-validity gates. A newly authorized criterion is a new contract; keep old evidence and do not rank it as a same-condition CAD improvement.

On timeout or native mesh failure, inspect the diagnostic and completed stages. `advise CASE --evidence DIRECTORY --out FRESH.advice.json` proposes bounded actions without changing inputs. Task attempts share a persisted branch allowance: set `--total-budget-seconds` for multiple checks, and use `task start --continue-from PREVIOUS_WORKSPACE` for later CAD revisions. `--budget-seconds` caps one worker; `--retry-reason` does not reset the branch allowance. A justified allowance change additionally needs `--budget-reason` and must stay within user authorization. Read [Agent tasks](references/agent-tasks.md) for opt-in `--reuse-levels` on qualified linear solids/bonded assemblies. An unchanged completed check needs no rerun; stop when the allowance is exhausted.

CAD handoff uses explicit units, frames, selected occurrences and source hashes. STEP carries units; STL/OBJ needs `model.units`; GLB defaults to metres/Y-up and needs `scene_node` for multiple occurrences. Verify `expected_bbox_mm` and gravity in the analysis frame. A partial load patch must be partitioned upstream. Read [model adapters](references/model-adapters.md) and [local refinement](references/local-mesh-and-reference.md).

After a CAD edit, regenerate and inspect the saved artifact, rebind named regions with `bind-regions`, and start a **fresh revision/workspace** with `--continue-from` for the same task branch. This shares execution accounting, never completion evidence. Keep `task_id`, material, loads, supports, criteria and rule meaning fixed for `compare`/`design-compare`; changed physical assumptions define another contract. Old face IDs never silently migrate. Use one Viewer session for both revisions. Check fit, motion, access and manufacturing effects of the edit.

## 3. Interpret the result / 按状态行动

| Evidence / 状态 | Next action / 下一步 |
|---|---|
| `pass_under_stated_model` 模型内通过 | Keep the scoped design; continue unresolved required checks. No automatic extra solve or product claim. |
| `fail_under_stated_model` 有效模型不满足 | Use the located failed criterion to propose an actual CAD feature, direction, mechanical reason and recheck. Preserve the task. |
| `indeterminate` 证据不足 | Resolve the missing or unconverged evidence; no favorable ranking margin. Preserve any independently confirmed failure. |
| `invalid` 分析无效 | Repair input, meshing or execution; it does not diagnose weak geometry. |
| `choose_analysis_depth` | Choose the declared detailed model explicitly; retain contact/preload/constraints. |
| `review_model_validity` | Address an out-of-range model; more mesh refinement cannot fix it. No thickness multiplier from unqualified displacement. |
| `review_joint_compliance` | Inspect measured/declared joint stiffness and held state before changing links. Effort rating is not stiffness. |

A root hotspot requires mesh sensitivity and physical load/support interpretation. Never drop the peak, clip negative contact pressure, invent supports or soften material to pass. A real fillet is a CAD hypothesis that needs reanalysis, not proof a singularity is harmless. A valid converged failure remains a failure.

Deliver the use conclusion, assumptions, assessed/unassessed scope, `report.html`, `result.json`, `signal.json` and sources. CLI exit 0 means execution completed, not structural acceptance. Read [interpretation](references/interpretation.md) before any capacity statement. A body pass cannot establish wall anchors, grip, actuation, mounting or whole-product capacity.

Use `task record` only for an actually performed external check, with source-bound artifacts and honest observations/limitations. Physical tests that were not performed stay pending or insufficient. External records are assertions, not independent certification. See [product evidence](references/product-evidence.md).

## Read the method needed for this decision

| Question or trigger | Reference |
|---|---|
| Solid loading, supports, material and criteria | [case format](references/case-format.md), [materials](references/materials.md), [support presets](references/support-presets.md) |
| Independent bodies, planar contact, friction or bolt preload | [assemblies](references/assemblies.md), [contact and transfer](references/contact-and-transfer.md), [contained contact](references/contained-planar-contact.md) |
| Heat path, then spatial temperature if needed | [thermal networks](references/thermal-network.md), [solid conduction](references/thermal-solid.md); temperature is not thermal stress |
| Excitation bands versus normal modes | [modal screening](references/modal-analysis.md); mounting/mass are inputs, amplitudes are not computed |
| Acceleration or braking reactions | [motion states](references/motion-loads.md), [rigid calculations](references/rigid-calculation-checks.md); named states are not a trajectory envelope |
| Repeated or sustained load | [fatigue and creep data](references/durability-data.md); missing material curves stay missing |
| Robot task error, link and joint contribution | [robot cases](references/robot-cases.md), [joint compliance](references/joint-compliance.md), [task measurements](references/task-measurements.md) |
| Gripper force range, drive and holding | [gripper tasks](references/gripper-tasks.md), [finite pads](references/finite-pad-grasps.md), [actuation](references/actuation-paths.md) |
| Local peaks, poor mesh or bounded continuation | [stress regions](references/stress-regions.md), [mesh diagnostics](references/mesh-diagnostics.md), [continuation](references/refinement-continuation.md) |
| Many explicitly selected jobs, completion and resume | [campaigns](references/campaigns.md) |
| JSON/API contracts or installation | [Agent API](references/agent-api.md), [installation](references/agent-installation.md), [README](README.md) |
| Viewer, storage, metrology or the full operational reference | [Viewer](references/viewer.md), [storage](references/storage.md), [interface metrology](references/interface-metrology.md), [workflow details](references/workflow-details.md) |

Bootstrap once only when runtime dependencies are missing; use the host-specific Python and an explicitly discovered solver. Ordinary usage does not require full pytest, license audits, `verify_release` or release receipts. Native Windows loader failure is an environment error: retain its log and repair the execution environment before retrying.

Resolve `<SIMPLECAE_PY>` using the [Windows/Linux/macOS table](references/platform-installation.md); keep all three toolchains isolated. For the `sca-simplecae` addon, run `sca addon check simplecae` before first use and resolve a failed runtime probe before analysis. SimpleCADAPI models/captures the package, its native environment exports STEP and final `interface.*` selections, then SimpleCAE reads millimetres in the explicitly declared part-local/world frame. Package identity metadata is retained; no foreign BREP is read and no geometry is modified here. See SimpleCADAPI's `references/scadpkg-format.md` for its package contract.

Default compact storage losslessly retains numerical evidence after readers stop. Retain failed attempts. Clean caches only under the user's retention instructions, after required reviews and retests. User model/data files are not executable solver code. Do not upload or publish unless requested.
