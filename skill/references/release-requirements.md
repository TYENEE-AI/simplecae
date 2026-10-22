# SimpleCAE release requirements and completion audit

## Current source-only release (1.6)

The public path is `python scripts/package_skill.py --public-release --out NEW.zip`.
It reuses the numerical/guard/example/license/privacy checks of the source-only
preview and additionally requires a final version plus source-bound
`validation/release-readiness.json`: current workflow/calculation/resource/
exception/product/documentation audit areas, no open release blockers, actual
Windows and Ubuntu install/CLI/worker/Viewer/compact/regression evidence, and
five-host discovery/CLI checks with live-Agent scope stated separately.
The three substantive showcase workflows must retain their true outcomes.

`verify_release.py` runs 14 native suite families plus the full current regression,
including required thermal, modal, motion, durability, local-region and task
modules. Missing/skipped critical modules reject qualification. No solver or
engineering acceptance threshold is relaxed for packaging.

The public archive contains only `validation/public-release.json`, an exact
source-bound scoped summary; private historical records remain local. Installers
verify that receipt against the delivered files. The historical R/F/A/M/J audit
rows below remain context for legacy packages, not a requirement to distribute
private history or rerun old user projects. Current code behavior is covered by
the actual native suites/regressions and current audit.

Ordinary users run quickstart and selected task checks, not the whole maintainer
qualification suite for every CAD change. Local packaging never uploads a release.

## Historical release contracts

Developer Preview 1 (1.5.0) additionally requires complete project/dependency notices, three real first-use outcomes and an unchanged-criteria geometry iteration, and a private-history-free source profile. The maintainer runs all ten numerical suites and guard tests against final sources. The public archive replaces local historical validation folders with `validation/public-preview.json`, containing exact source hashes and scoped verification summaries. See [preview scope](developer-preview.md). Earlier requirement rows/history below do not claim new physical or independent novice validation.

1.5 requires J01: axial preload/lock/service and independent load sharing; J02: planar friction with independent stick/sliding references and adverse task motion; J03: scope/completeness guards, no contact capacity promotion, and explicit omitted mechanics. Each is scoped to numerical/software evidence in `validation/numerical/bolt-friction.json`, guard tests and the mode documentation.

This is the scoped acceptance contract for the structural/robot design-screening release. The1.0 and1.1 archives remain separate baselines. Version1.2 adds task/relative measurements, finite-pad wrench closure, force-uncertainty endpoint orchestration, explicit actuator reactions and robot load preview, solved-level continuation, vendor interface metrology, guided support recipes, product evidence version binding and criterion-specific confidence. Qualification is numerical/software within this matrix, not robot/product certification or promised public adoption. Current evidence belongs in `validation/release-audit.json`, `validation/release-verification.json` and `validation/usability-verification.json`. Ordinary design work skips health/import/package smoke and does not rerun release suites for every candidate.

## Product users and decisions

- Makers: evaluate a robot arm, printed linkage, housing, mount or frame; identify material/dimension/fixture gaps; see where it bends, overloads or becomes unstable; compare a proposed revision.
- Engineers: initial sizing of solid parts and idealized assemblies, load-case envelopes, gravity, force/moment transfer and elastic buckling screening; retain input provenance and numerical checks for later detailed review.
- Generation agents: consume stable JSON signals, distinguish invalid analysis from an infeasible design, preserve the task's load/material/fixture contract between candidates, and send located, evidence-linked feedback to SimpleCADAPI or text-to-cad.

## Required acceptance items

