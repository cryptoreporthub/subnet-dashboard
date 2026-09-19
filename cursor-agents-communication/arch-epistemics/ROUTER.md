# Mission Control Router

## On seat reply

1. Do **not** paste raw chat into Ledger.
2. Extract JSON:
   - Drop leading prose (e.g. "Here is the bundle:")
   - If fenced with ` ```json ` / ` ``` `, take inner block
   - Parse first `{...}` object
3. Validate required fields in `schema/v1.json` (including `fetch_method` for code reads).
4. Reject falsifier literals: N/A, none, unknown, empty.
5. If invalid → reply to **that seat only** with the schema error. Do not notify Ledger.
6. If valid → write `bundles/<claim_id>.<produced_by>.json` and tell Ledger: "merge file X".

## Dispatch SMOKE-001

1. Confirm `CONSTITUTION.md` status is FROZEN.
2. Paste Tracer seat pack + ticket JSON into Tracer session.
3. If Tracer cannot fetch → MC runs fetch ladder locally and pastes lines 620–640 with `fetch_method: mc_paste` instruction for Tracer to package (Tracer still must emit schema-valid JSON; it may cite mc_paste).
4. After valid bundle file exists → Ledger merge only.
5. Write `results/SMOKE-001.json` as VERIFIED or NOT_OBSERVABLE — Joshua/MC spot-check bytes before VERIFIED.
