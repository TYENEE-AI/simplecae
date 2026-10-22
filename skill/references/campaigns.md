# Typed campaigns

Use a data-only manifest, with no scripts or solver directives:

```json
{"schema_version":"simplecae-campaign-1.0","title":"Design candidates","items":[{"id":"candidate-01","case_path":"cases/01.json","case_sha256":"CURRENT_CASE_SHA256"}]}
```

Paths are relative to the manifest; case IDs are unique safe names. Each optional `ledger_path` is a product evidence ledger reviewed after analysis. Run:

```powershell
.\.venv\Scripts\python.exe scripts/simplecae_cli.py campaign campaign.json --out outputs/campaign-01 --reuse-levels outputs/level-cache
.\.venv\Scripts\python.exe scripts/simplecae_cli.py campaign campaign.json --out outputs/campaign-01 --resume --reuse-levels outputs/level-cache
```

Each item gets a child process and a fresh numbered attempt directory. Native crashes retain incomplete solver artifacts and a process log; the remaining items continue. Completion receipts bind the full case physics, contributing source files, solver/package/code versions and output file hashes. Resume rechecks these bindings and the output hashes; missing, interrupted, crashed or tampered attempts get a new attempt. Completed indeterminate outcomes can be reused as diagnostics, but retain their indeterminate status and no comparison margin. A new source, physics or tool version cannot inherit old qualification.

`campaign-result.json` and CLI stdout report actual completed/requested counts, worst `status`, `status_counts` and `all_results_valid`, plus per-case signals and optional evidence review. Exit2 means invalid/error; exit1 means unresolved or incomplete numerical evidence; exit0 means complete valid analyses, which may still include `fail_under_stated_model` designs. Read model status when accepting a candidate. Progress does not imply success. It never grants a whole-product rating and performs no physical tests. Use normal `compare` for qualified shared task contracts; a campaign does not rank incompatible cases. Refer to raw result/mesh/DAT files for interpolation bookkeeping; compact public signals retain measurement locations, values and criterion confidence.
