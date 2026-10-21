# SimpleCAE

**Engineering checks that help CAD and robotics Agents make the next design decision.**

[中文说明](README.zh-CN.md) · [Skill entrypoint](SKILL.md) ·
[Examples](examples/showcase/README.md) · [Agent installation](references/agent-installation.md)

Describe what you want to build, how it will be used, and what would make it
uncomfortable, inaccurate or unreliable. SimpleCAE helps an Agent choose relevant
checks, organize local calculations, locate the controlling problem and return
an actionable change to a CAD or robotics tool.

It runs with Python, Gmsh and the open-source CalculiX command-line solver.
No commercial CAE application, cloud solver account or API key is required.
The calling Agent still needs its own host/model and terminal access.

> “My robot controller has a 5 W heat source. Keep its heat bridge below 40°C
> under the stated cooling condition. Use SimpleCADAPI to change the geometry,
> check the heat path with SimpleCAE, and show why the revision helps.”

![Controller mount with revised heat bridge](examples/showcase/thermal-bridge/r2/product.png)

In this four-part example, the Agent selects the **heat bridge**, not every part.
The original 2 mm bridge reaches **49.94°C**. Increasing only its thickness to
4 mm gives **34.97°C**, with the same 5 W input, ideal 20°C cold end and 40°C
limit. Real interface resistance and cooling remain explicit unknowns.
[Reproduce both revisions](examples/showcase/thermal-bridge/README.md).

`simplecae --version` identifies the actual code. Public release archives carry
a source-bound verification receipt; editing the source invalidates that snapshot.
See [test scope](references/platform-evidence.md) before extending its claims.

## What makes it useful

- **Start with use, not a mesh.** A hand-driven mechanism may first need clearance
  checks; a precision robot may be limited by joints. Record why a check matters
  and which parts/interfaces it covers.
- **Return a next action.** Keep the affected component, located peak, governing
  criterion and reanalysis trigger. A valid failure can motivate CAD changes;
  numerical failure first needs analysis repair.
- **Keep one iteration record.** Task files, CLI/JSON and the local Viewer connect
  requirements, computed results, external checks and CAD revisions. SimpleCAE
  does not silently edit CAD or execute Viewer annotations.
- **Keep inconvenient evidence.** Failed preload stages, hotspots and unfinished
  checks remain visible. A body pass cannot become a robot or product pass.
- **Use resources deliberately.** Select checks and finite budgets; use measured
  parallelism where useful. Lossless compression retains complete result fields.

## What it can check

| Question | Supported calculation | Boundary |
|---|---|---|
| Too much bending or stress? | STEP or suitable mesh solid linear elasticity, located strength/stiffness, task probes and convergence | Material, manufacturing and mounting must be supplied |
| Does the modeled mounting hold? | Independent bodies, planar opening/friction, equivalent axial bolt tightening → locking → service | No arbitrary contact, large sliding, real threads, bolt bending/shear or anchor pullout |
| Elastic instability? | Supported linear eigenvalue buckling screen | Not nonlinear collapse, imperfections or contact buckling |
| Why does a robot tip move? | URDF statics, selected link FEM, first-order section transfer and explicit joint compliance | Supported fixed-base tree/held states; no general flexible multibody coupling |
| High acceleration/braking demand? | Named rigid-tree states, effort and installation loads | Not controller or full-trajectory dynamics simulation |
| Too hot? | Steady/transient thermal networks and targeted solid heat transfer | No CFD/automatic thermal-stress coupling; local heat-flux accuracy needs separate evidence |
| Near an excitation frequency? | Modal frequency and mode-shape screening | Arbitrary mode amplitude; no forced-response prediction |
| Repeated or sustained loading? | Fatigue/creep from applicable material curves and located stress/temperature evidence | No invented FDM endurance limit or material-life extrapolation |
| Fit, assembly, motion or real use? | Revision-bound records from CAD tools, measurements and tests | Records are assertions, not independent certification |

[Method selection](references/use-driven-checks.md) · [Detailed contracts](SKILL.md)

## Three decisions, not three green demos

