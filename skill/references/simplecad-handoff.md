# Native SimpleCADAPI handoff

Validated versions: SimpleCADAPI 2.2.6.post2 and cadgen 0.7.26. Exporters read the
actual installed version with `importlib.metadata.version`; older saved audit
records retain the versions they really used. Each CAD tool and SimpleCAE uses
its own Python environment. Add this repository's `scripts/` to `PYTHONPATH` in
the **SimpleCADAPI** environment, or copy the independent `simplecae_scad/` package
there. It needs no SimpleCAE solver dependencies.

Finish all bores, blends and partitions, then tag whole faces as
`interface.mount`, `interface.payload`, etc. The region name is the suffix after
`interface.`. `cae.*` is not a persistent interface namespace. A later feature can
clear tags: rerun the native query on the final body and retag at the end.

After native notebook projection:

```python
from simplecadapi.runtime import run_notebook
from simplecae_scad import export_for_cae
run = run_notebook('hook.py', timeout=3000)
export_for_cae(run, 'out/cae/r1', required={
    'interface.mount': {'face_count': 1, 'surface_types': ['Plane']},
    'interface.payload': {'face_count': 1, 'surface_types': ['Plane']},
}, frame='part_local')
```

A final export cell in a separate handoff notebook may pass a completed native
product returned by `scad.use('hook.py')`. An unfinished raw Part in its own
modeling notebook has no durable definition yet; export its `NotebookRun` after
projection. This keeps IDs, revisions and native tag lineage authoritative.

The equivalent CLI (using the CAD environment's Python):

```text
<SCAD_PY> -m simplecae_scad hook.py --required interfaces.required.json --out out/cae/r1
<SIMPLECAE_PY> scripts/simplecae_cli.py bind-regions out/cae/r1/part.step --native-manifest out/cae/r1/interface_manifold.json --out out/cae/r1/bound.json
```

Exports: `part.step`, `interface_manifold.json` v2, `source.scadpkg` and
`handoff_report.json`. Missing tags/count/type mismatches produce a nonzero exit,
failed tag list, candidate signatures and a retagging action. Failed exports
never leave a successful manifest. Use a fresh directory for each attempt.
The report's `engineering_acceptance` is always false: export is not analysis.

For an assembly add `--occurrence component/subcomponent` to select one exact
leaf part. The STEP contains the assembly; the manifest carries its exact native
STEP label, part-local or world signatures, and composed placement. The importer
verifies source hash, occurrence, face counts, types, areas and centroids. Native
`face_N` appears only as cross-check evidence, never as a Gmsh face ID.

If only `.scadpkg` is supplied, locate its source `.py` notebook and rerun it in
its original CAD environment. Do not read its BREP with SimpleCAE's different
OCC build, guess `face_N`, or reconstruct missing interface semantics from a mesh.
If the source is unavailable, request it; that missing evidence cannot be repaired
by accepting a nearest face.

## Parameter iterations and comparisons

```text
<SCA> run hook.py --set root_fillet_r=4 --id rev2 --out out/cae/rev2.scadpkg
<SCAD_PY> -m simplecae_scad hook.py --set root_fillet_r=4 --id rev2 --required interfaces.required.json --out out/cae/rev2
<SIMPLECAE_PY> scripts/simplecae_cli.py task start rev2.task.json --out out/cae/work-rev2 --continue-from out/cae/work-rev1
<SIMPLECAE_PY> scripts/simplecae_cli.py task run out/cae/work-rev2 --check body-static --brief
<SIMPLECAE_PY> scripts/simplecae_cli.py design-compare REV1.design-review.json REV2.design-review.json --out out/cae/comparison.json
```

Use the regenerated STEP/manifest in `rev2.task.json`; keep the same task ID and physical inputs. The handoff automatically records source files/hashes, package identity/version/hash, installed SDK version and declared `var()` values. A located singularity action can expose the actual radius parameter as `param_hint`; no unrelated parameter is invented. The two native exports above rerun the notebook; the second step alone is sufficient when no standalone `sca run` package is needed.

Unchanged notebook source hashes plus identical native selectors/count/type requirements establish conservative semantic continuity for parameter-only edits. Each revised STEP still needs exact source-hash binding and boundary review. Editing selector source or physical requirements changes the contract. `--continue-from` shares the branch allowance, never prior completion evidence. A stale manifest or direct face-ID selector cannot bypass rebinding.

For robot MJCF/URDF and per-link 3MF/STEP handling, read [robot format handoff](robot-format-handoff.md).