| ID | Required final behavior | Evidence required | Current state |
|---|---|---|---|
| R0 | Critically use the supplied Sohu survey; verify selected upstream claims against source | Source URL/date, inspected pinned upstream files, implementation decisions and licenses | Verified: supplied survey critically reviewed; pinned sources, licenses and adoption decisions recorded. |
| R1 | General solid-part input, not hard-coded bracket geometry | Different classes of geometry and load/support patterns solved | Verified: CAD/mesh bars, rounded bracket, column, curved hollow tube, nonconvex angle and enclosed-cavity STEP; general validation 43 checks. |
| R2 | Elastic buckling analysis with modes, load factors, convergence and limits | Actual CalculiX eigen solves against Euler reference and nonlinear/imperfection limits disclosed | Verified: Euler/preloaded single-column and bonded assembly eigen solves, retained modes and mesh convergence; nonlinear limits disclosed. |
| R3 | GLB/STL mesh input with units, scene transforms, closedness and meshing checks | Real transformed mesh exports converted and solved; malformed input rejected | Verified: actual SDK GLB/STL/posed scene and curved/nonconvex meshes; units/occurrences/source checks and malformed/two-shell rejection. |
| R4 | Multi-body assembly/connection modeling with explicit assumptions | Bonded/compliant connection tests and load-path/equilibrium checks; no implicit fusion | Verified: independent bonded/compliant planar interfaces, positive energy/rigid/traction patch, bending, heterogeneous bodies, rotations, penetration and actual compound selection; 79 checks. |
| R5 | URDF robot input, pose/units/reference validation, gravity/payload loads, effort and component analysis | Independent kinematics/statics references; generated URDF assets; link FEM; invalid topology/poses rejected | Verified: real CAD component FEM, three poses, independent 2R equations, mimic/prismatic/frame guards, actuator/ground failure, mass/COM and missing-input rejection; robot suite 18 checks plus integration. |
| R6 | Manufacturing/material support including calibrated directional properties | Orthotropic material/orientation tests; no blanket printed-material certification | Verified: calibrated orthotropic elasticity/axes, positive energy, signed criteria and rotated isotropic equivalence; 47 mathematical checks, no manufactured material certification. |
| R7 | Fixed loads such as self-weight distinguished from scalable payload; multiple load cases | Analytical self-weight/superposition/limit tests and load-case envelope | Verified: fixed gravity/preloads, superposition and three-mesh limits; actual alternative load envelope and load doubling; omissions propagated. |
| R8 | SimpleCADAPI interoperability | Actual current SDK-generated exports/packages, semantic interfaces and regeneration tested | Verified: actual SimpleCADAPI 2.2.1 native tagged/scadpkg/AP242 part, QL port transfer to robot FEM, and placed multi-occurrence compound. |
| R9 | text-to-cad interoperability | Actual pinned cadgen-generated STEP/GLB/robot descriptions, scene references and regeneration tested | Verified: actual cadgen 0.7.21 STEP/GLB/STL, scene transform, regenerated thickness candidate and native URDF/assets validation/snapshots. |
| R10 | Nonexpert task guidance and plain-language visualization | Scenario-driven guided inputs, actionable missing-information messages, interactive result/mode viewing, rendered UI QA | Guided directional multi-region support, missing common rigid modes, named/relative measurements, per-criterion confidence and all-pose robot force/couple/drive-path preview; real browser input/export validation. Advanced connections/materials still require explicit templates. |
| R11 | Agent integration and self-evolution feedback | Versioned case/result/signal contracts, Python/CLI interfaces, comparable candidate runs and invalid-signal tests | Saved task snapshots and actual SDK candidate trends; 1.0.1 also requires buckling-envelope aggregation, effective URDF ratings, actuator-only metrics and associated rejection paths. |
| R12 | Testing grounded in primary examples | Analytic verification, diverse end-to-end geometries/formats/materials/connections/robot poses, failure paths, report/export/installation tests; reproducible release record | All seven numerical suites and public output contracts must rerun against unchanged final sources, including examples/documentation; audit-specific regression and installation checks supplement them. This is numerical/software evidence, not exhaustive physical validation. |
| R13 | Portable final skill/toolkit and verified release audit | Current SKILL, references, dependency lock, sources/licenses, runnable examples, intact source package, requirement-by-requirement completion record | Verified: independent current-source installation, native reference solves, intact source archive and local links; release-audit.json qualifies the supported scope. Final deliverable integrity is recorded in package-audit.json. |

No row becomes complete based on an import, mock, smoke test, screenshot alone or an upstream project's claim. Numerical verification is separate from physical validation. The final release is a structural design-screening product with an explicit capability matrix; arbitrary physical phenomena cannot be inferred from geometry or certified by this toolkit.

Final packaging checks the project version, complete scoped qualification, the exact set/hashes of delivered sources, examples, references and validation evidence, and the final source snapshot in the full numerical verification. Version1.2 additionally requires all12 DG250-feedback iteration items verified in a separate `iteration_requirements` map; its IDs do not replace the original R0..R13 scope. `verify_usability.py --out FRESH_DIRECTORY [--project DG250_ROOT]` reproduces native task/workflow cases, and final audit includes the actual project plus bounded rendered-UI checks. A stale flag or changed file cannot inherit prior qualification. The audit record excludes itself from its manifest to avoid a circular hash. ZIP and post-installation manifests stay outside the qualified source tree to avoid circular archive hashes. This is consistency checking of trusted local records, not a digital signature or independent certification.

`package_skill.py --development` produces only a local development checkpoint. Its `validation/development-validation.json` must record `passed: true`, the current `toolkit_version`, and an exact `source_files_sha256` matching `delivery_hashes(root, include_validation=False)`. A stale or incomplete snapshot is rejected before an archive is created. Keep the tested scope and unfinished application checks explicit in that record; this smaller consistency check does not grant release qualification.

## Architecture direction

Separate input adapters (STEP/mesh/URDF/generator metadata), the numerical backend (Gmsh/CalculiX), scenario/load preparation, validity checks, design signals and presentation. Preserve geometry/material/support/load provenance across the complete chain. Retain source models and never repair connectivity or substitute collision/visual geometry silently. Use typed data interfaces rather than executing user-supplied solver Python through an unrestricted tool endpoint.

## Survey use

The supplied article is a tool-directory survey, not a solver-verification source: https://www.sohu.com/a/1084649320_121124362 (published 2026-10-07, fetched 2026-10-13). Its useful directions are separating skill instructions from execution, explicit stage gates, finite repair attempts, unit/frame discipline, preserving raw numerical evidence and candid unsupported items. Evaluate HPC-Skills, femis-skill, CAE-Agent-Hub and pygccx for these concrete needs. Do not inherit article rankings or test counts as evidence for SimpleCAE.
