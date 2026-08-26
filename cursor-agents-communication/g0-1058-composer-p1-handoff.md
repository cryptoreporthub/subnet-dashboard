# Composer P1 handoff — #1058 after G0 PASS

Grok (investigation) → **you implement** → Luna reviews. Do not skip Luna.

**Branch:** `fix/hydration-starvation-p0` (from `bb84de10`)  
**G0:** PASS — two prod Playwright runs agree. Report: `artifacts/g0-baseline/G0_REPORT.md`  
**Scope:** P0/P1 partial mitigation only. Phase 2 JS stagger is **not** acceptance. No deploy from this branch.

---

## Shared root cause (do not re-litigate unless evidence changes)

**One cause:** request-path occupancy on the single shared-cpu web+inline-worker process.

Daily-pick 8s timeout HOLD, hero-critical aborts, and `/health` death during burst are the **same occupancy at increasing blast radius**. Bundle the P1 occupancy cuts. Split infra (`fly.toml`), Phase 2 hydrate JS, resolver/grading, `#1010`/`#1019`.

Do **not** “fix” host pressure inside `select_daily_pick` / scoring loops.

---

## What G0 proved (implement against this, not folklore)

1. Browser cold load of https://subnet-dashboard.fly.dev: hero stays `Awaiting subnet` / `COLD` for 50s. `/api/learning/stats` never parsed. `/api/daily-pick` aborted/retried.
2. `/health` is fine (~100–230ms) until ~t=3.2s fan-out, then **unreachable** (harness 8s timeouts). `/health` is async and load-shed bypassed → event loop / vCPU starved.
3. Sequential `GET /api/daily-pick` still takes **8.30s** and returns:

```json
{"status":"timeout","action":"HOLD","reason":"pick handler busy — retry shortly","pick":null,"_meta":{"generated_at":null,"data_source":"local","stale":true}}
```

4. Current GET handler already skips the pick engine (`server.py` `api_daily_pick` → `_find_today(_load())` + lite enrich, 8s `_to_thread_timeout` on `_DASHBOARD_EXECUTOR`). The 8s is **executor occupancy / queued `_build`**, not “we forgot to stop scoring on GET.”
5. Worker proxy is **not** implicated (`_meta.data_source: local`; `WORKER_SPLIT_V2=off`).
6. Local boot: same 25-way burst, `/health` p95 **1.4ms**, hero-critical 200s. Local placeholder ≠ prod starvation.

---

## P1 implementation (exact)

### A. Homepage SSR pick — rebase `#1018` Python hunks only

Unmerged PR: https://github.com/cryptoreporthub/subnet-dashboard/pull/1018

**Take these hunks** (re-apply on current `server.py` / `dashboard_context.py`; line numbers will shift):

1. `internal/learning/dashboard_context.py` `_pick_sections`  
   Replace `get_or_create_today_pick(...)` with `_find_today(_load())`. Never score/write on this path.

2. `server.py` `_home_hero_context`  
   Replace `get_or_create_today_pick` + `_enrich_daily_pick_payload` with `_read_shell_daily_pick()`. Empty → `{}`. Keep tribunal/story_path on the stored payload.

3. Add `tests/test_homepage_pick_read_only.py` from that PR (three tests: hero context, pick sections, homepage warm must not call `get_or_create_today_pick`).

**Do not take:** `fly.toml` `timeout = "12s"`; `test_fly_toml_v1_health_check_timeout_12s`. Forbidden file: `fly.toml*`.

`#1051` / `#1055` are already on main and do **not** change this read path. No rebase accounting needed beyond “current `_home_hero_context` still scores.”

Warm GET `/` already uses `_minimal_index_context` → `_fast_home_hero_context` (file read). `_home_hero_context` / `_pick_sections` are still live scoring callers (`_degraded_index_context` → `_shell_pump_and_picks(include_picks=True)` → `_pick_sections`). Fix them anyway.

### B. Bound `GET /api/daily-pick` (the 8s sequential timeout)

File: `server.py` `api_daily_pick` (and only helpers it already uses).

Required behavior:

