# Pick-handler occupancy — scope plan (2026-08-30)

Answers Ditto GO checklist ([#1136](https://github.com/cryptoreporthub/subnet-dashboard/pull/1136)) plus amendment **v3 (FINAL)**. **Plan only. No implementation in this PR.**

**Status: PLAN SUBMITTED — amendments v3 (FINAL) applied, awaiting Joshua review.**

Line numbers below are re-pinned against `origin/main` **`5a33fe6c`** (code files identical on this branch; see §8). Do not reuse `cfbe842a` ranges without a fresh `git show`.

## 1. Occupancy (definition + metric)

**Occupancy** = wall-clock from handler/tick entry to return, including every nested call that holds a Python thread or the GIL on the inline web+worker box.

Two sites. Do not collapse them:

| Site | Entry | Cap today | Metric (already exists unless noted) |
|------|--------|-----------|--------------------------------------|
| **GET** `/api/daily-pick` | `api_daily_pick` | `PICK_READ_TIMEOUT_SECONDS` default **0.5s** (env-overridable; prod value still needs `/proc` or env evidence) | middleware `dashboard_request path=/api/daily-pick duration_ms`; optional `DAILY_PICK_STAGE_TIMING=1` (`hydrate_get_*`) |
| **Tick** `daily-pick-scheduler` | `DailyPickScheduler._tick` | `DAILY_PICK_TICK_TIMEOUT_SECONDS` default **90** (do not bump) | add `duration_ms` on `last_tick` in an impl PR; tonight: soul/volume `written_at` − slot 00:15Z |

`/health` p95 during a hydrate burst is the **shared-runtime** blast-radius metric (same 1 vCPU), not a third pick handler.

Three timing envelopes on the tick (do not collapse):

1. **Pre-future** — APScheduler thread: `_load_capped_subnets` + `_market_context` (unbounded vs the 90s cap).
2. **In-future** — 1-thread `daily-pick-work`: `get_or_create_today_pick` → `select_daily_pick`.
3. **Post-timeout** — abandoned worker may still write JSON/HOLD **after** the 90s return (generation guard does not stop writes). See §3 (b1).

## 2. Baseline (tonight)

| Evidence | Value |
|----------|--------|
| 00:15Z tick | 90s timeout → HOLD persisted 00:17Z `scheduler_hold` |
| 00:39Z | directional-conflict HOLD (real decision, not timeout) — **engine can finish inside 90s** |
| G0-1 00:49Z | hero NEVER; UI **pick handler busy — retry shortly**; `/health` p95 **1245ms** / p100 8076ms; ~9 parallel `/api/daily-pick` |
| G0-2 00:54Z | same hero NEVER; then `/health` timeout + liveness 503; recovered 00:57Z no restart |
| Sequential GET (Cursor 00:30Z) | **184ms**, stored timeout HOLD — GET is fast when the box is idle |

So: GET is already off the scoring engine. The screenshot string is the **0.5s read-path timeout**, not `select_daily_pick` on GET. The 90s failure is the **background tick**. The timeout is **long-tail, not baseline**.

**RECURRENCE, NOT A ONE-OFF.** Same signature at 08-19 (tick timeout → HOLD, busy handler, alerts 422), 08-21 (HOLD busy-handler, tick timeout, endpoints OK — degradation inside handler), 08-25 (HOLD busy/retry, watchdog pending >48h); pump-alerts line degrading intermittently since 07-27. 08-29 ~03:00Z: scheduler wedge reverse-engineered — write timeouts leave tick-active flags set, preventing re-arm; regression traced to LivenessTracker migration **#1087** (merged 08-28 13:04Z). Tonight (00:15/00:17Z) is the latest instance.

Cuts in this plan explain: **08-19 / 08-21 / 08-25 handler-busy HOLDs + tonight’s GET busy + tick abandon**. They do **not** explain: alerts-line degradation, resolver freshness.

## 3. Root-cause map

### GET (hydrate) — `server.py` `api_daily_pick` (`3122-3194`)

Already P1: no `get_or_create_today_pick` / `select_daily_pick`. Dedicated 2-thread `"pick-read"` pool (`629-634`). Flow:

1. `_find_today(_load())` on `_PICK_READ_EXECUTOR`, wait ≤0.5s (`3139-3147`)
2. `_enrich_daily_pick_payload_lite` on the same pool, wait ≤0.5s (`3171-3186`) — names, brief, tribunal fields, web spotlight, judge scores, pump chip. **No live subnet scoring**, but still CPU/GIL. `_to_thread_timeout` (`661`) bounds the await; the executor callable may continue.
3. Timeout on the **read** wait → `_daily_pick_timeout_hold()` (`3096-3106`) reason `pick handler busy — retry shortly` (`status: timeout`, not a scheduler HOLD). Enrich timeout returns stored JSON, not the busy string (`3179-3186`).

**Blocks GET:** JSON `_load`, lite enrich, pick-read pool saturation, GIL vs 20+ other `/api/*` on `_DASHBOARD_EXECUTOR` (top-picks 8s, weighed 8s, hour, subnets). Client retries multiply `/api/daily-pick`.

Daily GET does **not** have hour-pick’s lock. `/api/top-pick/hour` uses `_HOUR_PICK_LOCK` (`648`, `3253-3283`) — cached or `"busy"`. Do not imply daily already has that pattern. TMC single-flight (`internal/indicators/tmc_singleflight.py`) is pre-warmed from `select_daily_pick` (`daily_pick.py:151-158`), not from GET.

Enforced: `tests/test_homepage_pick_read_only.py:36-92` (`_boom` if engine called); `tests/test_pick_scheduler.py:406-409` (GET must stay a read-only hydrate API).

### Tick — `internal/council/pick_scheduler.py` `_tick` (`270-375`)

**(a) Outside the 90s future** (scheduler / APScheduler thread — blocks re-arm):

1. `_load_capped_subnets()` (`276`, def `125`) → `server._get_subnets_with_source()` + cap 24
2. `_market_context()` (`277`, def `138`) → `_market_context_with_weights`

**(b) Inside the 90s 1-thread `daily-pick-work` pool** (`284-302`):

3. `get_or_create_today_pick` (`daily_pick_engine.py:184-327`) → on `scheduler_hold` or miss, `select_daily_pick` (`daily_pick.py:112+`: TMC pre-warm `151-158`, JSON score cache `163-228`, parallel `dpick-score` workers `216-221`)

On `FuturesTimeoutError`: bump `_work_generation` (`215`, `297-298`), log `worker abandoned`, `pool.shutdown(wait=False, cancel_futures=True)` (`302`) — same unjoined-pool motif as #1113; **do not bundle**. Then `write_scheduler_hold`. Retry `DAILY_PICK_RETRY_MINUTES` (15) (`369-372`). Test: `tests/test_pick_scheduler.py:350-393` (timeout retries even if a zombie wrote HOLD to disk).

**(b1) SIDE-EFFECT WINDOW (critical; was missing).** Abandoned worker is **not** cancelled. `get_or_create_today_pick` can still write `data/daily_picks.json` (`_save` at `241`, `284`) and prediction/HOLD records (`286-325` via `record_pick_prediction` / `record_hold_decision`) **before** the generation check at `_run_pick` (`288-290`) rejects the returned payload. Generation guard stops stale **result** propagation to the scheduler, not writes.

EPISTEMIC STATUS: **independent corroboration** — code-forward (source review) **and** symptom-reverse (reconstruction from 00:49 shared-runtime starvation). Not two readings of the same file.

**(b2) RANK 2 REVERSES CURRENT DESIGN (say so).** Today subnet+market load runs **outside** the 90s future on the APScheduler thread (`276-277` **before** `fut.result`). Rank 2 **deliberately** moves them inside so abandonment reclaims them and APScheduler can re-arm (wedge **#1087** — grounded: LivenessTracker migration merged 08-28 13:04Z). The impl Go must **not** “preserve” the current outside placement; the reversal is the fix. Moving the load inside does **not** reduce the work — it contains it. Occupancy **reduction** for the web tier is ranks **1** and (later) **3**; say so in the impl PR.

**(b3) ROOT LATENCY — NAMED NON-GOAL OF THIS PLAN.** No cut here asks **why** the 24-subnet scoring pass blows 90s. Cuts 1–4 / (e) contain the aftermath (abandonment, retry overlap, starvation, stale writes). They do not reduce or explain the tail. 00:39Z proves the engine **can** finish inside budget. If the tail degrades (TMC latency, subnet-count creep toward cap 24, ambient web-tier contention), the episode recurs on a longer cycle even with all cuts shipped. This plan measures and bounds. **Follow-up Go (separate) isolates the tail.**

Hour pick: separate job, untouched unless a later Go says so.

**(d) Persistence:** JSON + `fcntl` file-lock, **not SQLite** on the direct daily-pick path: `data/daily_picks.json` (`daily_pick_engine.py:28-49`, `158-181`), `data/pick_score_cache.json` (`pick_score_cache.py:40-46`, lock `101-108`, session `163-228`). Downstream `record_pick_prediction` / `record_hold_decision` were **not** traced as SQLite in this pass — no repo-wide “no SQLite” claim.

## 4. Ranked cuts (not a single pick)

| Rank | Option | What | Effort / risk | Hits tonight’s symptom? |
|------|--------|------|---------------|-------------------------|
| **1** | **(c)** GET single-flight + shed | One in-flight `_load`+lite enrich; extra hydrates get that result or last stored JSON. Borrow hour’s `_HOUR_PICK_LOCK` pattern **deliberately** (daily does not have it today). Stop retry storms (G0 ×9). | Low. Shape unchanged. | **GET busy string + /health during burst** |
| **2** | Tick: move subnet+market load **inside** the 90s pool | **Reverses** current outside-future placement (`276-277`). Containment vs APScheduler / #1087 re-arm — **not** less work. | Low. 90s cap unchanged. | Tick occupancy vs APScheduler; not GET |
| **3** | **(b)** inner deadlines in `select_daily_pick` | Time-box TMC/council/proxy so the tick returns a real HOLD/LONG inside 90s instead of abandon. | Medium. Scoring behavior. | 00:17Z 90s HOLD (**containment**, not root latency — see b3) |
| **4** | **(e)** generation-counter hardening | Pre-persistence check in `get_or_create_today_pick`: bail before `_save` / HOLD records if `_work_generation` is no longer current. | Low-Med. Engine write path. | Post-timeout stale writes **(b1)** |
| — | **(a)** | GET scoring already off-path. Tick already background. Remainder = rank 2. Do not re-litigate P1. | — | — |
| — | **(d)** JSON `fcntl` | Not SQLite. Optional later: reduce lock/write cost. Skip for first impl. | Skip | No |

**(e)** closes the **(b1)** window. If scope is tight, defer **(e)** to its own Go with a one-line why — **do not silently drop it**; it is the only cut that targets the post-timeout write race.

**Recommended first impl PR (after review Go):** rank 1 only. Rank 2 is a legal same-PR rider only if still tiny; otherwise its own PR. Rank 3 and (e) are later Gos. Not #1112/#1113.

Until runtime capture (§6 item 4) names the exhausted shared resource, **rank 1 is the only mergeable cut** (items 1–2 passing). Ranks 2 / 3 / (e) wait on that capture.

## 5. Constraints

- Response shape: stored LONG/HOLD (`published` / netuid / confidence) unchanged; timeout HOLD stays `status: timeout` + `_meta.stale` — never rewrite a scheduler HOLD into timeout.
- Hour pick untouched in the first impl PR (ok to **copy** its lock pattern onto daily GET).
- **90s stays. No deploy without Joshua. KILL=0.**
- #1112 / #1113 untouched. PR 1060 stays open fail-closed. #1058 stays closed (08-27 / #1071).
- **LINE-REF DRIFT WAS OPEN; THIS DOC RE-PINS IT** against `5a33fe6c` (§8). An **implementation** Go must `git show` against **then-current** HEAD again before citing these numbers. No older range (`cfbe842a` 265-297 / 312-369) is authoritative.

## 6. Validation (before any impl PR ships to prod)

No full G0 unless Joshua says so.

1. **GET occupancy:** `TestClient` + jammed `_DASHBOARD_EXECUTOR` (already `test_daily_pick_ignores_saturated_dashboard_executor`); add concurrent n=8 GET `/api/daily-pick` — one load, all 200, elapsed ≪ 0.5s × 8.
2. **Probe (local or one prod curl pair after deploy Go):** sequential GET `/api/daily-pick` duration_ms; `/health` p95 while n=10 parallel daily-pick. Compare to G0-1 p95 1245ms only as a *burst* check, not a close of PR 1060.
3. **Tick:** do not claim the 90s HOLD is fixed by rank 1. Rank 2/3/(e) get their own `duration_ms` on `last_tick` plus a **post-timeout side-effect audit** (no `_save` / HOLD records from an abandoned generation).
4. **RUNTIME CAPTURE** (open question: which shared resource is exhausted — capture from the affected generation or the next recurrence **before ranks 2/3/(e) ship**):
   - worker `/jobs` inventory: which jobs registered/fired at 00:15–00:17Z
   - Python thread stacks (`py-spy` / `faulthandler`) at timeout+5s and +60s: is the abandoned worker still alive? what is it holding?
   - scheduler logs: tick-active flags, re-arm, misfire events
   - file-lock state on `data/daily_picks.json` + `pick_score_cache.json` (`fcntl` holder) and soul_map liveness timestamps
   - process metrics (CPU/threads/FD) vs G0-1 `/health` p95 1245ms / p100 8076ms
   - Deliverable: capture artifact naming the exhausted resource (threads / GIL / network / lock / volume).
5. **ISOLATE MISFIRE GRACE:** `misfire_grace_time=180` (`internal/job_scheduler.py`; test asserts 180) can **absorb** catch-up backlog rather than fix occupancy. A validation run with backlog absorption **MUST NOT** be credited as occupancy improvement. State per run whether catch-up occurred; treat absorbed runs as **inconclusive**.
6. **GATE:** rank 1 may merge when items 1–2 pass. Ranks 2 / 3 / (e) do not ship until item 4 answers “which shared resource”.

## 7. Deliverable

This file + MC log. Implementation = separate Joshua Go after review.

## 8. Source verification (re-pin vs `origin/main` `5a33fe6c`)

Verified on this checkout. `git diff --stat origin/main --` of these code files is empty (main is two docs-only commits on `docs/GITHUB_TOOLING.md` ahead of branch base `04614d46`).

| Claim | HEAD pin (`5a33fe6c` / this tree) | vs old `cfbe842a` cite | Status |
|-------|-----------------------------------|------------------------|--------|
| `PICK_READ_TIMEOUT` default 0.5s, 2-thread `pick-read` | `server.py:629-634` | `623-634` | **Confirmed.** Env override still needs prod evidence. |
| `_to_thread_timeout` = `wait_for` around executor | `server.py:661` | `661-672` | **Confirmed.** Await is bounded; worker may continue. |
| GET is read-only; busy payload | `api_daily_pick` `3122-3194`; hold `3096-3106` | `3121-3178` / `3096-3106` | **Confirmed.** Enrich timeout path `3179-3186` returns stored JSON, not busy. |
| Hour single-flight | `_HOUR_PICK_LOCK` `648`, `3253-3283` | `3240-3283` | **Confirmed.** Daily GET has no equivalent. |
| Tick: load **before** 90s future | `_tick` `270-375`; load `276-277`; future `284-302` | `265-297` | **Same code, new numbers.** `_tick` now starts at **270**. |
| Generation + abandon | `_work_generation` `215`; bump `280-282`, `297-298`; `shutdown(wait=False)` `302`; re-arm `346-375` | `212-215` / `312-369` | **Confirmed.** Comment at `213-214` still overclaims (“cannot commit results”) vs (b1) writes. |
| Engine writes | `get_or_create_today_pick` `184-327`; `_save` `241`/`284`; prediction/HOLD `286-325` | `184-225, 250-284, 286-325` | **Confirmed.** |
| JSON + `fcntl`, not SQLite | `daily_picks.json` `28-49`; cache `pick_score_cache.py:40-46`, `101-108` | same regions | **Confirmed** on this path. Prediction-loop not SQLite-traced. |
| Scoring / TMC / cache | `daily_pick.py:112`, `151-158`, `163-228`, `216-221` | `148-221` / `162-221` | **Confirmed** as `151-221` on HEAD. |
| Tests | homepage `36-92`; scheduler timeout-retry `350-393`; GET coarse guard `406-409`; dashboard-exec `test_api_handler_timeouts.py:836` | `350-390`, `398-404` | **Confirmed**; GET guard is `406-409` not `398-404`. |
| `misfire_grace_time=180` | default `internal/job_scheduler.py:32`; applied `98,119`; `tests/test_job_scheduler.py:31-38` | (v3 Patch D) | **Confirmed.** |

**Not a conflict:** older 265-297 vs HEAD 270-302 are the same `_tick` body at a later HEAD. Implementation Go re-pins again; do not paste `cfbe842a` numbers into code comments.
