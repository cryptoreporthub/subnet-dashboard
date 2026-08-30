# Occupancy runtime capture (2026-08-30)

Plan §6 item 4 — name the exhausted shared resource. No prod py-spy this pass (no SSH/restart/deploy). Evidence: G0 ×2 on live v2107 (00:49Z / 00:54Z) + HEAD `5a33fe6c` code.

## Exhausted resource

**Primary: CPython GIL + the 2-thread `pick-read` pool on the inline 1-vCPU web+worker box**, multiplied by client retries on GET `/api/daily-pick`.

Not SQLite. Not a third pick handler. `/health` p95 is blast radius on the same process.

## Why that, not something else

| Signal | Points at |
|--------|-----------|
| Sequential GET 184ms when idle | Box is fine; GET is off scoring |
| G0-1 ~9 parallel `/api/daily-pick`, UI `pick handler busy — retry shortly`, `/health` p95 **1245ms** / p100 8076ms | Concurrent hydrates saturate `pick-read` (2 threads) + GIL; retries amplify |
| G0-2 then `/health` 15s timeout + liveness 503; recovered 00:57Z no restart | Process-wide occupancy, not a dead Fly machine |
| 00:15Z 90s tick → HOLD 00:17Z | Separate site: `daily-pick-work` abandoned (`shutdown(wait=False)`), worker may still score/write |
| 00:39Z directional HOLD inside budget | Scoring tail, not constant 90s baseline |

## What this does **not** prove

- Exact fcntl holder on `daily_picks.json` / `pick_score_cache.json` at 00:17Z (need next-recurrence `py-spy` + lock dump).
- Whether `misfire_grace_time=180` absorbed catch-up that night — treat any such run as **inconclusive** for occupancy delta.

## Gate

Rank 1 (GET single-flight) addresses the named GET/GIL/retry resource. Ranks 2/3/(e) contain the tick abandon/write window; they are not a substitute for a later tail-latency Go (plan b3).
