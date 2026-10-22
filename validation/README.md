# Verification scope

This directory keeps the uploadable verification summary only. Detailed local
logs, test outputs, source snapshots, historical receipts and audit reports are
retained outside this repository. They are not dependencies of ordinary skill
installation or analysis.

Recorded verification on 2026-10-22:

- Full regression before the subsequent installation recovery change: Windows
  1010 passed / 4 platform skips; Linux 1007 passed / 7 platform skips. Skipped
  checks passed on the applicable other platform.
- Two independent Agents exercised five scoped scenarios. A valid thermal
  failure and missing material/compliance evidence remained failures or gaps;
  no whole-product acceptance was claimed.
- Subsequent installation recovery change: Windows 61 passed / 4 skips; Linux
  58 passed / 7 skips, plus actual native probes and update/reuse of previously
  clean isolated Windows/Linux environments. This was not another full physics
  regression or a fresh dependency download.
- macOS, physical-product validation and hosted CI were not tested in this round.

These are historical, scoped results, not a current source-bound release receipt
or a guarantee of defect-free software. Upload-directory cleanup and documentation
changes do not constitute numerical retesting.

Ordinary `scripts/install_local.py` installation does not require validation
receipts, full pytest, license audits or `--verify-release`. Download integrity,
runtime readiness and analysis evidence checks remain in place. Maintainer-only
qualified packaging / `--verify-release` still requires fresh, source-bound
release evidence; this summary does not substitute for it.
