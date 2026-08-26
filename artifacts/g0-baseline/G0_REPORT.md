# Gate G0 report — issue #1058 homepage hydration starvation

**Verdict: PASS** (starvation reproduced on two independent prod runs; they agree; no tie-break needed)

**Date:** 2026-08-26  
**Base:** `main` @ `bb84de1094043badd806a0aa48525314190479c2`  
**Branch:** `fix/hydration-starvation-p0`  
**Live:** https://subnet-dashboard.fly.dev  
**Harness:** Playwright Chromium, `harness/g0_hydration_starvation/run_g0.py`  
**Local run:** instrumentation sanity only — do not cite for/against host contention

---

## 1. Gate verdict

| Item | Result |
|------|--------|
| Prod-1 starvation shape | **YES** — hero never completed; hero-critical `/api/learning/stats` + `/api/daily-pick` abort/hang >45s |
| Prod-2 starvation shape | **YES** — same shape |
| Tie-break | Not needed (2/2 agree) |
| Intermittent? | No — deterministic on these two cold browser loads |
| Phantom incident? | No |
| G0 | **PASS** |

Hero never left `Awaiting subnet` / `COLD` / graded `0` after 50s. `/api/learning/stats` was never parsed in either prod run.

---

## 2. Baseline table

### prod-1 (`2026-08-26T17:53:27Z`)

| Metric | Value |
|--------|-------|
| Hero complete time | **NEVER** (budget ≤ 10s) |
| stats parsed at | never |
| hero DOM ready at | never |
| Final title / verdict / graded | `Awaiting subnet` / `cold` / `0` |
| Aborted/hung endpoints | 24 paths including `/api/daily-pick`, `/api/learning/stats`, `/api/subnets`, `/api/pump-alerts`, `/api/simivision`, mindmap, letters, judges, watchlist, SSE |
| Aborted hero-critical | `/api/daily-pick` (×4), `/api/learning/stats` (×2) |
| `/health` n / ok | 14 / 8 |
| `/health` p50 / p95 / p100 | 937 / **8039** / 8041 ms |
| `/health` p95 over 500ms | **YES** |
| Max concurrent in-flight (all / api) | 47 / 28 |
| Pending API at t=45s | `/api/cockpit/stream`, `/api/daily-pick`, `/api/learning/stats`, `/api/subnets`, `/api/pump-alerts`, letters, watchlist, story-strip, ops/readiness, portfolio, message-intel |
| API request count | 42 |
| Homepage nav TTFB (browser) | 136 ms (`responseStart`) |
| Homepage curl TTFB after burst | 20s timeout (sanity only, not a gate) |

Health series: first ~1.4s of probes are 96–224ms OK (one 1247ms spike). From ~t=3.4s (hydration fan-out) every subsequent `/health` hits the harness 8s client timeout until the run ends.

`/api/learning/stats` started at 3.276s, client-aborted at 31.274s (`net::ERR_ABORTED`, 28000ms = hydrate timeout), retry still open at close.

### prod-2 (`2026-08-26T17:55:35Z`)

| Metric | Value |
|--------|-------|
| Hero complete time | **NEVER** |
| stats parsed at | never |
| hero DOM ready at | never |
| Final title / verdict / graded | `Awaiting subnet` / `cold` / `0` |
| Aborted/hung endpoints | same family as prod-1 (25 paths) |
| Aborted hero-critical | `/api/daily-pick` (×4), `/api/learning/stats` (×2) |
| `/health` n / ok | 15 / 9 |
| `/health` p50 / p95 / p100 | 559 / **8038** / 8039 ms |
| `/health` p95 over 500ms | **YES** |
| Max concurrent in-flight (all / api) | 46 / 28 |
| Pending API at t=45s | same pattern (stream + daily-pick + stats + subnets + pump + …) |
| API request count | 42 |
| Homepage nav TTFB (browser) | 180 ms |

Same health cliff: OK until fan-out, then 8s `/health` timeouts.

### Sequential curl (after prod-2, not a G0 gate)

