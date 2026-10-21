# Validation scope for this checkout

This checkout includes installation, budget/continuation, CAD region diagnostics,
resource advice and Viewer maintenance on top of 1.6.0.
`workflow-maintenance-20261021.json` records the latest scoped verification:
898 Windows regressions passed, 2 platform-specific symlink checks skipped;
real Linux symlink/cache checks, five native historical scenarios, three native
recovery scenarios, Viewer parity/browser checks and isolated installation passed.
The robot negative case remains a model failure; expected behavior passed.
This does not establish fresh Linux native FEM or independent external review.

`onboarding-fix.json` records the scoped regression and smoke checks performed.
It does not claim a fresh full numerical release qualification.

The previous source-bound receipt is retained in `history/` for traceability.
It belongs to the earlier source snapshot, not this edited checkout. Ordinary
installation does not require a receipt. Do not regenerate a passing receipt
merely to make hashes match. `--verify-release` is an optional maintainer audit
and will require new release evidence before this checkout can claim qualification.

Missing/deprecated release receipts are separate from case validity: material,
load, support, mesh, convergence, result-binding and product-scope checks remain.
