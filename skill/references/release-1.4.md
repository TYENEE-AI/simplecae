# 1.4 scoped qualification

Historical 1.4 scope below. The current 1.5 preview runs ten suites and adds explicitly declared equivalent axial preload locking and planar Coulomb contact; see [current conditions](contact-and-transfer.md). Detailed continuum bolt-section/thread and whole-robot joint coupling remain outside that scope.

This release extends existing assembly and component workflows, with no additional dependency, solver backend, orchestration framework or automatic CAD optimizer. Reproduce the nine numerical suites with `python scripts/verify_release.py --out FRESH_DIRECTORY`; guard tests use `python -m pytest tests`. Ordinary design candidates need their own numerical checks, not all release suites.

| ID | Required observable behavior |
|---|---|
| M01 | Native planar frictionless contact reproduces compression, opening, nonuniform pressure, declared-gap closure and penalty-stiffness sensitivity. Reversed normals reject. No coordinate adjustment or geometry fusion. |
| M02 | Fixed-force preload precedes service loads; every step reaches the full load. Preload is assessed separately and can fail while service strength passes. Closed-to-open unloading remains stable only with declared real supports. |
| M03 | First-order URDF section translation AND rotation propagate through explicit FEM/rigid paths. Straight and bent two-link references, fixed gravity, transformed frames, cumulative task failure and rotation-screen rejection retain meaningful verdicts. |
| M04 | New modes withhold automatic capacity scaling. Incomplete contact histories, missing task probes, wrong displacement scope or absent frame/warping/rotation evidence cannot get a favorable public signal. Mathematical materials remain numerical references. |
| M05 | Campaign CLI exposes worst status, status counts and validity; invalid/unresolved campaigns return nonzero. Legacy source/contract/criterion guards and native suites remain active. |

`validation/release-audit.json` binds these requirements and the original scoped requirements to current delivered file hashes. `validation/release-verification.json` binds native results to the non-validation source snapshot; `validation/numerical/mechanics.json` records independent references and adverse controls. Development trials retain their original failures and are not substituted for frozen-source release verification.

The retained20-case1.3.1 native results are replayed through the current signal/contract logic with source hashes checked. That is **historical result revalidation**, not new native20-case reruns or physical testing. Original changes of task scope (P02, P08, P16), unresolved historical DG250 mounting stress and broader product evidence remain explicit. A primary-body pass still cannot grant product acceptance.

## Remaining priorities

| Priority | Boundary / next useful work |
|---|---|
| P1 capability | True bolt-section pretension and locked-length tightening, frictional stick/slip, nonplanar/partial-overlap contact and stable general contact initiation need separate models and numerical references. Applied clamping force covers a narrower case. |
| P1 capability | A coupled whole-robot continuum/joint model, flexible transmission/actuator/bearing mounts and section warping compatibility are not implemented. First-order tree transfer is a useful reduced model with explicit limits. |
| P2 | Local pressure singularities, moving peaks and penalty sensitivity still need engineering review. No automatic clipping, threshold relaxation or mesh-independent physical guarantee. |
| P2 | New history-dependent modes deliberately reject cache reuse and automatic capacity search. Qualify those only if repeated real tasks justify the complexity. |
| P2 | General manufacturing/assembly acceptance remains caller supplied. Keep purchased-part, source, CAD, mechanical and physical test evidence distinct; no universal DFM certification. |
| P3 | Very large robot visualization/JSON still duplicates some geometry and is not streaming; numerical reports already load viewers separately. |
| P3 | Cross-platform native execution, independent novice usability and public license/adoption remain outside this Windows numerical release qualification. |

No hardware was manufactured or tested. No original task's allowable stress, displacement, load, material or quality gate was relaxed to improve pass counts. Mathematical solver-reference tolerances are documented separately from design acceptance criteria.
