# Arch-epistemics STATUS

## Confirmed
- Pin == /version SHA: YES (`c9449d6490231373748f19f299ed19d423a1c971`) — E-PROD-VERSION @ 2026-09-20T00:44:36Z
- PR #1294 campaign-only
- Ditto source tag: **cursor**
- F-1b row: PRESENT (`results/F-1b.json`) live WORKER_HEAVY=NOT_OBSERVABLE
- Live-config probe: DRAFT only (`probes/PROBE-LIVE-CONFIG-DRAFT.md`) — **not run**

## Claims
- SMOKE-001 VERIFIED
- C-014 VERIFIED (code-only partial)
- F-1 VERIFIED (code-only partial)
- F-1b RECORDED NOT_OBSERVABLE (Tier B wedge premise)
- **C-016 VERIFIED** (Joshua) — scope code-only, verdict partial
  - Tier A: snapshot path reads SCORE_SNAPSHOT_MAX_SUBNETS; scoring/home reads TOP_SCORING_UNIVERSE (:628 default 20)
  - Tier B: effective caps 40/20; live env NOT_OBSERVABLE
  - X-C-016-CAP: **resolved code-only**
  - **C-016b:** Tracer bundle ACCEPTED — code defaults at :276 confirmed (MAX default 0; worker TOP default 40; else 0); **pending_spotcheck**
- **P-CENSUS-001 VERIFIED** (MC execute at pin) — shutdown(wait=False)=15; .result(timeout=)=17; .result() no timeout=5; ThreadPoolExecutor=41; Thread(=82
- **A2-REPIN** pending_spotcheck — A2 atoms re-pinned to pin blobs via census cites; ~18min magnitude remains NOT_OBSERVABLE
- C-015, C-017: open (not dispatched)

## Rules hygiene
- Ratified `docs/agent-operating-rules-2026-09-01.md` at pin: **Rules 1–18 only**
- **Rules 24–29: NOT PRESENT** in ratified doc (no text; not ratified)
- Rules 19–23: also absent from that file (historical note: earlier brief flagged 19–23 unratified / Rule 21 blank — still not in-repo)

## last_updated
2026-09-20T01:07Z

