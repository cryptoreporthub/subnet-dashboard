# LOCK — #1058 Phase 2 (client hydrate stagger)

**Agent:** Drift/QA (Grok 4.6 medium design)
**Date:** 2026-08-27 (America/Phoenix)
**Issue:** https://github.com/cryptoreporthub/subnet-dashboard/issues/1058
**Live evidence:** G0 PASS starvation; P1 `64176d16` sequential daily-pick win; post-P1 / post-P1-reprobe FAIL close (hero >10s or NEVER; `/health` p95 ~8s; stats first fetch aborted 28s).
**Do not re-litigate:** shared-cpu web+inline-worker occupancy from hydration fan-out at DCL (~2–5s), not sequential daily-pick scoring alone.

---

## VERDICT: CONDITIONAL

Phase 2 JS stagger is the correct next product cut and is **necessary** to remove the 27–28 `/api/*` fan-out that kills `/health` and aborts `/api/learning/stats`.

It is **not sufficient to close #1058 by assertion**. Close remains: two agreeing **prod G0 browser** runs with hero complete ≤10s **and** `/health` p95 <500ms during the same burst. If after 2a+2b the first 10s in-flight `/api/*` is ≤3 and `/health` p95 is still ≥500ms, that is no longer a client-fan-out bug — escalate (shared-cpu / on-loop Python), do not add more JS.

P1 sequential daily-pick win stands. Timeout HOLD vs stored HOLD stay distinct. Sequential curl is not a close gate.

---

## DECISIONS

1. **One hero-critical owner.** `run()` is the only function allowed to fetch `/api/learning/stats` and `/api/daily-pick` on first paint. `bootstrapCouncilHeroHydrate()` must not issue those fetches (SSR/cache paint only). Dedup in-flight: `loadLearningStats` / `fetchDailyPickForHero` share one promise each (`window.__heroStatsPromise` / `window.__heroPickPromise`). Today both fire at script-eval and again at DCL (G0: daily-pick ×4, stats ×2).

2. **Max concurrent hydrates in the hero window = 2.** Window = `DOMContentLoaded` → `HERO_COMPLETE` or 10s, whichever first. Allowed in-flight: `/api/learning/stats` + `/api/daily-pick` only. Forbidden in that window: SSE, `kickPriorityPanels()`, trail, pump-alerts, subnets, story-strip, letters, judges-all, evidence, message-intel, simivision, portfolio, `living_focus` coldBootstrap network.

3. **SSE deferral.** `connectCockpitStream()` only after hero complete **or** 10s elapsed. `cockpit.sections` must not dispatch `home:cockpit-tick` during the hero window (that path pulls daily-pick + resolved + subnets via `home_live_refresh.js`).

4. **Retry / abort (hero window).**
   - `/api/learning/stats`: timeout **4000 ms**, **retries = 0** in-window. One idle retry only after the 10s gate (not `fetchJsonRetry(..., 28000, 2)` which is the 28s AbortController in every FAIL HAR).
   - `/api/daily-pick`: timeout **4000 ms**, **retries = 0** in-window. A 200 with `status:"timeout"` + `action:"HOLD"` + `_meta.stale:true` is a **terminal hero payload** (paint it). `dailyPickNeedsHeroRetry()` must **not** treat timeout HOLD as “needs retry”. `scheduleCouncilHeroRetry` / `fetchDailyPickForHero({force:true})` only after the 10s gate.
   - Do not use the `ms + attempt * 4000` bump on hero-critical URLs.

5. **Timeout HOLD honesty.** Keep `status:"timeout"`, `action:"HOLD"`, `_meta.stale:true`. Do not rewrite into stored scheduler HOLD (`status:"ok"`, `_meta.stale:false`). If the 4s abort fires with no body, leave SSR placeholder; do not invent a fresh HOLD.

6. **HomeHydrateCache.** On first daily-pick 200 (including timeout HOLD): set `HomeHydrateCache.dailyPick` + `at`. On stats parse: `SimiLearning.stats` (already). `trail`, `subnets`, `subnetsMeta`, `simivision` stay cache keys but are filled in **2b only**. `living_focus` / `home_live_refresh` must read cache and not refetch those URLs during the hero window.

7. **Post-hero concurrency cap (2b) = 2.** Remaining endpoints go through a small queue (not `Promise.all` of the rest). `kickPriorityPanels` + `startTrailHydration` + pump + subnets + story-strip start only after the gate, two at a time.

8. **`living_focus.js` must wait.** `init()` / `coldBootstrap()` / `dailyPickPromise()` must not hit `/api/daily-pick`, `/api/simivision`, `/api/judges/*`, trail, or chip APIs until `home:hydrate-cache` **or** 10s. Prefer `HomeHydrateCache`. A 2s `coldBootstrap` timer during the hero window recreates fan-out.

9. **`home_live_refresh.js`:** no new DCL fetches. `refreshHomeHotPath` already no-ops unless `data-hydrate=1`; keep it quiet until SSE is allowed. Skip ticks while `window.__heroCriticalUntil > Date.now()` or stats unset.

10. **Forbidden in the Composer diff:** `fly.toml*`, `Dockerfile`, `internal/council/resolver.py`, grading modules, `select_daily_pick` / scoring, `internal/worker_proxy.py`. No harness timeout bump to hide `/health` p95.

---

## FILES