| Case | Problem | What the Agent learns |
|---|---|---|
| [Controller heat bridge](examples/showcase/thermal-bridge/README.md) | Four-part mount, 5 W, 40°C limit | Resistance and solid temperature support a section change; two CAD revisions included |
| [Two-joint inspection arm](examples/showcase/inspection-arm/README.md) | 0.2 kg payload, 0.5 mm tip target, three motion states | Separate joint/link contributions; unresolved transfer applicability blocks a misleading thickness recommendation |
| [Bolted sensor mast](examples/showcase/sensor-mast/README.md) | Full preload/lock/contact path and revised root | Service can pass while preload/root convergence remains unresolved; locate rather than discard the hotspot |

All include authored editable SimpleCADAPI sources and portable geometry/inputs.
The CAD environment is optional for running these CAE inputs. Smaller
`quickstart` references check pass, fail, insufficient evidence and iteration;
they are installation checks, not the main product examples.

## Install the runtime

This checkout includes first-use maintenance fixes on top of 1.6.0. See
[validation scope](validation/README.md); the archived release receipt belongs
to the earlier snapshot and is not an installation prerequisite.

For host skill discovery, first follow “Connect your Agent” below, then run setup
inside the installed folder. Create the runtime once. Agents using this source
folder directly do not need an additional installed copy.

Use a writable source folder and **64-bit Python 3.11+**; Python 3.11 is the
recommended common baseline. Initial dependency downloads need network access.
Run commands from this folder.

