# Post-offload browser audit — #1058 after Cut A+B (`64176d16` / deploy `e8bd9545`)

**Gate verdict: FAIL to close.** Keep [#1058](https://github.com/cryptoreporthub/subnet-dashboard/issues/1058) open. Owner bar for this cut is hero complete ≤10s on **both** runs **and** no `/health` 8s abort pattern (HealthPoller `timeout=8s` → ~8038 ms p95 of `TimeoutError`). Majority of the pair + G0 tie-break: hero completes, but **12.069s / 15.245s** (over budget). Original close bar `/health` p95 <500 ms also **FAIL**. Sequential curl is **not** closure. No Phase 2 JS. No `cockpit_hydrate.js` edit. No `flyctl deploy`. No merge.

**Do not cite `73b681b4` as proof of this cut.**

---

## 1. Live SHA (confirmed before Playwright)

| Surface | Value |
|---------|--------|
| Expected squash on `main` | `64176d16cf76d1c3335c527981f2984f1f70ad94` — `Offload hydrate handlers + bound daily-pick (#1058)` (squash of [#1059](https://github.com/cryptoreporthub/subnet-dashboard/pull/1059), merged 2026-08-26T21:40:55Z) |
| P1-only prod (forbidden as proof) | `73b681b48561b2139b23b74c797888160bb43697` — Fly [run 33004983478](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/33004983478) |
| Latest **Fly Deploy** (`.github/workflows/fly.yml`) | [run 33016781135](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/33016781135) |
| Conclusion | **success** (Deploy Guard SUCCESS, Deploy app SUCCESS) |
| Checkout SHA | `e8bd95453e128bc3eaf23ed2fec932a887899e38` (`fix/hydration-starvation-p0`, `workflow_dispatch`, created 2026-08-26T21:44:58Z, Deploy app completed 2026-08-26T21:49:32Z) |
| Tree identity | `e8bd9545^{tree}` == `64176d16^{tree}` (`49cec2ed…`). Distinct from `73b681b4^{tree}` (`90e62e0c…`). |
| App git SHA | Not exposed. `/api/ops/live` 200 (`live:true`, `worker_mode:split`, peer alive). `/health` 200 `OK` before the pair. `/api/ops/readiness` timed out at 8s (not used as identity). Identity = Actions checkout SHA + `/health` 200. |

Fly MCP was not available in this session. No `flyctl deploy`.

---

## 2. Owner pass bar vs original close bar

| Bar | Criterion | Majority result |
|-----|-----------|-----------------|
| **This cut (owner)** | Hero `HERO_COMPLETE` ≤10s on **both** runs | **FAIL** — 12.069s and 15.245s |
| **This cut (owner)** | `/health` no longer hits the **8s abort pattern** (p95 must not be ~8038 ms of `TimeoutError`) | **Mostly gone on majority runs** — p95 662.8 ms / 550.4 ms of real OK latencies, not a TimeoutError cliff. Residual: 1–2 late-window 8s `TimeoutError`s (p100 still ~8038 ms). |
| Original close | `/health` p95 <500 ms during burst | **FAIL** — 662.8 ms / 550.4 ms |

Verdict for closing #1058: **FAIL** (hero over budget on both majority runs). Offload improved occupancy vs G0/post-P1; it did not meet the stated close bar.

---

## 3. Baseline table (G0 → post-P1 → post-offload)

Harness: `harness/g0_hydration_starvation/run_g0.py` against `https://subnet-dashboard.fly.dev`. Independent cold loads. Prod-1 and prod-2 disagreed, so prod-3 is the G0 tie-break. Majority = prod-1 + prod-3.

| Metric | G0 prod-1 | G0 prod-2 | post-P1-1 | post-P1-2 | **offload-1** | **offload-2** | **offload-3 (tie-break)** |
|--------|-----------|-----------|-----------|-----------|---------------|---------------|---------------------------|
| Captured | 17:53:27Z | 17:55:35Z | 19:31:43Z | 19:33:02Z | **21:55:30Z** | **21:56:52Z** | **22:00:39Z** |
| Live SHA | `bb84de10` | same | `73b681b4` | same | **`e8bd9545` / tree=`64176d16`** | same (wedged) | same |
| Hero complete ≤10s | NEVER | NEVER | NEVER | NEVER | **12.069s** | **NEVER** | **15.245s** |
| stats parsed | never | never | never | never | **12.069s** | never | **15.245s** |
| Hero DOM ready | never | never | 35.962s | never | **12.069s** | never (no hero) | **15.245s** |
| Final hero | Awaiting / COLD | Awaiting / COLD | SN97 at 36s / GATED | Awaiting / COLD | **SN65 / GATED / 44** | **no document** (503 `/`) | **SN65 / GATED / 44** |
| Aborted hero-critical | stats + daily-pick | same | same | same | **(none)** | n/a (0 API) | **(none)** |
| `/health` n / ok | 14 / 8 | 15 / 9 | 13 / 7 | 14 / 8 | **105 / 104** | **6 / 0** | **107 / 106** |
| `/health` p50 / p95 / p100 ms | 937 / **8039** / 8041 | 559 / **8038** / 8039 | 1292 / **8038** / 8040 | 812 / **8038** / 8041 | **122 / 663 / 8039** | **8036 / 8051 / 8055** | **129 / 550 / 8036** |
| TimeoutError mix | 6 consecutive 8s | 6 consecutive 8s | 6 consecutive 8s | 6 consecutive 8s | **2 late-window 8s** (series); windowed summary 1 | **7/7 from t=0** | **2 late-window 8s** (series); windowed summary 1 |
| Max in-flight api | 28 | 28 | 27 | 27 | 26 | 0 | 26 |
| API request count | 42 | 42 | 43 | 40 | 62 | **0** | 60 |
| DCL | ~3s | ~3s | 3.078s | 2.700s | 7.801s | **36.239s** (503) | 11.602s |

---

## 4. HAR-backed browser numbers (do not substitute sequential curl)

Sources: `artifacts/g0-baseline/post-offload-prod-{1,2,3}/{summary.json,requests.json,session.har,health_series.json,baseline.md,hero_t10s.png,hero_t45s.png}`.

### post-offload-prod-1 (`2026-08-26T21:55:30Z`)

- Nav `responseStart` 123 ms; `domContentLoaded` **7.801s**. HTML TTFB is not the stall; DCL itself is slower than G0 (~3s).
- Hero complete: **12.069s** — over the 10s budget. `hydrates_in_budget: false`. Screenshot t=10s still `Awaiting subnet` / COLD; t=45s is SN65 / GATED / HOLD with stats graded 44.
- Hero-critical: `/api/learning/stats` 200 in 3805 ms (start 8.141s). `/api/daily-pick` four 200s, **none aborted**. First HAR body is **stored HOLD** (`status:"ok"`, directional-conflict, `_meta.stale:false`, wait 3715 ms). Later siblings are **timeout HOLD** (`status:"timeout"`, `pick handler busy`, `_meta.stale:true`, waits 815–1266 ms). Do not collapse those payloads.
- `/health` during burst (summary window): n=105, ok=104, errors=1. p50 **122 ms**, p95 **663 ms**, p100 **8039 ms**. Series file has two `TimeoutError: The read operation timed out` at ~t+37.7s and ~t+45.7s (not a fan-out cliff of six consecutive 8s probes). p95 is a real latency, not ~8038 ms of aborts.
- Max concurrent in-flight 46 / api 26. Secondary paths still abort/hang (stream, top-picks, signals, formula-lineage, …).
- Homepage curl sanity after the 50s wait: **TimeoutError 20049 ms**. Sanity only. This leftover load is the likely cause of prod-2’s 503.

### post-offload-prod-2 (`2026-08-26T21:56:52Z`) — disagree / not a hydrate measurement

- Console: `Failed to load resource: … 503` on `/` at t=36.569s. Navigation timing: `responseStart` 36.2s, `encodedBodySize` 0, `transferSize` 300.
- **0 API requests.** Screenshots t=10s and t=45s are blank white. Hero never present.
- `/health`: n=6, ok=0. Every sample is harness 8s `TimeoutError`. p50/p95/p100 **8036 / 8051 / 8055 ms**. This **is** the 8s abort pattern, but it started at t=0 — the machine was already unresponsive after prod-1’s 20s homepage curl, not a 27-way fan-out cliff.
- Idle `/health` after this run stayed timed out for ~67s, then recovered (200 OK 96–249 ms ×3) before prod-3.

### post-offload-prod-3 (`2026-08-26T22:00:39Z`) — G0 tie-break

- Started only after `/health` recovered. Nav `responseStart` 253 ms; `domContentLoaded` **11.602s**.
- Hero complete: **15.245s** — over the 10s budget. t=10s still `Awaiting subnet` / COLD; t=45s SN65 / GATED / 44.
- Hero-critical: `/api/learning/stats` 200 in 3831 ms (start 11.354s). `/api/daily-pick` five 200s, **none aborted**. All five HAR bodies are **timeout HOLD** (`stale:true`), waits 754–3373 ms. Stats still parsed (success payload); hero left the placeholder.
- `/health` summary window: n=107, ok=106, errors=1. p50 **129 ms**, p95 **550 ms**, p100 **8036 ms**. Series has two late-window 8s `TimeoutError`s (~t+41.3s, ~t+49.4s). Same shape as prod-1: p95 is real latency, not an 8s TimeoutError cliff.
- Homepage curl sanity again 20s timeout (not a gate).

**Majority:** prod-1 and prod-3 agree — hero completes after the 10s budget; hero-critical no longer abort; `/health` p95 is ~0.55–0.66s of OK samples, not ~8038 ms of read timeouts. Prod-2 is a post-burst machine 503, not a second independent hydrate fan-out.

---

## 5. `/health` TimeoutError vs real latency (honesty)

G0 / post-P1: after hydrate fan-out, **every** subsequent `/health` hit `urllib` `timeout=8.0` → reported p95 **~8038 ms** of `TimeoutError`. That is the 8s abort pattern. True latency is **≥8s** (censored).

Post-offload majority:

| Run | OK samples | TimeoutError samples | p95 meaning |
|-----|------------|----------------------|-------------|
| offload-1 | 104 | 1 in summary window (2 in full series, late) | **662.8 ms real** |
| offload-3 | 106 | 1 in summary window (2 in full series, late) | **550.4 ms real** |
| offload-2 | 0 | 7/7 from t=0 | **8051 ms TimeoutError cliff** (machine dead, not fan-out) |

The fan-out 8s cliff is **gone** on the two runs that actually hydrated. It is **not** gone as a residual: p100 still clips at the harness 8s timeout late in the 50s window, and the post-run homepage curl (20s) can still wedge `/health` until recovery. Original p95 <500 ms is **not** met.

Raising the harness timeout would change p100, not the hero miss.

---

## 6. Honesty notes

1. **Sequential curl is not closure.** This file does not treat idle `/health` 200 or a later sequential daily-pick as a gate. Close requires the Playwright burst.
2. **Hero at 12s / 15s is not in-budget.** `HERO_COMPLETE` needs stats parsed **and** non-placeholder hero. Both majority runs get there; both miss ≤10s. t=10s screenshots are still `Awaiting subnet` / COLD.
3. **Timeout HOLD vs stored HOLD.** Prod-1 first daily-pick 200 is stored HOLD (`status:"ok"`, stale:false, ~3.7s). Prod-1 later picks and **all** prod-3 picks are timeout HOLD (`stale:true`). Hero still completed because `/api/learning/stats` 200’d.
4. **Prod-2 503 is leftover occupancy, not a second cold hydrate.** 0 API, blank screenshots, health dead from t=0. Tie-break required; majority is prod-1 + prod-3. Do not average prod-2’s 8051 ms p95 into the offload health claim.
5. **Do not use `73b681b4` as proof.** Latest Fly Deploy checkout is `e8bd9545` (same tree as squash `64176d16`).
6. **DCL 7.8–11.6s eats the 10s budget** before hydrate even finishes. Stats+pick then take ~3.8s. That is why complete lands at 12–15s.

---

## 7. Verdict and next

Cut A+B **is deployed** (Fly [33016781135](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/33016781135), SHA `e8bd9545`, tree=`64176d16`). Browser fan-out no longer starves hero-critical to NEVER: stats and daily-pick return 200; hero reaches SN65 / GATED. The G0/post-P1 `/health` 8s TimeoutError **cliff** is gone on majority runs.

**Do not close #1058.** Owner bar for this cut is hero ≤10s on both runs. Measured: **12.069s and 15.245s**. Original `/health` p95 <500 ms also fails (550–663 ms). Phase 2 JS stagger remains a separate, owner-gated PR. No `cockpit_hydrate.js` change in this audit.
