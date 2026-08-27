# Prod critical-path n=3 — graph-defer cut (Fly #1521, `653ef795`)

**Close: no.** [#1058](https://github.com/cryptoreporthub/subnet-dashboard/issues/1058) **stays open.** Product round **2 of 3**. One in-budget run is not a close; this n=3 has a **majority (2/3)** in the ≤10 s budget and median hero **9.518 s** vs marks **13.881 s**, but the issue stays open. Do not merge. Do not drop pump-alerts preload.

**Graph gate: yes.** `/api/mindmap/graph` did **not** co-start with stats. Starts were **9.509 / 9.293 / 10.772 s**, after stats+daily-pick settled (or with the other gated secondaries), not 1.6–4.1 s with stats as on Fly #1519.

**Deploy:** Fly Deploy [#1521](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/33033421906) SUCCESS. Branch `cursor/hydrate-hero-first-ec01`, SHA `653ef795`, `static_v=d7c4c971`. Draft PR [#1062](https://github.com/cryptoreporthub/subnet-dashboard/pull/1062). Identity (pre-harness): `GET /` 200, 133900 bytes, `Server-Timing: app;dur=0.3`, served `mindmap_graph.js` contains `afterHeroCritical` and `refreshGraphUngated`. No `flyctl deploy` from the agent.

**Harness:** `harness/g0_hydration_starvation/run_g0.py` against `https://subnet-dashboard.fly.dev`. Three spaced loads (`critpath-graph-defer-1521-{1,2,3}`). After each run, waited for three consecutive `GET /health` 200 &lt;1s plus extra 20 s (leftover 20 s homepage-curl sanity wedges `/health` for ~1–2 min of 8 s timeouts). Not Playwright against `73b681b4`.

**Vs marks median (`77395892`):** hero complete 13.881 s → **9.518 s**. Hydrate measure 8613 ms → **6713 ms**. Graph start no longer matches stats.

---

## Median table (n=3)

| Metric | Run 1 | Run 2 | Run 3 | **Median** | Marks |
|--------|-------|-------|-------|------------|-------|
| Captured (UTC) | 2026-08-27T02:55:44Z | 2026-08-27T03:00:22Z | 2026-08-27T03:05:32Z | — | — |
| machine_state | warm | warm | warm | **warm** | warm |
| Server-Timing | `app;dur=0.3` | `app;dur=10.6` | `app;dur=0.4` | — | — |
| TTFB (ms) | 117 | 135.9 | 117.3 | **117.3** | 138.4 |
| DCL (ms) | 2344.7 | 3770.3 | 2733.5 | **2733.5** | 4375.7 |
| hydrate-start / end (ms) | 2309.8 / 9022.8 | 3754.4 / 6299.1 | 2707.8 / 10431.2 | start **2707.8** / end **9022.8** | 4363 / 13476 |
| hydrate measure (ms) | 6713 | 2544.7 | 7723.4 | **6713** | **8613** |
| stats start / end (s) | 2.793 / 9.414 | 4.087 / 6.300 | 3.046 / 10.631 | start **3.046** / end **9.414** | 4.71 / 13.45 |
| daily-pick start / end (s) | 2.793 / 9.487 | 4.087 / 6.315 | 3.045 / 10.768 | — | — |
| **graph start (s)** | **9.509** | **9.293** | **10.772** | **after stats settle** | 1.6–4.1 with stats |
| gated secondaries first start (s) | 9.508 | 9.293 | 10.771 | with graph | n/a |
| **hero complete (s)** | **9.518** | **6.707** | 10.886 | **9.518** | **13.881** |
| hydrates in 10s budget | yes | yes | no | **majority yes (2/3)** | no |
| t=10s hero | Closest · SN65 · gated | Closest · SN65 · gated | Awaiting subnet / COLD | — | — |
| `/health` p95 (ms) | 617 | 519 | 490 | **519** | — |

Hero-complete median of `{9.518, 6.707, 10.886}` is **9.518**. Graph does not co-start with stats on any run.

---

## Graph gate proof

| Run | stats start → end | daily-pick end | graph start | first gated (letters) | co-start with stats? |
|-----|-------------------|----------------|-------------|----------------------|----------------------|
| 1 | 2.793 → 9.414 | 9.487 | **9.509** | 9.508 | **no** |
| 2 | 4.087 → 6.300 | 6.315 | **9.293** | 9.293 | **no** (starts after settle; ~3 s after hydrate-end 6.299) |
| 3 | 3.046 → 10.631 | 10.768 | **10.772** | 10.771 | **no** |

Fly #1519 graph starts were 1.628 / 4.143 / 2.688 s (same millisecond as stats). This cut moved graph into the gated-secondary wave.

Graph still aborts ~12 s later (`net::ERR_ABORTED`) on every run — occupancy after hero, not during it.

Pump-alerts preload still fires at ~0.45–0.60 s (before DCL). Left as required.

Still self-starting with stats (out of scope): data-freshness, ops/readiness, subnet-integrations, market-drivers, story-path, portfolio/status, watchlist, message-intel, whales/flow-signals, cockpit/stream, dev-radar.

---

## Per-run detail

### Run 1 — `critpath-graph-defer-1521-1` (HYDRATES_IN_BUDGET)

- machine_state **warm** (114 / 94 / 115 ms).
- TTFB 117 ms. Server-Timing `app;dur=0.3`. DCL **2345 ms**. hydrate-start 2310 ms.
- stats 2.793 → 9.414 s (6621 ms, 200). daily-pick 2.793 → 9.487 s (6694 ms, 200).
- hydrate-end 9023 ms. Hero complete **9.518 s**. t=10s Closest · SN65 · True Performance Network, gated, graded 46.
- Graph **9.509 s** (after daily-pick 9.487). Letters 9.508 s. Graph abort 21.502 s.
- `/health` p95 **617 ms**, p100 8035 ms. Homepage curl sanity TimeoutError ~20046 ms.

### Run 2 — `critpath-graph-defer-1521-2` (HYDRATES_IN_BUDGET)

- machine_state **warm** (262 / 101 / 288 ms).
- TTFB 136 ms. Server-Timing `app;dur=10.6`. DCL **3770 ms**. hydrate-start 3754 ms.
- stats 4.087 → 6.300 s (2213 ms, 200). daily-pick 4.087 → 6.315 s (2228 ms, 200).
- hydrate-end 6299 ms. Hero complete **6.707 s**. t=10s Closest · SN65 · gated, graded 46.
- Graph **9.293 s** with letters (after settle; not with stats at 4.087). Graph abort 21.289 s.
- `/health` p95 **519 ms**, p100 8031 ms. Homepage curl sanity ~20048 ms.

### Run 3 — `critpath-graph-defer-1521-3` (over budget 10.886 s)

- machine_state **warm** (120 / 113 / 97 ms).
- TTFB 117 ms. Server-Timing `app;dur=0.4`. DCL **2734 ms**. hydrate-start 2708 ms.
- stats 3.046 → 10.631 s (7585 ms, 200). daily-pick 3.045 → 10.768 s (7723 ms, 200).
- hydrate-end 10431 ms. Hero complete **10.886 s**. t=10s still Awaiting subnet / COLD (`statsParsed` false at 9.946 s). Final title at t=50s is SN65 gated.
- Graph **10.772 s** (after daily-pick 10.768). Letters 10.771 s. Graph abort 22.768 s.
- `/health` p95 **490 ms**, p100 8034 ms. Homepage curl sanity ~20045 ms.

---

## Close gate

| Check | Result |
|-------|--------|
| n=3 on SHA `653ef795` after Fly #1521 | **yes** |
| Identity: `afterHeroCritical` + `refreshGraphUngated` in served `mindmap_graph.js` | **yes** |
| Graph co-starts with stats | **no** (9.509 / 9.293 / 10.772 vs stats 2.8 / 4.1 / 3.0) |
| Median hydrate measure vs marks 8613 ms | **6713 ms** (moved) |
| Median hero complete vs marks 13.881 s | **9.518 s** (moved) |
| Majority ≤10 s | **yes (2/3)** |
| #1058 close | **no** — stays open; do not merge |

Harness dirs: `artifacts/g0-baseline/critpath-graph-defer-1521-{1,2,3}/`.
