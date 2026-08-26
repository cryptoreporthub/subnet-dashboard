# Post-P1 re-audit diagnosis — #1058 (no Phase 2, no deploy)

**Gate verdict: FAIL.** Keep [#1058](https://github.com/cryptoreporthub/subnet-dashboard/issues/1058) open. Phase 2 (`static/js/cockpit_hydrate.js` stagger) remains blocked. No product SHA shipped. No close, no merge, no `flyctl deploy`.

**Live SHA:** `73b681b4` (P1). **Harness SHA on this branch:** `af19e409` artifacts-only + this reprobe. Draft PR [#1059](https://github.com/cryptoreporthub/subnet-dashboard/pull/1059). `main` remains `bb84de10`.

**Fresh pair:** `post-p1-reprobe-1` (`2026-08-26T20:24:21Z`) and `post-p1-reprobe-2` (`2026-08-26T20:25:45Z`) against `https://subnet-dashboard.fly.dev`.

---

## 1. Gate table

| Metric | reprobe-1 | reprobe-2 | Close bar |
|--------|-----------|-----------|-----------|
| Hero complete | **49.719s** | **NEVER** | ≤10s both runs |
| stats parsed | 49.719s (retry 200) | never | required |
| Hero DOM ready | 48.438s | never | — |
| Final hero | SN65 / GATED / graded 44 | Awaiting subnet / COLD | — |
| `/health` p95 | **8038 ms** | **8038 ms** | <500 ms |
| `/health` errors | 6/13 `TimeoutError` 8s | 5/10 `TimeoutError` 8s | — |
| Max in-flight api | 28 | 27 | — |

Idle sequential (not a close gate): `/health` 175 ms OK; `/api/learning/stats` 137 ms 200; `/api/daily-pick` 618 ms timeout HOLD (`stale:true`). Sequential stats is cheap. Browser burst is the stall.

---

## 2. Why hero never completes (or completes at 50s)

`HERO_COMPLETE` in `harness/g0_hydration_starvation/run_g0.py` requires **both** `window.SimiLearning.stats` parsed **and** hero DOM non-placeholder. Budget is 10s.

Causal chain:

1. `cockpit_hydrate.js` `run()` + `bootstrapCouncilHeroHydrate()` + `kickPriorityPanels()` + SSE fire together at DCL (~2–5s). First-window fan-out is **27–28** `/api/*` (observed max 27–28).
2. `/api/learning/stats` **does start in budget** (`reprobe-1` 2.297s, `reprobe-2` 5.074s, post-p1-1 3.472s). It does **not** hang without a request.
3. First stats fetch is client-aborted at **28000 ms** (`fetchJsonRetry(..., 28000, 2)` → `AbortController`). HAR status `-1`, no body. Server never delivered a 200 in that window.
4. Retry starts ~t=31–33s. On reprobe-1 the retry returned **200 at 49.701s** → stats parsed 49.719s (over budget). On reprobe-2 / post-p1-1 / post-p1-2 the retry was **still open at 50s close**.
5. Hero DOM can leave `Awaiting subnet` **without** stats: post-p1-1 title SN97 at 35.962s after a late daily-pick 200. Harness still will not fire `HERO_COMPLETE` until stats parses. That 36s title is also over the 10s budget.
6. The late daily-pick 200 on post-p1-1 was **timeout HOLD** (HAR wait 32202 ms, `status:"timeout"`, `_meta.stale:true`) — not the sequential stored-HOLD win. `PICK_READ_TIMEOUT` is 0.5s; `asyncio.wait_for` cannot expire while the loop is starved, so the client sees a 32s wait.

SSR/HTML is not the stall (nav TTFB 129–154 ms).

---

## 3. Why `/health` p95 is ~8s

**8038 ms is the harness probe timeout, and it is also a true miss.** `HealthPoller` uses `urllib.request.urlopen(..., timeout=8.0)`. Failed samples are `TimeoutError: The read operation timed out` at 8032–8041 ms. p95 of a series that is half 8s-timeouts **is** ~8038 ms. True latency is **≥8s** (censored), not a healthy 8.038s round-trip.

Cliff: probes are 95–557 ms OK until the hydrate fan-out (~t=2.3–3.5s), then every subsequent probe hits the 8s abort until the run ends. `/health` is `async def` and load-shed-bypassed (`server.py` + `internal/load_shed.py`). If it cannot answer in 8s, the event loop / shared vCPU is occupied.

Raising the harness timeout would change the reported number, not the starvation.

---

## 4. Remaining amplifiers (P1 sequential win stands)

Daily-pick scoring is **demoted**. Sequential GET is sub-second (timeout HOLD or stored HOLD). Under burst it still waits tens of seconds because timeouts cannot fire on a starved loop.

Ranked remaining occupants (do not “fix” inside `select_daily_pick`, `fly.toml`, Dockerfile, resolver/grading, Telegram, `internal/liveness.py`, or `cockpit_hydrate.js`):

1. **27-way client fan-out** (trigger). Duplicate hero-critical: `bootstrapCouncilHeroHydrate()` and `run()` both call `loadLearningStats()` + `fetchDailyPickForHero()` at the same instant.
2. **Shared-cpu GIL / vCPU**: `REQUEST_EXECUTOR` (4) + `_DASHBOARD_EXECUTOR` + default aio pool (4) + inline worker. `_learning_snapshot()` trail scan + judges-all + subnets + simivision + graph compete on one Fly shared-cpu.
3. **On-loop sync work in the burst**: `api_mindmap_trail` runs `collect_trail_events()` on the event loop (load-shed bypassed); `api_dev_radar` builds payload on-loop; `whales_flow_signals` and `api_message_intel_status` also on-loop. Trail scan is the same class of work `_learning_snapshot` already moved off-loop because it “costs seconds on a warm volume.”
4. **Load-shed bypass of “light” APIs** (`/api/learning/`, letters, ops, trail, …) so ~27 handlers still run; MAX_IN_FLIGHT=12 only sheds the rest.
5. **Client retry storm** after 6–35s AbortController timeouts (stats 28s, daily-pick 35s, others 8/12/15/18/22/25s).

No tiny non-Phase-2 handler rewrite can make `/health` run if the 1-vCPU GIL is already occupied by that burst. Local same burst (`/health` p95 ~1.4 ms) is extra CPU, not evidence against prod occupancy.

---

## 5. Code change

None. Not Phase 2 JS. Not a harness timeout bump (would hide the miss). A server occupancy cut of trail/dev-radar off the loop is real but **not tiny enough to close the gate without a fly.yml redeploy**, and would not by itself guarantee hero ≤10s under 27-way fan-out.

---

## 6. Next owner action

**Stay parked.** Do not close #1058. Do not merge #1059 as a close. Do not deploy. Phase 2 JS stagger remains **forbidden until owner GO**. Any Python occupancy cut still needs owner `fly.yml` dispatch to verify on live prod.
