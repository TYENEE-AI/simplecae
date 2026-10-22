# Evidence that stays attached to the tested revision

Use the product ledger to explain what has been calculated, what remains unassessed and what needs physical testing. It complements analysis reports; it never alters a model's numerical result or awards a product rating.

```powershell
python scripts/simplecae_cli.py evidence model.step fixture.json controller.h --init --out evidence-ledger.json
python scripts/simplecae_cli.py evidence evidence-ledger.json --out outputs/evidence-001
python scripts/simplecae_cli.py summarize run/result.json --ledger evidence-ledger.json --out outputs/product-001
```

`--init` writes an editable checklist with all items unassessed and SHA256-bound sources. Keep its prior revisions; output review directories must be fresh. Domains cover material, procurement, interfaces, assembly, structure, contact, actuation, force calibration, control, fault response, lifetime and physical acceptance. Omitted domains reappear as unassessed.

Each item has `state`, `statement`, and an `evidence` list:

- `unassessed`: no assessment has been claimed. Supplier documents may be recorded as context.
- `calculated`: a simulation, analytic calculation, software build or software test exists. It does not claim a physical test.
- `physical_pending`: the next step requires real measurement. Calculations may accompany it.
- `physical_recorded`: external physical test/inspection records have been supplied, including their **pass, fail or inconclusive** outcome. This means recorded, not independently certified.

For example, a controller's compiled36 state tests are `calculated`, while ADC integrity, force tracking and fault response on actual hardware remain `physical_pending`. A sensor-error budget±2 N is an assumed acceptance target until its calibration test is recorded; the template CSV is not such a test.

```json
{
  "file":{"path":"bench-test.json","sha256":"<actual64hex>"},
  "kind":"physical_test",
  "applies_to":["source1","source2"],
  "source_sha256":{"source1":"<tested-model64hex>","source2":"<tested-fixture64hex>"},
  "scope":"Static retention with the specified object and fixture only",
  "outcome":"fail",
  "date":"2026-10-14",
  "operator":"Named test operator",
  "test_method":"Procedure and instrument identifiers inside the test record"
}
```

`file` protects the evidence file version. `source_sha256` records the revision to which that evidence applies. Both must match current bindings and file contents; editing a model then refreshing only the ledger binding does not retarget old evidence. Missing or changed records/sources produce `evidence_missing_or_stale`, preserving the originally declared state for audit. A build or software test cannot be relabelled `physical_recorded`. Physical records require outcome, date, operator and test method.

File hashes prove version matching, not measurement truthfulness or adequate test design. Supply a real protocol, measured data and provenance; the tool does not infer those from a filename. Even a complete ledger with passing records sets `whole_product_rating_available` and `certification_available` to false. Review acceptance scope and engineering obligations separately.

Python integrations use `simplecae.evidence.init_ledger`, `inspect_ledger` and `review_ledger`. Canonical `evidence` and `evidence-review` JSON contracts are also checked by `check --kind evidence|evidence-review`.
