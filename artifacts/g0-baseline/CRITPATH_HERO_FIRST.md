# Prod critical-path n=3 — hero-first cut (`9f1059da`)

**Gate: BLOCKED.** Product round **1 of 3**. n=3 exists on the hero-first SHA. The gate worked (letters / trail / story-strip / evidence / judges start after stats + daily-pick settle, or after the 12s safety timeout). Median hero complete **14.774 s** misses the ≤10 s budget. Median hydrate-end **14214 ms** did not beat marks **13476 ms**. Keep [#1058](https://github.com/cryptoreporthub/subnet-dashboard/issues/1058) **open**. Do not treat run 1 (4.248 s) as a close. Do not drop pump-alerts preload. Do not stagger the remaining ~27-fetch graph this pass.

**Deploy:** Fly Deploy [#1519](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/33025463740) — Deploy Guard SUCCESS, Deploy app SUCCESS (00:03:21–00:07:22Z), branch `cursor/hydrate-hero-first-ec01`, checkout SHA `9f1059da`, `static_v=7b9cae5e`. Draft PR: [#1062](https://github.com/cryptoreporthub/subnet-dashboard/pull/1062). `main` remains behind this branch.

**#1518 was the wrong branch.** Fly Deploy [run 33025012432](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/33025012432) deployed marks SHA `92b5033` / PR #1061 first. Owner then dispatched #1519 from `cursor/hydrate-hero-first-ec01`. This n=3 is after #1519 only.

**Identity (hero-first, not marks-only):** live `GET /` HTTP 200, `Server-Timing: app;dur=0.4`, HTML **133900** bytes. Script order: `api_fetch.js` immediately then `cockpit_hydrate.js` then `brain_letter.js` … `premium_judges.js`. Served `/static/js/api_fetch.js` (3438 bytes) contains `afterHeroCritical`. Re-checked 2026-08-27T00:24:45Z — still hero-first.

**Harness:** `harness/g0_hydration_starvation/run_g0.py` against `https://subnet-dashboard.fly.dev`. Three spaced loads (`critpath-hero-first-{1,2,3}`) with `/health` 200 <1s recovery between runs. Run 1 leftover 20s homepage-curl sanity wedged health; later runs waited for a streak of three `/health` 200 <1s plus extra spacing. Not Playwright against `73b681b4`. No `flyctl deploy`.

**Vs marks median (`77395892`):** hero complete 13.881 s → **14.774 s** (did not improve). Stats **start** 4.71 s → **2.701 s**. DCL 4376 ms → **2411 ms** (run 2 DCL 9.1 s contended is the outlier). Hydrate-end 13476 → **14214** (did not improve).

---

## Median table (n=3)

| Metric | Run 1 | Run 2 | Run 3 | **Median** |
|--------|-------|-------|-------|------------|
| Captured (UTC) | 2026-08-27T00:10:21Z | 2026-08-27T00:15:05Z | 2026-08-27T00:21:42Z | — |
| machine_state | warm | **contended** | warm | — |
| Server-Timing | `app;dur=0.4` | `app;dur=0.3` | `app;dur=0.3` | — |
| TTFB (`responseStart` ms) | 118.9 | 137.5 | 128.0 | **128.0** |
| html-parse mark (ms) | 127.8 | 144.4 | 136.3 | **136.3** |
| first script | `mindmap_graph.js` end 839 | `dev_pulse.js` end 3816 | `dev_pulse.js` end 1795 | end **1795** |
| script wall before DCL | `letter_export.js` end 1526 | `time_capsule.js` end 9118 | `weighing_room.js` end 1943 | end **1943** |
| DCL (`domContentLoadedEventEnd` ms) | 1643.1 | 9125.7 | 2410.8 | **2410.8** |
| hydrate-start (ms) | 1627.2 | 3818.6 | 2366.8 | **2366.8** |
| hydrate-end (ms) | 3880.5 | 14213.7 | **None** | **14213.7** |
| hydrate measure (ms) | 2253.3 | 10395.1 | None | **10395.1** |
| stats start / end (probe s) | 1.958 / 4.044 | 4.147 / 11.456 | 2.701 / 9.646 | start **2.701** / end **9.646** |
| daily-pick start / end (probe s) | 1.958 / 4.734 | 4.146 / 11.466 | 2.701 / 9.645 | — |
| gated secondaries first start (s) | 4.744 | 14.744 | 14.523 | — |
| `/api/mindmap/graph` start (s) | 1.628 | 4.143 | 2.688 | **co-starts with / before stats** |
| hero complete (probe s) | **4.248** | 14.774 | **NEVER** | **14.774** |
| hydrates in 10s budget | yes | no | no | **no** |
| t=10s screenshot | Closest · SN65 · gated | Awaiting subnet / COLD | Awaiting subnet / COLD | — |
| `/health` p95 (ms) | 440 | 545 | 480 | **480** |

Harness median file: `artifacts/g0-baseline/critpath-hero-first-median.md`.

Hero-complete median treats NEVER as +∞, so the middle of `{4.248, 14.774, ∞}` is **14.774**. Hydrate-end median treats missing as +∞ the same way.

---

## Gate proof (this cut did what it claimed)

Letters / trail / story-strip / evidence / judges **did not** start with stats. They started after hero APIs settled, or after the 12s `afterHeroCritical` safety timeout:

| Run | stats start → end | hydrate-end | first gated fetch | note |
|-----|-------------------|-------------|-------------------|------|
| 1 | 1.958 → 4.044 | 3.881 s | letters/judges/trail/story-strip **4.744 s** | after daily-pick 4.734 s |
| 2 | 4.147 → 11.456 | 14.214 s | letters/trail/story-strip **14.744 s** | after hydrate-end |
| 3 | 2.701 → 9.646 | **never** | letters **14.523 s** | ≈ hydrate-start 2.367 + **12 s safety** |

Run 1 t=10s screenshot still shows TRAIL as `—` while INTEGRATIONS already reads `6/7` (subnet-integrations was not gated and started with stats). That is the intended window.

---

## Remaining occupant with stats (not this cut)

`/api/mindmap/graph` still starts the same millisecond as stats (or earlier, from `mindmap_graph.js` before DCL): 1.628 / 4.143 / 2.688 s. It then sits ~12 s and aborts (`net::ERR_ABORTED`) on every run.

Still self-starting at stats time (not gated): data-freshness, ops/readiness, subnet-integrations, market-drivers, story-path, portfolio/status, watchlist, message-intel, whales/flow-signals, cockpit/stream. `/api/pump-alerts` still preloads at ~0.45 s (before DCL) — **not nominated for removal this round**.

---

## Per-run detail

### Run 1 — `critpath-hero-first-1` (HYDRATES_IN_BUDGET)

- machine_state **warm** (`/health` probes 118 / 113 / 107 ms).
- TTFB 119 ms. Server-Timing `app;dur=0.4`. html-parse 128 ms.
- First script `mindmap_graph.js` end 839 ms. Script wall `letter_export.js` end 1526 ms.
- DCL **1643 ms**. hydrate-start 1627 ms (tied to DCL).
- stats 1.958 → 4.044 s (2086 ms, 200). daily-pick 1.958 → 4.734 s (2776 ms, 200).
- hydrate-end 3881 ms. Hero complete **4.248 s** (Closest · SN65 · True Performance Network, gated, graded 45).
- Gated secondaries 4.744 s. Graph started **1.628 s** (before stats) and aborted at 13.624 s.
- `/health` n=118 / ok=116, p50 115 ms, p95 **440 ms**, p100 8034 ms.
- Trailing homepage-curl sanity: **TimeoutError ~20047 ms**.

### Run 2 — `critpath-hero-first-2` (STARVATION, over budget)

- machine_state **contended** (probes 587 / 241 / 100 ms).
- TTFB 138 ms. Server-Timing `app;dur=0.3`. html-parse 144 ms.
- First script `dev_pulse.js` end 3816 ms. Script wall `time_capsule.js` **9118 ms**. **DCL 9126 ms** (outlier; script wall ate the budget before hydrate started).
- hydrate-start 3819 ms. stats 4.147 → 11.456 s (**7309 ms**). daily-pick 4.146 → 11.466 s (7320 ms, 200).
- hydrate-end 14214 ms. Hero complete **14.774 s**. t=10s still Awaiting subnet / COLD (`statsParsed` false at 9.965 s).
- Gated secondaries 14.744 s. Graph 4.143 s (same ms as stats), abort 16.140 s.
- `/health` n=118 / ok=117, p95 **545 ms**, p100 8034 ms. Homepage curl sanity again ~20 s timeout.

### Run 3 — `critpath-hero-first-3` (STARVATION, hero NEVER)

- machine_state **warm** (250 / 135 / 303 ms).
- TTFB 128 ms. Server-Timing `app;dur=0.3`. html-parse 136 ms.
- First script `dev_pulse.js` end 1795 ms. Script wall `weighing_room.js` end 1943 ms. DCL **2411 ms**.
- hydrate-start 2367 ms. stats 2.701 → 9.646 s (6945 ms, 200). first daily-pick 2.701 → 9.645 s (6944 ms, 200).
- **hydrate-end never.** Hero complete **NEVER**. t=10s Awaiting subnet / COLD (`statsParsed` true at 10.12 s, title still placeholder, graded 0). Final at t=50s still Awaiting subnet / cold / `needsHydrate` true.
- Harness flagged aborted hero-critical `/api/daily-pick` — a later retry still **open at 46.239 s**. First daily-pick 200 did not produce `hydrate-end` or a painted title.
- Gated secondaries 14.523 s ≈ 12 s safety timeout from hydrate-start (cockpit never called `releaseHeroCritical`).
- Graph 2.688 s (same ms as stats), abort 14.686 s.
- `/health` n=128 / ok=127, p95 480 ms, p100 8031 ms. Homepage curl sanity ~20 s timeout.

---

## Slowest segment after this cut

**The gate moved stats start earlier** (median 2.70 s vs marks 4.71 s) by loading `cockpit_hydrate.js` right after `api_fetch.js`. **It did not shorten the stats/daily-pick duration** on contended/warm-but-busy runs (7.3 s / 6.9 s) because `/api/mindmap/graph` and the other self-starters still occupy the same window.

Run 1 proves the window can fit 10 s when the machine is actually warm and graph/occupants do not stall the hero pair. Median is still the contended/never pair.

Do **not** remove pump-alerts preload (still ~0.45 s, finishes before DCL on every run). Next **one** cut, if the owner continues the checklist: defer `/api/mindmap/graph` (and only then other pre-DCL same-origin occupants that start with stats). Do not brute-force the remaining 27.

---

## Close gate

| Check | Result |
|-------|--------|
| n=3 on SHA `9f1059da` after Fly #1519 | **yes** |
| Identity: `afterHeroCritical` + `cockpit_hydrate.js` immediately after `api_fetch.js` | **yes** |
| Gate: secondaries after hero (or 12s safety) | **yes** |
| Median DCL | **2411 ms** (moved vs marks 4376) |
| Median stats start | **2.701 s** (moved vs marks 4.71) |
| Median hydrate-end | **14214 ms** (did not beat marks 13476) |
| Median hero complete | **14.774 s** (budget ≤10 s; worse than marks 13.881) |
| In-budget runs | **1 of 3** (not a close) |
| Product round | **1 of 3** |
| #1058 close | **no** — budget not met; issue stays open |

Harness dirs: `artifacts/g0-baseline/critpath-hero-first-{1,2,3}/` plus `critpath-hero-first-median.md` / `.json`.