| Path | Functions / behavior |
|------|----------------------|
| `static/js/cockpit_hydrate.js` | **Primary.** `run()`, `bootstrapCouncilHeroHydrate()`, `kickPriorityPanels()`, `loadLearningStats()`, `fetchDailyPickForHero()`, `fetchJsonRetry` / hero timeout path, `connectCockpitStream()`, `scheduleCouncilHeroRetry()`, `dailyPickNeedsHeroRetry()`, `armHeroCriticalRelease()`. |
| `static/js/living_focus.js` | **Must coordinate.** `init`, `coldBootstrap`, `dailyPickPromise`, `refreshFocus` — gate network until hero cache/10s. |
| `static/js/home_live_refresh.js` | **Coordinate only if SSE still early.** `refreshHomeHotPath` / `bindCockpitTick` — no hero-window fetches. |
| `static/js/home_deferred.js` | **Optional.** Idle script load timeout 2500ms → after 10s hero gate so drawer scripts do not start extra APIs mid-window. |
| `harness/g0_hydration_starvation/run_g0.py` | **Do not relax HERO_BUDGET_S=10 or health 8s probe.** Optional **add** assertion: max concurrent `/api/*` in first 10s ≤ 3 (stats + daily-pick + at most one stray). |

`HERO_COMPLETE` (do not change): `window.SimiLearning.stats` parsed **and** hero DOM non-placeholder (`Awaiting subnet` / `data-verdict-kind=cold` gone). Timestamp = max(stats_parsed_at, hero_dom_ready_at). Budget 10s.

---

## AC (measurable; two prod G0 runs)

Harness: `python harness/g0_hydration_starvation/run_g0.py --base-url https://subnet-dashboard.fly.dev --run-id post-p2-<n> --out-dir artifacts/g0-baseline/post-p2-<n>`

Both `post-p2-1` and `post-p2-2` must show:

| Gate | Bar |
|------|-----|
| Hero complete | `hero_complete_at_s ≤ 10` (not NEVER) |
| Stats parsed | `stats_parsed_at_s ≤ 10` and a HAR **200 body** for `/api/learning/stats` |
| `/health` p95 during burst | **< 500 ms** (not harness 8s timeout) |
| First-10s `/api/*` in-flight | **≤ 3** |
| Timeout HOLD | If daily-pick is timeout HOLD: `_meta.stale === true` (not `status:"ok"` stored HOLD) |
| Duplicate hero-critical | First window: **one** stats request, **one** daily-pick request |

Not AC: sequential curl, local Playwright without prod contention, hero title at 36s, late stats retry at 49s.

---

## PHASES

**2a — minimal hero path (ship this first)**
- Dedup bootstrap vs `run()`.
- Hero window: only stats + daily-pick; 4s abort; no in-window retry; timeout HOLD is terminal + stale-shaped.
- Defer `connectCockpitStream` and `kickPriorityPanels`.
- Gate `living_focus` cold network.
- Prove on two prod G0 runs (hero + health p95 + in-flight ≤3).

**2b — defer non-hero (same PR if 2a is small; else follow-on commit)**
- After gate: queue remaining hydrates with max 2 concurrent (`kickPriorityPanels`, trail, pump, subnets, story-strip, then deferred warehouse).
- `home_deferred.js` idle after 10s.
- Do not start 2b-only work until 2a HAR shows stats 200 in budget. If 2a already meets AC, 2b is still required so post-10s burst does not immediately re-starve `/health`.

---

## RISKS / NON-GOALS

Will **not** fix:

- Fly shared-cpu / `INLINE_WORKER=1` topology (`fly.toml*` owner-gated).
- Hollow mindmap-summary (independent).
- Resolver / watchdog (`#1051` / `#1055`).
- On-loop Python in trail / story-strip / evidence / integrations **once those URLs are requested** — 2b queue reduces blast radius, does not offload GIL.
- Sequential daily-pick scoring hangs (P1 already removed 8s executor wait on GET).

Honesty: G0 already stated occupancy cuts on the request path do not by themselves guarantee `/health` p95 <500ms **under 28-way fan-out**. This LOCK’s claim is: **removing the 28-way fan-out** is what makes the health bar reachable. If the bar still fails at ≤3 in-flight, JS is done.

---

## ESCALATE_HIGH?

**no** for starting Composer 2a (fan-out is the remaining trigger; owner GO for this LOCK is implied by this task).

**yes after 2a+2b** if two prod G0 runs still have `/health` p95 ≥500ms **while** first-10s in-flight `/api/*` ≤3 — then the occupant is not client stagger. Do not patch scoring or `fly.toml` from Composer.

---

## TEST PLAN (Composer; not sequential curl)

1. Unit/js: `dailyPickNeedsHeroRetry` is false for timeout HOLD; `loadLearningStats` / `fetchDailyPickForHero` return the same in-flight promise; `bootstrapCouncilHeroHydrate` does not call fetch when `run` will.
2. Local: existing tests + a small fixture that `run()` with mocked fetch records URL order (stats + daily-pick first; SSE/panels after a gate).
3. **Prod proof (required):** two cold Playwright G0 runs after owner `fly.yml`. Cite `summary.json` + `requests.json` + `health_series.json` + HAR. Pass table in AC.
4. Explicitly **do not** cite sequential `curl /health` or `curl /api/learning/stats` as close evidence (G0 already showed those are cheap while the browser burst is not).

Rollback: hero-complete p95 worse than post-P1 NEVER/49s is unlikely; rollback if `/health` p95 during burst is worse than ~8s timeout cliff **or** stats still never parse.

---

## STATUS

`LOCK_PATH=cursor-agents-communication/g0-1058-phase2-lock.md`
`VERDICT=CONDITIONAL`
`NEXT=Composer 2a on cockpit_hydrate.js (+ living_focus gate); Luna AC/honesty after two prod G0 runs`
`#1058 stays OPEN` — this LOCK is not a close and not a merge approval.
