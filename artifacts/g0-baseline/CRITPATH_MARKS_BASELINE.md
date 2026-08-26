# Prod critical-path n=3 baseline — marks deploy (`77395892`)

**Gate: BLOCKED.** n=3 exists; bottleneck classified from marks. Hero budget (complete ≤10s) is **not** met on median. Keep [#1058](https://github.com/cryptoreporthub/subnet-dashboard/issues/1058) **open**. Do not remove pump-alerts preload or stagger fetches this pass.

**Deploy:** Fly Deploy [run 33022098902](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/33022098902) — Deploy Guard SUCCESS, Deploy app SUCCESS (3m 43s), branch `cursor/hero-critical-path-marks-ec01`, checkout SHA `77395892`. Draft PR: [#1061](https://github.com/cryptoreporthub/subnet-dashboard/pull/1061). `main` remains behind this branch.

**Identity (not the old 940-byte shell):** `GET /` after Deploy app SUCCESS returned HTTP 200, `Server-Timing: app;dur=0.4`, HTML 133900 bytes containing `performance.mark('html-parse')`, TTFB 190 ms. Probe: `artifacts/g0-baseline/critpath-post-marks-identity.txt`.

**Harness:** `harness/g0_hydration_starvation/run_g0.py` against `https://subnet-dashboard.fly.dev`. Three spaced loads (`critpath-post-marks-{1,2,3}`) with `/health` 200 <1s recovery between runs. Run 1’s trailing 20s homepage-curl sanity wedged health; run 2 waited until health recovered (then extra spacing). Same after run 2 before run 3. Not Playwright against `73b681b4`. No `flyctl deploy`.

---

## Median table (n=3)

| Metric | Run 1 | Run 2 | Run 3 | **Median** |
|--------|-------|-------|-------|------------|
| Captured (UTC) | 2026-08-26T23:15:20Z | 2026-08-26T23:21:21Z | 2026-08-26T23:27:04Z | — |
| machine_state | warm | warm | warm | **warm** |
| Server-Timing | `app;dur=0.0` | `app;dur=21.0` | `app;dur=3.2` | — |
| TTFB (`responseStart` / html_ttfb ms) | 143.2 | 138.4 | 112.3 | **138.4** |
| html-parse mark (ms) | 151 | 145.3 | 120.1 | **145.3** |
| first script | `dev_pulse.js` end 3281 | `mindmap_graph.js` end 1216 | `dev_pulse.js` end 2046 | end **2046** |
| script wall before DCL | `weekly_letter.js` end 4361 | `home_live_refresh.js` end 4503 | `story_path_ui.js` end 2292 | end **4361** |
| DCL (`domContentLoadedEventEnd` ms) | 4375.7 | 4876.4 | 2695 | **4375.7** |
| hydrate-start (ms) | 4363.1 | 4863.5 | 2680 | **4363.1** |
| hydrate-end (ms) | 7803.4 | 13476.3 | 13581.6 | **13476.3** |
| hydrate measure (ms) | 3440.3 | 8612.8 | 10901.6 | **8612.8** |
| stats start / end (probe s) | 4.710 / 8.138 | 5.184 / 13.453 | 3.015 / 13.780 | start **4.71** / end **13.453** |
| daily-pick start / end (probe s) | 4.710 / 7.668 | 5.184 / 13.785 | 3.015 / 13.903 | — |
| hero complete (probe s) | 8.270 | 13.881 | 13.921 | **13.881** |
| hydrates in 10s budget | yes | no | no | **no** |
| t=10s screenshot | SN55 · NIOME SEALED | Awaiting subnet / COLD | Awaiting subnet / COLD | — |

Harness median file: `artifacts/g0-baseline/critpath-post-marks-median.md`.

---

## Per-run detail

### Run 1 — `critpath-post-marks-1` (HYDRATES_IN_BUDGET)

- machine_state **warm** (`/health` probes 103 / 119 / 112 ms).
- TTFB 143 ms. Server-Timing `app;dur=0.0`. html-parse 151 ms.
- First script `dev_pulse.js` 160→3281 ms (wall 3121 ms). Script wall `weekly_letter.js` 160→4361 ms.
- DCL 4376 ms. hydrate-start 4363 ms (tied to DCL).
- stats + daily-pick both start 4.710 s; stats 200 in 3428 ms; daily-pick 200 in 2958 ms.
- hydrate-end 7803 ms. Hero complete **8.270 s** (SN55 · NIOME, sealed, graded 44).
- `/health` during burst: n=109 / ok=107, p50 116 ms, p95 **470 ms**, p100 8039 ms.
- Trailing homepage-curl sanity: **TimeoutError 20048 ms** — wedged health until ~90 s of 5 s timeouts, then 885 ms OK.

### Run 2 — `critpath-post-marks-2` (STARVATION, over budget)

- Started only after `/health` 200 <1s recovered (streak of 3).
- machine_state **warm** (207 / 203 / 97 ms).
- TTFB 138 ms. Server-Timing `app;dur=21.0`. html-parse 145 ms.
- First script `mindmap_graph.js` end 1216 ms. Script wall `home_live_refresh.js` 152→4503 ms.
- DCL 4876 ms. hydrate-start 4864 ms.
- stats start 5.184 s → end 13.453 s (**8269 ms**). daily-pick start 5.184 s → end 13.785 s (8601 ms, 200; harness also flagged `/api/daily-pick` abort on a sibling request).
- hydrate-end 13476 ms. Hero complete **13.881 s**. t=10s still Awaiting subnet / COLD.
- `/health` n=135 / ok=135, p95 463 ms, p100 7938 ms. Homepage curl sanity again 20 s timeout.

### Run 3 — `critpath-post-marks-3` (STARVATION, over budget)

- Started after run 2 health recovered (≈2 min of 8 s timeouts, then 259/573/218 ms streak + 20 s extra spacing; post-spacing `/health` 92 ms).
- machine_state **warm** (265 / 110 / 88 ms).
- TTFB 112 ms. Server-Timing `app;dur=3.2`. html-parse 120 ms.
- First script `dev_pulse.js` 128→2046 ms. Script wall `story_path_ui.js` 128→2292 ms. **DCL 2695 ms** (fastest of the three).
- hydrate-start 2680 ms. stats 3.015→13.780 s (**10765 ms**). daily-pick 3.015→13.903 s (10888 ms).
- hydrate-end 13582 ms. Hero complete **13.921 s**. t=10s still Awaiting subnet / COLD.
- `/health` n=126 / ok=125, p95 401 ms, p100 8034 ms. Homepage curl sanity 20 s timeout.

---

## Slowest segment (do not remove suspects)

**Slowest segment: hydrate wall** — `hydrate-start` → `hydrate-end`, which is the concurrent `/api/learning/stats` + `/api/daily-pick` fetch after DCL.

Median hydrate measure **8613 ms**. Median stats end **13.453 s**. Median hero complete **13.881 s**. HTML generation is not the stall: Server-Timing 0–21 ms, TTFB median 138 ms, html-parse median 145 ms.

Secondary (not removed this pass): **blocking script wall before DCL** — median script-wall `responseEnd` 4361 ms, median DCL 4376 ms. hydrate-start is tied to DCL (scripts must finish before `cockpit_hydrate.js` marks `hydrate-start`). Run 3 proves a faster DCL (2.7 s) still loses the 10 s budget because stats/daily-pick then take ~10.8 s.

Do **not** remove pump-alerts preload. Do **not** stagger/reorder fetches in `cockpit_hydrate.js` this pass. Marks nominated the hydrate/API occupancy wall; next cut is a separate owner-gated step.

---

## Close gate

| Check | Result |
|-------|--------|
| n=3 on SHA `77395892` | **yes** |
| Identity: Server-Timing + `html-parse` | **yes** |
| Median DCL | **4376 ms** |
| Median stats start | **4.71 s** |
| Median hero complete | **13.881 s** (budget ≤10 s) |
| #1058 close | **no** — budget not met; issue stays open |

Harness dirs: `artifacts/g0-baseline/critpath-post-marks-{1,2,3}/` plus `critpath-post-marks-median.md` / `.json`.
