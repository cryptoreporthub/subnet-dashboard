# Mission Control Router (FROZEN companion to CONSTITUTION.md)

**frozen_at:** 2026-09-19T20:06Z

## On every seat reply

1. **Never** paste raw chat into Ledger.
2. **Strip before validate:**
   - Remove greetings / sign-offs / "Here is the JSON:" prose.
   - If wrapped in a markdown fence (```json … ```), use the inner text.
   - Parse the **first** JSON object `{...}` only.
3. Validate against `schema/v1.json`.
4. For code-read bundles, `fetch_method` MUST be one of: `raw` | `api` | `mc_paste`. Missing → reject.
5. Reject falsifier literals: N/A, none, unknown, empty.
6. Invalid → reply to **producing seat only** with the schema error. Do **not** notify Ledger.
7. Valid → write `bundles/<claim_id>.<produced_by>.json` → tell Ledger to merge that **file**.

## Fetch ladder (when MC must paste)

If Tracer/ConfigTruth exhausts raw + api:

1. MC fetches locally (raw then api).
2. Pastes a **bounded** snippet (e.g. server.py lines 620–640).
3. Seat re-emits schema-valid JSON with `fetch_method: "mc_paste"` and those bytes in `bytes_read`.

## SMOKE-001 dispatch checklist

1. CONSTITUTION.md status is **FROZEN**.
2. Dispatch Tracer only; ConfigTruth idle; Ledger awaiting_bundle.
3. On valid bundle → Ledger `pending_spotcheck` (not VERIFIED).
4. Joshua spot-check → `results/SMOKE-001.json` VERIFIED or REJECT.
5. Line **628** lock unchanged: `TOP_SCORING_UNIVERSE = int(os.environ.get("TOP_SCORING_UNIVERSE", "20"))`
