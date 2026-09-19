# Architecture Epistemics — Pass 0 skeleton

**Status:** scaffolding only. No bots running. No smoke executed. No C-014 executed.

**Repo:** `cryptoreporthub/subnet-dashboard`  
**Campaign pin (repo_sha):** `c9449d6490231373748f19f299ed19d423a1c971`  
*(deploy_sha / runtime_ref = NOT_OBSERVABLE until ConfigTruth fills them)*

## Sequence (not either/or)

1. **This folder exists** (Pass 0) — you are here.
2. **Freeze** `CONSTITUTION.md` in Cursor plan mode (read-only campaign law).
3. Stand up 3 Grok seats (Ledger, Tracer, ConfigTruth) with seat prompts.
4. Execute `queue/open/SMOKE-001.json` only.
5. Only if smoke PASS → hard claim ticket (later).

## Seats

| Seat | Job |
|------|-----|
| Ledger | IDs, contradictions, merge **valid** bundles only |
| Tracer | Raw bytes at pin; one hop; smoke / vertical |
| ConfigTruth | Live vs code; pin triple; history only when Pass 6 opened |

**Ditto:** Grok never calls Ditto. Mission Control reads/writes Ditto MCP; Joshua pastes extracts into Ledger as Tier B.

**Router:** Mission Control only. No bot↔bot prose. Malformed bundles are rejected back to the producing seat — never forwarded to Ledger.

## Smoke evidence floor

Smoke is **cheap**, not vague. Bundle PASS only if it includes **literal lines 626–630** of `server.py` at the campaign pin (see `queue/open/SMOKE-001.json`). Prose without bytes = FAIL.
