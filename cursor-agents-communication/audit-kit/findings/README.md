# Audit findings (Evidence Bundles)

Lane 1 and Lane 2 workers write JSON bundles here. Mission Control validates
schema and merges into the candidate matrix.

See [`../evidence-bundle-schema.md`](../evidence-bundle-schema.md).

Do not commit bundles until MC strip-validation passes (required fields present,
`refutes_if` non-empty, pin matches charter).

## Draft artifacts (not indexed)

| File | Status |
|---|---|
| `POPULATION-DRAFT-FINAL.json` | **Draft artifact** — population ledger export for Lane 1 stop-rule validation. **Not indexed in `claims.json`** (out of 26-claim set). |
| `population-draft.tsv` | Working TSV mirror of population scan; not a claim bundle. |
