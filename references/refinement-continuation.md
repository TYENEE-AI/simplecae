# Continue a refinement without losing the first result

Complete-result `--cache` and solved-level `--reuse-levels` are different opt-in operations. The latter can retain correctly solved mesh levels from an **indeterminate** run. Always use a fresh output directory; never extend or overwrite the original run in place.

```powershell
python scripts/simplecae_cli.py analyze coarse.case.json --out outputs/coarse-001 --reuse-levels outputs/mesh-cache
# Keep unchanged physics, criteria and quality gates; append a smaller size in a new input file.
python scripts/simplecae_cli.py analyze refined.case.json --out outputs/refined-001 --reuse-levels outputs/mesh-cache
```

A level key includes its individual mesh size, exact floating input values, other mesh/quality limits, material, load, gravity, restraint, connections, probes, buckling, source content, toolkit code/package versions and solver executable hash. Only the overall list of requested mesh sizes, notes and provenance are excluded. Changing the mechanical problem, geometry, criterion or software causes a miss. Exact level matching may refuse harmless frame roundoff rather than risk mixing loads.

The cache preserves mesh state, surface data, decks, solver logs, DAT/FRD fields and any fixed-load or buckling outputs. Restoration verifies all file hashes, reads the mesh state and checks current source hashes. The toolkit reconstructs the current full/fixed/buckling input deck and requires exact equality, reparses DAT coverage and values, recomputes static summaries and requested task probes, and rechecks buckling mode coverage. A damaged or incomplete archive is a miss; a failed partial restoration aborts rather than solving in a mixed directory.

Only complete numerical levels that satisfy force/moment balance are stored. A nonconverging peak or large-response concern still needs assessment; retaining its linear field does not turn it into trustworthy physical capacity. The new run reassesses convergence across all its actual levels. `level_reuse` records the original numerical evidence timestamp and origin, and progress emits `level_cache_hit`. Original output files remain unchanged.

Actual DG250 continuation evidence starts at2,1.4,1 mm with unresolved stress. Extending to0.7 mm reused the first three meshes and needed only one new mesh and its two static subcases. The continued assessment exposed a model failure; unverified physical conditions still withheld capacity. Changed normal force and the real thicker CAD both missed the cache. This demonstrates reuse and numerical classification, not speed guarantees or physical validation.

Python `analyze_case`, solid/assembly/robot analyzers and envelopes accept `reuse_levels=PATH`. Keep that directory outside output; a standard CalculiX/Gmsh numerical run is still needed to create the first evidence. This cache is for trusted local artifacts, not a substitute for running untrusted data through normal validation.