| Endpoint | Result |
|----------|--------|
| `GET /health` | 135 ms, 200 |
| `GET /` | 105 ms TTFB, 200, 134 KB |
| `GET /api/learning/stats` | 319 ms, 200 |
| `GET /api/daily-pick` | **8.30 s**, 200, `status:"timeout"`, `action:"HOLD"`, `reason:"pick handler busy — retry shortly"`, `_meta.stale:true` |

Confirms the original incident: sequential curls work for stats/homepage/health; daily-pick still burns the full `PICK_HANDLER_TIMEOUT` (8s) even alone.

### local-sanity (NOT contention evidence)

| Metric | Value |
|--------|-------|
| stats parsed at | **2.335 s** |
| hero DOM ready | never (`Awaiting subnet`, verdict `forming`) — empty stored pick, not abort |
| Hero-critical abort | **none** (`/api/daily-pick` 200 in 1.17s; `/api/learning/stats` 200) |
| `/health` p50 / p95 / p100 | 1.14 / **1.39** / 1060 ms |
| `/health` p95 over 500ms | **NO** |
| Pending at 45s | `/api/cockpit/stream` only (SSE left open) |
| Homepage curl TTFB | 1.5 ms, 200 |

Harness `starvation_shape=true` locally is a **false positive**: placeholder title because there is no today's pick on the local volume, plus SSE still open. Hero-critical fetches completed. `/health` stayed fast under the same 25-way API burst. **Do not cite local as proof the prod fix works.**

---

## 3. Root-cause hypothesis

**Shared-runtime occupancy on the single shared-cpu web+inline-worker process, triggered by the hydration burst, with daily-pick GET as a proven 8s occupant.**

Not isolated handler-local (other routes stay healthy while only daily-pick is slow). Not isolated host pressure independent of the request storm ( `/health` is 100–230ms until the burst, then becomes unreachable).

Evidence:

1. `GET /health` is `async` `PlainTextResponse("OK")` and is load-shed **bypassed**. If it 8s-timeouts, the event loop or the Firecracker vCPU is not running the coroutine. That is shared-runtime, not a daily-pick-only queue.
2. The health cliff lines up with fan-out (~t=3.2s, max 28 in-flight `/api/*`).
3. Sequential `/api/daily-pick` still takes 8.30s and returns timeout HOLD — `PICK_HANDLER_TIMEOUT_SECONDS=8`. Occupancy exists without a browser storm; the storm amplifies it until `/health` dies.
4. Current `GET /api/daily-pick` already claims “never run pick engine on hydrate” (`_find_today(_load())` + lite enrich). The 8s timeout means `_build` is stuck on the 4-thread `_DASHBOARD_EXECUTOR` (queue or lite-enrich/IO), not `select_daily_pick` on that handler.
5. `fly.toml` is v1: `web=1`, `INLINE_WORKER=1`, `WORKER_SPLIT_V2=off`, `timeout = "5s"` on `/health`. Sequential `_meta.data_source: "local"` — worker proxy is **not** the path here. Do not treat this as a split_v2 proxy bug.
6. Load-shed cap is 48; we hit 47 in-flight. `/api/learning/stats` is a light bypass and still aborted at 28s. Shed is not the primary explanation.
7. `#1018` homepage read-only hunks are **not on main**. `_home_hero_context` still calls `get_or_create_today_pick`; `_pick_sections` still does too. GET `/` warm path uses `_minimal_index_context` / `_fast_home_hero_context` (file read) so HTML TTFB stays ~150ms — SSR is not what starved these two runs. Those scoring callers remain landmines on degraded/full-build paths.

**Host-level branch:** `/health` p95 during burst **crosses 500ms** → classify as shared-runtime. Do **not** code around host pressure inside `select_daily_pick` / scoring loops. P1 occupancy cuts on the **request path** (fast JSON read, stop SSR scoring callers) are still the right first slice. They will not, by themselves, guarantee `/health` p95 <500ms under a 28-way fan-out. Phase 2 (client stagger) remains follow-on. Infra (shared-cpu size / topology) stays owner-gated; no `fly.toml*` in this diff.

---

## 4. Shared root cause vs independently convergent

**Single root cause, increasing blast radius — bundle P1 occupancy cuts; split everything else.**

