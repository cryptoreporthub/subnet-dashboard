# Pick-handler occupancy — scope plan (2026-08-30)

Answers Ditto GO checklist ([#1136](https://github.com/cryptoreporthub/subnet-dashboard/pull/1136)). **Plan only. No implementation in this PR.**

## 1. Occupancy (definition + metric)

**Occupancy** = wall-clock from handler/tick entry to return, including every nested call that holds a Python thread or the GIL on the inline web+worker box.

Two sites. Do not collapse them:

| Site | Entry | Cap today | Metric (already exists unless noted) |
|------|--------|-----------|--------------------------------------|
| **GET** `/api/daily-pick` | `api_daily_pick` | `PICK_READ_TIMEOUT_SECONDS` default **0.5s** | middleware `dashboard_request path=/api/daily-pick duration_ms`; optional `DAILY_PICK_STAGE_TIMING=1` (`hydrate_get_*`) |
| **Tick** `daily-pick-scheduler` | `DailyPickScheduler._tick` | `DAILY_PICK_TICK_TIMEOUT_SECONDS` default **90** (do not bump) | add `duration_ms` on `last_tick` in an impl PR; tonight: soul/volume `written_at` − slot 00:15Z |

`/health` p95 during a hydrate burst is the **shared-runtime** blast-radius metric (same 1 vCPU), not a third pick handler.

## 2. Baseline (tonight)

| Evidence | Value |
|----------|--------|
| 00:15Z tick | 90s timeout → HOLD persisted 00:17Z `scheduler_hold` |
| 00:39Z | directional-conflict HOLD (real decision, not timeout) |
| G0-1 00:49Z | hero NEVER; UI **pick handler busy — retry shortly**; `/health` p95 **1245ms** / p100 8076ms; ~9 parallel `/api/daily-pick` |
| G0-2 00:54Z | same hero NEVER; then `/health` timeout + liveness 503; recovered 00:57Z no restart |
| Sequential GET (Cursor 00:30Z) | **184ms**, stored timeout HOLD — GET is fast when the box is idle |

So: GET is already off the scoring engine. The screenshot string is the **0.5s read-path timeout**, not `select_daily_pick` on GET. The 90s failure is the **background tick**.

## 3. Root-cause map

### GET (hydrate) — `server.py` `api_daily_pick`

Already P1: no `get_or_create_today_pick` / `select_daily_pick`. Flow:

1. `_find_today(_load())` on `_PICK_READ_EXECUTOR` (2 threads), wait ≤0.5s  
2. `_enrich_daily_pick_payload_lite` on the same pool, wait ≤0.5s — names, brief, tribunal fields, web spotlight, judge scores, pump chip. **No live subnet scoring**, but still CPU/GIL.  
3. Timeout → `_daily_pick_timeout_hold()` reason `pick handler busy — retry shortly` (`status: timeout`, not a scheduler HOLD).

**Blocks GET:** JSON `_load`, lite enrich, pick-read pool saturation, GIL vs 20+ other `/api/*` on `_DASHBOARD_EXECUTOR` (top-picks 8s, weighed 8s, hour, subnets). Client retries multiply `/api/daily-pick`.

### Tick — `internal/council/pick_scheduler.py` `_tick`

**Outside** the 90s future (scheduler thread, blocks APScheduler):

1. `_load_capped_subnets()` → `server._get_subnets_with_source()` + cap 24  
2. `_market_context()` → `_market_context_with_weights`

**Inside** the 90s 1-thread `daily-pick-work` pool:

3. `get_or_create_today_pick` → on `scheduler_hold` or miss, `select_daily_pick` (council + TMC pre-warm + telegram conviction rows)

On `FuturesTimeoutError`: abandon worker (`shutdown(wait=False)` — same unjoined-pool motif as #1113; **do not bundle**), `write_scheduler_hold`. Retry `DAILY_PICK_RETRY_MINUTES` (15).

Hour pick: separate job, untouched unless a later Go says so.

**(d) SQLite:** this path is JSON `_load/_save`, not SQLite. Drop from the cut.

## 4. Ranked cuts (not a single pick)

| Rank | Option | What | Effort / risk | Hits tonight’s symptom? |
|------|--------|------|---------------|-------------------------|
| **1** | **(c)** GET single-flight + shed | One in-flight `_load`+lite enrich; extra hydrates get that result or last stored JSON. Stop retry storms (G0 ×9). | Low. Shape unchanged. | **GET busy string + /health during burst** |
| **2** | Tick: move subnet+market load **inside** the 90s pool | `_load_capped_subnets` + `_market_context` currently run *before* `fut.result(timeout=90)`. | Low. 90s cap unchanged. | Tick occupancy vs APScheduler; not GET |
| **3** | **(b)** inner deadlines in `select_daily_pick` | Time-box TMC/council/proxy so the tick returns a real HOLD/LONG inside 90s instead of abandon. | Medium. Scoring behavior. | 00:17Z 90s HOLD |
| **4** | **(a)** | GET scoring already off-path. Tick already background. Remainder = rank 2. Do not re-litigate P1. | — | — |
| — | **(d)** SQLite | Not on this path. | Skip | No |

**Recommended first impl PR (after review Go):** rank 1 only. Rank 2 is a legal same-PR rider only if still tiny; otherwise its own PR. Rank 3 is a later Go. Not #1112/#1113.

## 5. Constraints

- Response shape: stored LONG/HOLD (`published` / netuid / confidence) unchanged; timeout HOLD stays `status: timeout` + `_meta.stale` — never rewrite a scheduler HOLD into timeout.  
- Hour pick untouched in the first impl PR.  
- **90s stays. No deploy without Joshua. KILL=0.**  
- #1112 / #1113 untouched. PR 1060 stays open fail-closed. #1058 stays closed (08-27 / #1071).

## 6. Validation (before any impl PR ships to prod)

No full G0 unless Joshua says so.

1. **GET occupancy:** `TestClient` + jammed `_DASHBOARD_EXECUTOR` (already `test_daily_pick_ignores_saturated_dashboard_executor`); add concurrent n=8 GET `/api/daily-pick` — one load, all 200, elapsed ≪ 0.5s × 8.  
2. **Probe (local or one prod curl pair after deploy Go):** sequential GET `/api/daily-pick` duration_ms; `/health` p95 while n=10 parallel daily-pick. Compare to G0-1 p95 1245ms only as a *burst* check, not a close of 1060.  
3. **Tick:** do not claim the 90s HOLD is fixed by rank 1. Rank 2/3 get their own duration_ms on `last_tick`.

## 7. Deliverable

This file + MC log. Implementation = separate Joshua Go after review.
