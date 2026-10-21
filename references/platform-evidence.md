# Platform and release evidence

This page distinguishes tested behavior from intended compatibility. Exact
source hashes, final test counts, environments and audit evidence are in a public
release archive's `validation/public-release.json`. A source checkout without
that receipt must not claim the archive's qualification. Historical intermediate
test counts are deliberately not used as the final package's count.

| Environment | Verification scope | Limit |
|---|---|---|
| Windows x64, Python3.11, CalculiX2.23 | Full regressions, source/isolated wheel quickstart, worker subprocesses and Viewer iteration | Other hardware/solver builds need their own evidence |
| WSL2 Ubuntu26.04, Python3.14, CalculiX2.21 | Full regressions, isolated wheel CLI, native examples and workers | WSL is not independent bare-metal/device coverage |
| Fresh Ubuntu Python3.11.17 environment | Bootstrap, all four quickstart outcomes, iteration, compact retention; existing Windows solver/user marker preservation | Dependency versions differ from the Windows lock |
| Windows multithreaded CalculiX2.23 | Same contact deck at1/2/4 threads; all printed fields/times/contact/bolt rows compared; automatic selection replay | One measured static/contact family, not universal speedup |
| Local Codex Agent | Actual task authoring, CLI, CAD/CAE iteration, failures and browser Viewer review | Not every host/model combination |
| Claude Code, DeepSeek Harness, OMP, Pi | Official discovery conventions; installer targets/preservation and CLI contract checks | No claim of live model-driven sessions in these hosts |

The measured contact run took27.39/20.89/16.14 s for1/2/4 threads; auto replay
selected four and took16.19 s. This is one machine/input observation. Runtime
selection falls back to serial when identity, coverage or applicability differs.

## Accuracy boundaries

- Temperature convergence and energy balance do not certify pointwise heat flux.
  A curved-cylinder reference retained a coarse temperature error above the
  original0.0001°C target; finer unchanged natural-boundary meshes met that
  temperature target. The stricter0.001 W/m² local-flux target remained unmet.
- Unresolved preload/root convergence and robot transfer applicability remain
  incomplete example outcomes, not waived numerical gates or product passes.
- Numerical references, regressions, onboarding and rendering are different
  evidence. Green tests do not substitute for material, mounting or real-use data.

## Reproduce

Run the source environment's `python -m pytest -q` for regressions and
`python scripts/verify_release.py --out FRESH_DIRECTORY` for native qualification.
The latter also checks execution of current physics/task modules; absent or
skipped required modules cannot silently satisfy release coverage.

Normal users need not run maintainer suites for every CAD revision. Start with
`quickstart --example all`, then a selected task. Final source archives exclude
local environments, solver binaries, private results and machine-specific profiles.
