# Arch-epistemics STATUS

## Official channels
1. **Shared repo (authoritative ledger/artifacts/results):** `cursor-agents-communication/arch-epistemics/` on branch `docs/arch-epistemics-pass0-skeleton` / PR https://github.com/cryptoreporthub/subnet-dashboard/pull/1294
2. **Ditto MCP (coverify mirror):** MC writes dense packets; Ditto cross-checks on Joshua request (repo+pin_sha same turn). Grok seats never call Ditto.

## Gates
- **Gate 0/0b:** CLEARED — SMOKE-001 **VERIFIED** (Option A; lock server.py:628)
- **X-SMOKE-001-LOCUS:** resolved

## Active claim
- **C-014:** Ledger **pending_spotcheck** (verdict **partial**)
  - AFFIRM fresh-starvation (`score_snapshots.py:166`, `scoring_cap.py:107`, write-path `276-280`)
  - REFUTE stale-mtime-surface (`score_snapshots.py:145-146`, `test_score_snapshots.py:50`)
  - bundle: `bundles/C-014.Tracer.json` | results: `results/C-014.json`
  - awaiting Joshua: VERIFIED | REJECT | HOLD

## Pin
`c9449d6490231373748f19f299ed19d423a1c971` — canonical SMOKE blob 128696 bytes / 3379 lines

- **last_updated:** 2026-09-19T22:29Z (MC state sync + Ditto MCP catch-up)