**Windows PowerShell**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
.\.venv\Scripts\python.exe scripts/simplecae_cli.py --version
# Optional: one real solver example
.\.venv\Scripts\python.exe scripts/simplecae_cli.py quickstart --out outputs/first-001
```

No shell activation is required. Bootstrap reuses a compatible local runtime and
configured solver; otherwise it installs runtime dependencies within the declared
version bounds. Tests are not an installation prerequisite. `-Locked` is an optional
Windows maintainer setup for the full test dependency lock. A newly downloaded
CalculiX archive is checked before extraction. Supply `-Python PATH` or `-Ccx PATH`
to select a full Python (including venv/ensurepip) or solver; stripped Agent Python
runtimes may not support environment creation.

**Ubuntu / bash**

Install prerequisites with your normal package-management permissions:

```bash
sudo apt-get update
sudo apt-get install python3-venv calculix-ccx libglu1-mesa libxft2 libxcursor1 libxinerama1 libgomp1
bash scripts/bootstrap.sh
.venv-linux/bin/python scripts/simplecae_cli.py --version
# Optional: one real solver example
.venv-linux/bin/python scripts/simplecae_cli.py quickstart --out outputs/first-001
```

The selected Python must be >=3.11; use `--python /path/to/python3.11` if needed.
Use `--ccx /path/to/ccx` for an existing solver. Bootstrap does not run `sudo`
or modify system packages. Linux uses separate `.venv-linux` and preserves
Windows solver settings in shared folders. Ubuntu dependencies resolve within
declared version bounds; record `doctor` output for reproduction.

An existing healthy environment can go straight to the user task. `quickstart
--example all`, pytest, dependency audits and release verification are optional
learning/maintainer workflows, not mandatory first-use steps. Reuse an existing
quickstart result rather than rerunning it; use a fresh output directory when a
new solve is actually needed. Opening Viewer alone starts no solve.

Installed environments can also call `python -m simplecae`. A wheel contains
runtime assets/examples; the **source folder** is the installable Agent skill.
[Dependency details](references/dependencies.md).

## Connect your Agent

Start with **“Read this folder's SKILL.md and use SimpleCAE.”** For discovery,
install the source folder (destination preview is optional):

```text
python scripts/install_local.py --agent codex --show-target
python scripts/install_local.py --agent codex
```

Ordinary installation needs no release receipt or source SHA-256 comparison.
Missing/stale receipts do not block it. `--verify-release` is an optional maintainer
audit, not a first-use step. `--development` also works without a receipt.
Solver download integrity and analysis validity checks remain enabled.

| Host | Flag | Default discovery root |
|---|---|---|
| Codex | `codex` | `$CODEX_HOME/skills` or `~/.codex/skills` |
| Claude Code | `claude` | `$CLAUDE_CONFIG_DIR/skills` or `~/.claude/skills` |
| DeepSeek Harness | `deepseek` | `~/.agents/skills` |
| OMP / oh-my-pi | `omp` | `~/.omp/agent/skills` |
| Pi | `pi` | `~/.agents/skills` |

Use `--skills-root PATH` for project roots/custom profiles. Managed sources receive
a backup; environments, tools, outputs and unrelated root files are preserved.
Run bootstrap in a new installation folder, then reload host discovery.
Source copying alone does not install the Python runtime.
[Official host references and details](references/agent-installation.md).
Discovery compatibility is distinct from live testing of every host/model.

## A short Agent loop

1. State use, success criteria, unknowns and allowed changes.
2. Choose checks and the complete load/heat path. Write one task file.
3. Run the selected check; interpret validity, scope, location and criterion.
4. Change CAD when evidence supports it. Rebind geometry/interfaces, preserve
   physics/thresholds and start a fresh revision.

```text
simplecae task start examples/showcase/thermal-bridge/r1/task.json --out outputs/bridge-r1 --run temperature --brief
simplecae task start examples/showcase/thermal-bridge/r2/task.json --out outputs/bridge-r2 --viewer-session outputs/bridge-r1/viewer --run temperature --brief
simplecae task status outputs/bridge-r2 --brief
simplecae view --session outputs/bridge-r1/viewer --serve --open
```

Without `--run`, start only prepares. Use `task run --check NAME` for another
computation and `task record` for external evidence. An unchanged retry needs a
concrete `--retry-reason`; a passed check does not need another solve.
[Task API](references/agent-tasks.md) · [Python/JSON API](references/agent-api.md).

With [text-to-cad](https://github.com/earthtojake/text-to-cad), let `cadgen` own
parametric geometry/export and appropriate DfAM inspection. With
[SimpleCADAPI](https://github.com/PhySpace/SimpleCADAPI), let notebooks own
features, assembly constraints and STEP export. SimpleCAE consumes exports plus
explicit physical inputs and returns feedback to the calling Agent.
Neither CAD tool is an obligatory backend or automatically invoked dependency.

## Results, Viewer and disk use

| Result | Meaning / next action |
|---|---|
| `pass_under_stated_model` | Assessed criteria pass within scope; continue other required checks |
| `fail_under_stated_model` | Valid evidence establishes failure; propose a targeted permitted change |
| `indeterminate` | Evidence/coverage/convergence insufficient; resolve before favorable ranking or capacity |
| `invalid` | Input/environment/mesh/solver checks failed; repair analysis first |

`result.json`, `signal.json`, `report.html` and task/design summaries retain the
evidence. Independent confirmed failures remain actionable when another criterion
is unresolved. No numerical state automatically grants whole-product acceptance.

The Viewer shows real fields, iterations, stage records and annotations on
`127.0.0.1`, without automatic upload or external web assets. Annotations are
review input, not executable CAD commands. [Display scope](references/viewer.md).

Default `compact` storage losslessly compresses native DAT/FRD/MSH after readers
finish. It keeps all mesh levels, full fields, decks, logs and failures. It does
not silently delete old projects or create a second cache.
[Retention](references/storage.md).

For expensive work, inspect `doctor` and execution records, select a justified
budget and calibrate a representative static/contact deck once. Auto mode uses
an applicable measured CPU profile or serial fallback; it does not predict
sparse-matrix memory fit or weaken accuracy to meet a deadline.
[Parallel execution](references/execution-resources.md).

## Feedback, verification and license

Use the [feedback template](assets/feedback-template.md) with a minimal shareable
case, version/platform, expected decision and logs. Check private geometry/paths
before sharing. No feedback is uploaded automatically.

[Contributing](CONTRIBUTING.md) · [Verification](references/release-requirements.md) ·
[Current evidence scope](references/platform-evidence.md)

Source, documentation and authored examples are **GPL-3.0-or-later**.
See [LICENSE](LICENSE), [NOTICE](NOTICE.md) and the
[dependency inventory](licenses/dependency-inventory.json). Source archives exclude
environments, solver binaries, user results and private audit history.
Redistributing dependencies separately carries their own license obligations.
