# Release channels and verification scope

This page retains its filename for existing links. Current release scope is in
[platform evidence](platform-evidence.md). A final source archive carries
`validation/public-release.json`; a development preview instead carries
`validation/public-preview.json`. Both bind the delivered sources to their own
verification. A changed checkout cannot inherit an older archive's qualification.

SimpleCAE is a local engineering design-check and CAD iteration skill for agents. Select the relevant structural, thermal, modal, motion-load or data-backed durability question first. Contact/preload, buckling and first-order robot/link/joint transfer are explicitly scoped modes. A model result never establishes a physical product rating.

Qualification includes 14 native numerical suite categories, the full current
physics/workflow regression with required-module coverage, guard tests,
pass/fail/insufficient examples, iteration, notices, privacy and actual isolated
runtime/Agent/Viewer exercises. Final releases additionally require current audit,
platform, host-integration and substantive-example evidence. Local development
checkpoints have a separate scoped record. None is physical certification or an
independent novice study.

Current evidence covers Windows and WSL Ubuntu workflows and a measured
multithreaded static/contact family. Exact environments and limitations are in
[platform evidence](platform-evidence.md), not inferred from this older filename.
Historical workpiece and hook experiments do not grant new product acceptances.

The public package excludes environments, native binaries, results, upstream snapshots and historical validation folders. Only the current portable public receipt is included. Changing delivered sources invalidates it. Follow [README](../README.md) for bootstrap and two-revision Viewer use. Daily runs losslessly compact native text and retain every mesh level, complete fields, logs and decisions. Use --storage full for native-file inspection. No background purge, telemetry or upload.

Maintainers can reproduce numerical/software checks from frozen sources:

```powershell
.\.venv\Scripts\python.exe -m pytest --junitxml=outputs/guard-tests.xml
.\.venv\Scripts\python.exe scripts/verify_release.py --out outputs/verification-001 --timeout 3000
.\.venv\Scripts\python.exe scripts/verify_preview.py --out outputs/preview-001
.\.venv\Scripts\python.exe scripts/audit_dependencies.py
```

These mathematical/software references require expected failures and rejections. They do not measure materials, anchors or product performance. Fresh dependency installation and interactive Viewer checks are recorded separately. Use [the feedback template](../assets/feedback-template.md), reviewing private content before sharing.

SimpleCAE-authored code/examples use GPL-3.0-or-later; [NOTICE](../NOTICE.md) defines third-party terms and the source-only boundary. Bootstrap separately downloads pinned dependencies and the checksum-verified solver. Notice checks are not a legal opinion for other redistribution arrangements. Making a ZIP does not publish it.