| Symptom | Same cause? |
|---------|-------------|
| Hero never hydrates (stats + daily-pick abort) | Yes — burst occupancy |
| `/health` dies during burst | Yes — same occupancy starving the event loop/vCPU |
| Sequential daily-pick 8s timeout HOLD | Yes — same occupancy on the dashboard executor, visible without fan-out |
| Placeholder SSR HTML (Awaiting subnet) | Convergent **display** of failed hydrate; HTML itself is fast |
| Hollow mindmap-summary | **Independent** (separate issue) — do not bundle |
| `#1051` / `#1055` resolver/watchdog | **Independent** — actual diffs are resolver honesty, not homepage hydration |
| `#1010` stage timing / `#1019` misfire grace | **Independent** unmerged scoring-tick work; `#1019` explicitly does not fix the scoring hang |

Bundle in P1: homepage SSR pick read-only (`#1018` Python hunks only) + bound `GET /api/daily-pick` so cached/degraded returns without an 8s executor wait.

Do **not** bundle: `fly.toml` health-check timeout (`#1018` infra hunk), Phase 2 JS stagger, resolver/grading, worker-proxy (not implicated), `picks_snapshot.py` (SSE hang is expected for an open stream).

---

## 5. GO / NO-GO for Composer P1

**GO for P1 as a partial occupancy cut**, with owner rollback criteria. **Not a close of #1058** unless a post-deploy browser audit shows hero ≤10s **and** `/health` p95 <500ms during the same burst.

P1 must **not** patch scoring inside `daily_pick_engine.get_or_create_today_pick` / `select_daily_pick` to “work around” host CPU.

Exact plan: `cursor-agents-communication/g0-1058-composer-p1-handoff.md`

---

## 6. Files changed since last gate (harness/docs/artifacts only)

No product code.

- `harness/g0_hydration_starvation/run_g0.py`
- `harness/g0_hydration_starvation/README.md`
- `artifacts/g0-baseline/**`
- `cursor-agents-communication/g0-1058-composer-p1-handoff.md`
- this report

---

## 7. Next action requested of the owner

1. Review G0 evidence (two prod HARs + screenshots).
2. **Owner GO** for Composer P1 on `fix/hydration-starvation-p0` (or a follow-on implementation commit on the same branch).
3. After P1 CI green: owner-only `workflow_dispatch` of `.github/workflows/fly.yml`. **No deploy from the task agent.**
4. Post-deploy: re-run this harness twice. Rollback if hero-complete p95 is worse than this baseline or `/health` p95 during burst is still ≥500ms.
5. Phase 2 (hydrate stagger) stays follow-on; `#1029`/`#1032` stay blocked until burst verification.

---

## Research notes (`#1018` / `#1051` / `#1055`)

| PR | On main? | Use in P1 |
|----|----------|-----------|
| [#1018](https://github.com/cryptoreporthub/subnet-dashboard/pull/1018) | **No** | Rebase **Python + test** hunks only: `_home_hero_context` → `_read_shell_daily_pick`; `_pick_sections` → `_find_today(_load())`; add `tests/test_homepage_pick_read_only.py`. **Do not** take `fly.toml` `timeout = "12s"` or `test_fly_toml_v1_health_check_timeout_12s`. |
| [#1051](https://github.com/cryptoreporthub/subnet-dashboard/pull/1051) | Yes | Resolver scheduler honesty. **Does not** change homepage hydration/read-path. Ignore for this rebase. |
| [#1055](https://github.com/cryptoreporthub/subnet-dashboard/pull/1055) | Yes | Shadow-row expire / watchdog scope. **Does not** change homepage hydration. Ignore. |
| [#1010](https://github.com/cryptoreporthub/subnet-dashboard/pull/1010) | **No** | `DAILY_PICK_STAGE_TIMING` not on main. Do not merge wholesale. Optional: one log line on the **fast** daily-pick GET path. |
| [#1019](https://github.com/cryptoreporthub/subnet-dashboard/pull/1019) | **No** | Misfire grace. Explicitly does not fix scoring hang. Do not merge. |
