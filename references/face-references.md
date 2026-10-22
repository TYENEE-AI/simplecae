# CAD Viewer face references

Run `refs resolve` in the CAE environment. It starts the separately configured
cadgen Python, asks `read_scene(...).resolve(...)` for the Viewer's canonical face,
then verifies volume/centroid/bounds of the selected solid and the whole face's
centroid/area/type against the CAE import. It does not equate `f7` with Gmsh face 7.

```text
<SIMPLECAE_PY> scripts/simplecae_cli.py refs resolve "assembly.step#o1.2.f7" --expected-sha256 <HASH_WHEN_SELECTED> --cad-python <CADGEN_PY> --out out/cae/face-ref.json
```

`SIMPLECAE_CADGEN_PY` can replace `--cad-python`. Keep this interpreter isolated;
SimpleCAE never imports cadgen/OCP. `--timeout` defaults to 3000 seconds and is
explicitly adjustable; it bounds this extraction, not a reset of a task's budget.
The output contains a source-bound selector, selected solid, unique matching
evidence, native version and native artifact hash. Use that selector with the
same `model.solid_id`; directions and load magnitude remain explicit inputs.

The reference text alone has no revision hash. Retain the STEP hash at selection
time; if unknown or changed, reopen the current model and reselect. A stale hash,
multiple references, coincident indistinguishable solids or an ambiguous face is
rejected. No nearest-face fallback is used. Canonical scene lookup reads the saved
STEP only; it does not execute model source.
