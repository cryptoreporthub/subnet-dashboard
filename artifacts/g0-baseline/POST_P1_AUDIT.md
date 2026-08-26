# Post-deploy browser audit — #1058 after P1 (`73b681b4`)

**Gate verdict: FAIL to close.** Hero budget (complete ≤10s) and `/health` p95 during burst are not met. Keep [#1058](https://github.com/cryptoreporthub/subnet-dashboard/issues/1058) open. Phase 2 (client stagger) remains; owner GO. Do not merge this PR as a close of #1058.

**Deploy:** Fly Deploy [run 33004983478](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/33004983478) — Deploy Guard SUCCESS, Deploy app SUCCESS, SHA `73b681b4`. Draft PR: [#1059](https://github.com/cryptoreporthub/subnet-dashboard/pull/1059). `main` remains `bb84de10`.

**Harness:** same Playwright G0 runner (`harness/g0_hydration_starvation/run_g0.py`) against `https://subnet-dashboard.fly.dev`. Two independent cold loads after deploy: `post-p1-prod-1` (`2026-08-26T19:31:43Z`) and `post-p1-prod-2` (`2026-08-26T19:33:02Z`).

---

## What P1 did vs did not fix

P1 removed the sequential 8s timeout HOLD occupancy on `GET /api/daily-pick` (hydrate no longer waits the scoring pool). Sequential traffic after deploy returned in **0.75s** with stored scheduler HOLD (`status:"ok"`, `action:"HOLD"`, reason directional-conflict, `_meta.stale:false`) versus G0 sequential **8.30s** `status:"timeout"` HOLD.

That sequential win is **not** closure. The 28-way browser hydrate fan-out still starves the shared-cpu web + inline-worker event loop: `/health` p95 during burst remains ~8s, `/api/learning/stats` never parses in 50s, hero complete remains NEVER.

---

## Baseline vs post-P1

| Metric | G0 prod-1 | G0 prod-2 | post-p1-1 | post-p1-2 |
|--------|-----------|-----------|-----------|-----------|
| Captured | 2026-08-26T17:53:27Z | 2026-08-26T17:55:35Z | 2026-08-26T19:31:43Z | 2026-08-26T19:33:02Z |
| Hero complete ≤10s | NEVER | NEVER | NEVER | NEVER |
| stats parsed | never | never | never | never |
| Hero DOM ready | never | never | **35.962s** (over budget) | never |
| Final hero | `Awaiting subnet` / COLD | `Awaiting subnet` / COLD | title SN97 at 36s / GATED | `Awaiting subnet` / COLD at 50s |
| Aborted hero-critical | daily-pick + stats | same | same (stats abort; daily-pick abort + one late 200) | same (first-window abort; later retry still open) |
| `/health` n / ok | 14 / 8 | 15 / 9 | 13 / 7 | 14 / 8 |
| `/health` p50 / p95 / p100 | 937 / **8039** / 8041 ms | 559 / **8038** / 8039 ms | 1292 / **8038** / 8040 ms | 812 / **8038** / 8041 ms |
| Max concurrent in-flight (all / api) | 47 / 28 | 46 / 28 | 47 / 27 | 47 / 27 |
| API request count | 42 | 42 | 43 | 40 |
| Sequential `/api/daily-pick` | 8.30s timeout HOLD | — | **0.75s stored HOLD** (post-deploy; not a close gate) | — |

Rollback not triggered on hero-complete p95 (still NEVER, not a regression vs G0 NEVER). `/health` p95 during burst still ≥500ms — expected residual occupancy, not a silent close.

---

## HAR-backed browser numbers (do not substitute sequential curl)

Sources: `artifacts/g0-baseline/post-p1-prod-1/{summary.json,requests.json,session.har,health_series.json,baseline.md}` and the matching `post-p1-prod-2/` files.

### post-p1-prod-1 (`2026-08-26T19:31:43Z`)

- Nav TTFB `responseStart` 154 ms; `domContentLoaded` 3.078s. HTML is not the stall.
- Hero complete: **NEVER**. `stats_parsed_at_s`: null. `hydrates_in_budget`: false. `starvation_shape`: true.
- Hero DOM ready at **35.962s** — title `Closest · SN97 · Albedo`, verdict `gated`, graded `0`. Still over the 10s budget. Screenshot t=10s is still `Awaiting subnet` / COLD; t=45s shows SN97 / GATED / HOLD.
- `/health` during burst: n=13, ok=7, errors=6. Early probes 98–224 ms OK (one 1292 ms spike). From the fan-out cliff, six consecutive harness 8s timeouts. p50 **1292 ms**, p95 **8038 ms**, p100 **8040 ms**.
- Max concurrent in-flight 47 / api 27. Pending at t=45s includes hero-critical `/api/learning/stats` (open from 31.778s) and `/api/daily-pick` (open from 35.71s and 38.836s).
- Homepage curl sanity after this run: 200 in 2556 ms (sanity only, not a gate).

**`/api/daily-pick` (HAR + `requests.json`):**

| start_s | duration_ms | HTTP | HAR body |
|---------|-------------|------|----------|
| 3.472 | 32238 | **200** | `status:"timeout"`, `action:"HOLD"`, `reason:"pick handler busy — retry shortly"`, `_meta.stale:true`, `data_source:"local"` |
| 3.473 | 34999 | aborted `net::ERR_ABORTED` | no body |
| 5.478 | 8000 | aborted `net::ERR_ABORTED` | no body |
| 35.710 | still open at close | — | — |
| 38.836 | still open at close | — | — |

The one completed 200 is **timeout HOLD**, not stored scheduler HOLD. Wait in HAR was 32202 ms. Do not cite this 200 as the P1 stored-HOLD win.

**`/api/learning/stats`:** first request start 3.472s, aborted at 31.471s (27999 ms); retry at 31.778s still open at 50s. Never parsed.

### post-p1-prod-2 (`2026-08-26T19:33:02Z`)

- Nav TTFB 140 ms; `domContentLoaded` 2.700s.
- Hero complete: **NEVER**. `hero_dom_ready_at_s`: null. Final title `Awaiting subnet`, verdict `cold`, placeholder still true at 50.231s. Screenshots t=10s and t=45s both COLD.
- `/health`: n=14, ok=8, errors=6. Early probes 96–354 ms OK (one 1201 ms spike). Then six consecutive 8s timeouts. p50 **812 ms**, p95 **8038 ms**, p100 **8041 ms**.
- Max concurrent in-flight 47 / api 27. Pending at t=45s includes `/api/learning/stats` (open from 31.353s) and `/api/daily-pick` (open from 38.301s).
- Homepage curl sanity after this run: **TimeoutError** 20050 ms (sanity only). Burst still saturates the shared runtime.

**`/api/daily-pick` (HAR + `requests.json`) — first-window abort, no later 200:**

| start_s | duration_ms | HTTP |
|---------|-------------|------|
| 3.023 | 34995 | aborted `net::ERR_ABORTED` |
| 3.024 | 34999 | aborted `net::ERR_ABORTED` |
| 5.030 | 8000 | aborted `net::ERR_ABORTED` |
| 38.301 | still open at 50s close | no HAR 200 |

Do not treat a late retry as closure. Run-2 never delivered a daily-pick 200 in the 50s window. Run-1’s late 200 was timeout HOLD after 32s, not stored HOLD, and stats still never parsed.

**`/api/learning/stats`:** first request start 3.024s, aborted at 31.023s (27999 ms); retry at 31.353s still open. Never parsed.

---

## Honesty notes

1. **Timeout HOLD vs stored HOLD.** Scheduler HOLD (`status:"ok"`, directional-conflict, `_meta.stale:false`) and timeout HOLD (`status:"timeout"`, `reason:"pick handler busy — retry shortly"`, `_meta.stale:true`) are different payloads that share `action:"HOLD"`. P1’s sequential honesty win is stored HOLD without an 8s wait. The only browser daily-pick 200 (run-1, 32s) is timeout HOLD. Do not collapse them.
2. **Sequential 0.75s is not closure.** Close requires two agreeing browser cold loads with hero complete ≤10s **and** `/health` p95 <500ms during the same burst. Sequential curl does not exercise the 27-way `/api/*` fan-out.
3. **Run-2 later daily-pick 200 vs first-window abort.** HAR does not show a run-2 200. First-window requests aborted (8s and 35s client timeouts). The t=38.3s retry was still open at close. Run-1’s 32s 200 is the late completion; it is timeout HOLD and does not hydrate stats.
4. **Hero title at 36s is not in-budget.** Run-1 leaving `Awaiting subnet` at 35.962s is still a miss of the 10s hero budget. Run-2 never left the placeholder.
5. **`/health` p95 ~8038 ms is the residual.** Same cliff as G0: OK until fan-out, then harness 8s timeouts. Occupancy cuts on the request path do not, by themselves, guarantee `/health` p95 <500ms under hydrate fan-out.

---

## Sequential smoke (not a close gate)

Post-deploy (recorded in the first draft of this file, immediately after fly.yml SUCCESS): `GET /api/daily-pick` **0.75s**, `status:"ok"`, `action:"HOLD"`, reason directional-conflict, `_meta.stale:false`. Versus G0 **8.30s** timeout HOLD.

Packaging-time recheck (2026-08-26, after the two Playwright runs; still not a gate):

| Endpoint | HTTP | time_total | Body |
|----------|------|------------|------|
| `GET /health` | 200 | 0.124s then 0.111s | `OK` |
| `GET /api/daily-pick` | 200 | 0.662s then 0.680s | `status:"timeout"`, `action:"HOLD"`, `reason:"pick handler busy — retry shortly"`, `_meta.stale:true` |

Sequential remains ~sub-second (no 8s wait). This later curl is **timeout HOLD**, not stored HOLD. That does not undo the post-deploy stored-HOLD observation, and it does not close #1058.

---

## Verdict and next

P1 landed and deployed: sequential daily-pick no longer burns `PICK_HANDLER_TIMEOUT` (8s). Browser 28-way fan-out still starves `/health` (~8s p95) and never parses `/api/learning/stats` in 50s. Hero complete remains NEVER on both post-deploy Playwright runs.

**Do not close #1058.** Phase 2 JS stagger is next, separate PR, owner GO. Infra topology (`fly.toml`) stays owner-gated. No rollback from hero-complete (unchanged NEVER vs G0).