1. **Cached-today hit:** if `_find_today(_load())` (or a process cache of that JSON) exists, return lite payload **immediately**. Must not sit behind a saturated `_DASHBOARD_EXECUTOR` for 8s. If you keep the executor, fail the wait in well under the hero budget (hundreds of ms, not `PICK_HANDLER_TIMEOUT`).
2. **Miss:** return degraded **within budget** (`status` pending/timeout, `action:"HOLD"`, `_meta.stale:true`). Never wait inline on full-universe scoring. Engine already has this miss branch — the bug is the **timeout wait**, not a missing pending payload.
3. **Timeout must not look like a clean HOLD.** Shape already exists (`status:"timeout"`, `action:"HOLD"`, `_meta.stale:true`). Keep it. Sequential prod already has `stale:true` — good. It must become **fast** even while a background tick scores.
4. **Legitimate directional-conflict HOLD** (stored JSON `action:"HOLD"` with candidate/reason from the scheduler) ≠ timeout HOLD. Do not rewrite stored HOLDs into `status:"timeout"`.
5. Optional one-liner stage timing on this **fast** path (env `DAILY_PICK_STAGE_TIMING` if you add a tiny helper). Do **not** merge `#1010` / `#1019`.

Likely smallest fix: serve the file/cache read without `run_in_executor` (or with a dedicated 1-thread “pick-read” pool and a short `wait_for`), and never call `_enrich_daily_pick_payload` (full) or `get_or_create_today_pick` here. Lite enrich must stay cheap; if spotlight/weighing work can block, skip it on the hydrate GET (weighed stays on `/api/daily-pick/weighed`).

### C. Tests (extend, don’t invent a framework)

`tests/test_api_handler_timeouts.py`

- Timeout payload never persists a **fresh-shaped** HOLD: if `status=="timeout"` then `_meta.stale is True` (and/or explicit degraded marker). Must not look like a scheduler HOLD with `status` ok/missing.
- Cached-today hit returns within a tight budget **without** calling `get_or_create_today_pick` / `select_daily_pick`.
- Saturated executor: monkeypatch `_DASHBOARD_EXECUTOR` to block; GET `/api/daily-pick` still returns degraded/cached fast; `/health` stays fast (reuse `test_prod_stability` pattern).

`tests/test_prod_stability.py`

- Homepage / daily-pick read path does not block `/health` when `get_or_create_today_pick` is slow (patch the engine to `Event.wait`).
- After `#1018` hunks: `_home_hero_context` / `_pick_sections` must not call the engine.

Keep `tests/test_subnet_feed_timeout.py` invariants (`test_daily_pick_read_path_skips_live_feed`, miss → `pending`).

### D. Forbidden in the diff

- `fly.toml*` `Dockerfile`
- `internal/council/resolver.py` decision logic, grading modules, `internal/liveness.py`
- `static/js/cockpit_hydrate.js` (Phase 2)
- `internal/worker_proxy.py` (not implicated)
- `internal/cockpit/picks_snapshot.py` unless you have new evidence
- Resolver lifecycle, council decision math, Telegram listener

---

## Acceptance (P1, not close-the-issue)

After your tests pass locally:

- Timeout HOLD is always `stale`/`timeout`-shaped and **fast**.
- Cached-today GET does not invoke the scoring engine.
- Homepage SSR/warm does not call `get_or_create_today_pick`.

**Close #1058 only after** owner deploy + this harness twice on prod: hero ≤10s **and** `/health` p95 <500ms during burst. If local/CI pass but post-deploy browser audit fails → rework, do not close.

Rollback: hero-complete p95 worse than G0, or `/health` p95 during burst still ≥500ms → revert via the same `workflow_dispatch` path.

---

## What not to touch / not to merge wholesale

- `#1018` fly.toml health timeout
- `#1010` tick I/O cache + nested `record_hold_decision` timing
- `#1019` 60s misfire grace
- `#1051`/`#1055` (already merged; resolver)

---

## Re-run harness (you or Luna, post-deploy only)

```bash
source .venv/bin/activate
python harness/g0_hydration_starvation/run_g0.py \
  --base-url https://subnet-dashboard.fly.dev \
  --run-id post-p1-prod-1 \
  --out-dir artifacts/g0-baseline/post-p1-prod-1
```

Playwright is venv-only (`pip install playwright && python -m playwright install chromium`). Not in `requirements.txt`.
