# Thread / abandon leak diagnosis (plan only)

**Status:** Diagnosis + fix plan — **no product code changes in this PR.**  
**Repo:** `cryptoreporthub/subnet-dashboard`  
**Prod context:** Fly 1GB VM, web (Uvicorn) + inline or dedicated worker (`RUN_MODE=worker`).  
**Related:** #1552 (orphaned resolver vs revived scheduler overlap), #1558 / PR #1538 (`MALLOC_ARENA_MAX=2` RSS containment — does **not** stop thread accumulation from abandoned work).

---

## 1. Executive summary

Production captures show the **worker** holding ~21–26 threads at boot and ~**22–24 steady** (flat in recent operator windows), while **web** reports ~8 threads at boot. `MALLOC_ARENA_MAX=2` cut worker RSS (~500 → ~285 MiB) by shrinking glibc arenas; **that does not prove or disprove thread accumulation from abandon paths.**

**Hypothesis (unproven in prod):** the main growth mechanism is **not** forgotten daemon tick threads (those are bounded and named) but **ephemeral `ThreadPoolExecutor` instances** per resolver cycle, daily-pick tick, desk snapshot, etc., plus **`future.result(timeout=…)` + `pool.shutdown(wait=False, cancel_futures=True)`**. That pattern returns on timeout without joining the worker; `cancel_futures` only drops **queued** work, not a thread already running Python. **Ordinary scheduled retries on the same scheduler instance do not overlap** a prior abandon — resolver and daily pick refuse a new submit while `_inflight_future` is unfinished (`resolver_scheduler.py:806–811`, `pick_scheduler.py:359–362`). **Overlap (second concurrent pool worker)** arises mainly from **revive / recycle (#1552)** — new scheduler generation or replacement while the prior cycle’s orphan still runs — plus **score-snapshot global write** overlap. Desk snapshot abandons hold **`_cycle_lock`** until the orphan’s worker `finally`; the next tick **skips** rather than starting a second pool worker on the same scheduler.

**Proof / disproof (two legs — no “quiet days” gate):**

1. **Deliberate staging episode** (same calendar day as morning-pick observability — does **not** delay or replace prod morning pick): on a **staging worker only**, force short cycle budgets (e.g. `RESOLVER_CYCLE_TIMEOUT_SECONDS=1`, desk/pick timeouts similarly tight) and run a bounded burst of resolver + pick + desk ticks. **Judge:** compare **`submitted`**, **`abandoned`**, and **`orphan_completed`** counters plus **`oldest_live_orphan_age_seconds`** peaks from the sampler. Accumulation ⇒ **`live`** or oldest age **trends up** while completions lag abandons; drain-only ⇒ abandons spike but **`live` returns to 0** and oldest age **falls** after the burst. This answers the Ditto “is abandon accumulating?” baseline **without** waiting for passive prod quiet time.

2. **Multi-day prod trend** (sampler **30s** resolution — not every transient blip): over **≥3 production days**, **`max(live)`** and **named heavy-prefix peaks** from the sampler must show a **rising trend** (or sustained **`live ≥ 2`** with **rising oldest age**) to **support** accumulation. A flat **`max(live)`** band means **no detected accumulation** at sampler cadence — **not** a proof that zero orphans ever existed between samples. RSS remains separate.

**First approved step:** **logging only** — no scheduler/executor **behavior** changes (timeouts, shutdown, revive). Phase 0 **does** add **+1 daemon sampler thread** and modest log volume; it does **not** change abandon/shutdown semantics. **May ship the same deploy day** as morning-pick work (#1561): logging PR is independent; staging episode is staging-only and runs **after** Phase 0 lands, **without** blocking the prod morning pick path.

---

## 2. Process model (what runs where)

| Process | How it starts | Background schedulers | Typical boot threads (observed / inferred) |
|--------|----------------|----------------------|---------------------------------------------|
| **Web** | `fly_web_entrypoint.sh` → Uvicorn `server:app` | Only if `BACKGROUND_ON_WEB` ≠ `off` (prod `fly.toml`: **off**; schedulers on inline worker) | ~**8** at boot (operator capture) — **INFERRED** from lifespan boot threads + asyncio default pool + module-level executors |
| **Inline worker** | Same VM: `python -m internal.worker` (`ENABLE_INLINE_WORKER=1`) | `start_background_workers()` — resolver, picks, pump, score snapshot producer, MI bots, etc. | ~**21–26** boot, ~**22–24** steady (operator capture) |
| **Dedicated worker** | `RUN_MODE=worker` (split v2 / worker entrypoint) | Same as inline worker | Same order of magnitude as inline worker |

Shared infrastructure in **both** web and worker when that process imports `server` or runs worker boot:

- `internal/job_scheduler.py` — `BackgroundScheduler(daemon=True)` (+ APScheduler internal thread pool). **VERIFIED**
- `internal/process_memory.start_rss_heartbeat()` — daemon `rss-heartbeat` when not pytest/CI. **VERIFIED**

---

## 3. Inventory — thread and executor start sites

Legend: **W** = web-only or web-primary, **K** = worker / `start_background_workers`, **B** = both (import-time or either mode).  
**Abandon risk:** HIGH = per-job executor + timeout without join; MED = long-lived pool + timeout; LOW = daemon loop / one-shot.

### 3.1 Module-lifetime pools (created at import / lifespan)

| Location | W/K/B | max_workers | Abandon risk | Notes |
|---------|-------|-------------|--------------|-------|
| `server.py:567–573` `_DASHBOARD_EXECUTOR` | W | `DASHBOARD_WORKER_POOL_SIZE` (default 4) | MED | `atexit` → `shutdown(wait=False, cancel_futures=True)`. Timed-out `run_in_executor` work keeps running. **VERIFIED** |
| `server.py:670–674` `_PICK_READ_EXECUTOR` | W | 2 | MED | Same atexit pattern. **VERIFIED** |
| `server.py:400–403` asyncio default executor `aio-web` | W | `AIO_WORKER_POOL_SIZE` (default 4) | MED | Lifespan shutdown `wait=False`. **VERIFIED** |
| `internal/request_executor.py:27–28` `REQUEST_EXECUTOR` | B | env-sized | MED | Shared API offload pool. **VERIFIED** |
| `internal/ops/readiness.py:18+` `_SECTION_EXECUTOR` | W | bounded | MED | Readiness section builds. **VERIFIED** |
| `internal/council/score_snapshots.py:1247–1250` `_write_executor` | K | 1 global `score-snap-write` | **HIGH** | Reused across writes; caller timeout **abandons wait**, build continues. **VERIFIED** |

### 3.2 Lifespan / boot daemon threads

| File:line | Name / role | W/K | Join on stop? | Abandon risk |
|-----------|-------------|-----|---------------|--------------|
| `server.py:345–364` | `emergency-prime`, `homepage-warm-boot`, `registry-name-sync`, `council-weight-rebalance` | W | No (daemon) | LOW — fire-and-forget boot. **VERIFIED** |
| `server.py:377–380` | `cache-coverage-audit` | W | No | LOW. **VERIFIED** |
| `server.py:307` | `worker-heartbeat` (when worker lifespan path) | K | No | LOW. **VERIFIED** |
| `internal/worker.py:84` | `job-inventory-http` (`ThreadingHTTPServer`) | K | No | LOW (+ per-request threads). **VERIFIED** |
| `internal/worker.py:151` | `worker-heartbeat` | K | No | LOW. **VERIFIED** |
| `internal/background_boot.py:56` | `defer_boot(*)` — one thread per deferred scheduler | K | No | LOW per thread; **many** distinct names. **VERIFIED** |
| `internal/background_boot.py:179` | `pump-lead-recover` | K | No | LOW. **VERIFIED** |
| `internal/background_boot.py:415` | `telegram-summary-bot-watchdog` | K | No | LOW. **VERIFIED** |
| `internal/worker_proxy.py:740–742` | `worker-base-discover`, `worker-base-boot` | W | No | LOW (web proxy to worker volume). **VERIFIED** |
| `internal/process_memory.py:244` | `rss-heartbeat` | B | No | LOW; logs `threads=` via `log_memory_snapshot`. **VERIFIED** |
| `internal/loop_stall_guard.py:569` | `loop-stall-guard` | K | No | LOW; triggers **revive** (overlap risk). **VERIFIED** |
| `internal/ops/readiness_cache.py:263,330` | warm + refresher | W | No | LOW. **VERIFIED** |

### 3.3 APScheduler-backed jobs (`schedule_in_seconds` / `schedule_interval_seconds`)

Scheduler implementation: `internal/job_scheduler.py:72–74` starts `BackgroundScheduler(daemon=True)`.

Each consumer registers **callables** (not necessarily threads) — but **many schedulers spawn a daemon thread per tick**:

| Job source | File:line (tick entry) | W/K | Thread per tick? |
|------------|------------------------|-----|------------------|
| Prediction resolver | `resolver_scheduler.py:491,582` `_tick` | K | Optional immediate thread; else APScheduler |
| Daily / hour pick | `pick_scheduler.py:268,476` + `schedule_in_seconds` | K | Same pattern |
| Score snapshot | `score_snapshots.py:1435–1439` `score-snap-tick` | K | **Yes** on `immediate=True` |
| Pump ladder | `pump/scheduler.py:141,240` | K | Yes |
| Pick audit | `pick_audit_scheduler.py:103` | K (heavy) | Yes |
| Outcome snapshot | `outcome_snapshot_scheduler.py:91` | K (heavy) | Yes |
| Calibration snapshot | `calibration_snapshot_scheduler.py:109` | K (heavy) | Yes |
| Dev radar | `dev_radar/github_sync.py:225` | K (heavy) | Yes |
| Indicator | `indicators/indicator_scheduler.py:116` | K | Yes |
| Selector | `council/selector_scheduler.py:51` | K | Yes |
| Pump desk snapshot | `pump/desk_snapshot_scheduler.py` interval job | K | APScheduler only |
| Whale warm | `background_boot.py` → `job_scheduler` interval | K | APScheduler |
| Registry freshness | `internal/freshness.py` (via boot) | K | **INFERRED** interval job |

**Stop behavior:** `cancel_job(JOB_ID)` on scheduler `stop()` — **does not** stop an in-flight `_tick` thread. **VERIFIED** in resolver/pick/score snapshot `stop()` methods.

### 3.4 Per-cycle / per-request ephemeral executors (**primary leak class**)

| File:line | `thread_name_prefix` | Timeout path | On timeout / error | Overlap new cycle? | Evidence |
|-----------|---------------------|--------------|-------------------|-------------------|----------|
| `resolver_scheduler.py:864–958` | `resolver-cycle-work` | `fut.result(timeout=timeout)` | `_abandon_inflight_cycle`; `pool.shutdown(wait=False, cancel_futures=True)` | **Revive / new scheduler (#1552)** — orphan keeps running; **same-instance retry does not** start a second pool while `_inflight_future` unfinished (~806–811). Revive (`1393–1474`) **stop+start** while orphan may live. | **VERIFIED** (inflight guard + revive tests — **do not** assert OS thread counts) |
| `pick_scheduler.py:364–377` | `daily-pick-work` | `FuturesTimeoutError` | `_work_generation += 1`; `shutdown(wait=False)` | **No same-instance retry overlap** — `_refuse_inflight` while prior `fut` not done (~359–362). Orphan may still run until `is_cancelled` stops save. | **VERIFIED** |
| `pump/desk_snapshot_scheduler.py:120–153` | `desk-snapshot-work` | `FuturesTimeoutError` | `shutdown(wait=False)`; **no** generation bump | **Partial** — orphan holds `_cycle_lock` until worker `finally`; next tick may **skip** (`cycle_in_flight`) rather than overlap pool workers. | **VERIFIED** |
| `council/daily_pick.py:217–223` | `dpick-score` | scoring timeout | `shutdown(wait=False, cancel_futures=True)` | **INFERRED** parallel score threads under load |
| `council/score_snapshots.py:873` | `snap-score` | context manager pool | normal `with` exit shuts down pool | MED — inner scoring parallelism per build |
| `council/score_snapshots.py:1307–1315` | `score-snap-write` (global) | `FuturesTimeoutError` on caller | Caller returns; **`_build_and_save` continues** (`completed-after-abandon` log). | **Yes** — single-flight future; next caller may see `scoring_in_progress`. | **VERIFIED** |
| `subnets/feed.py:154,170` | (unnamed / pool) | feed warm | mixed thread + 1-worker pool | **INFERRED** |
| `chain_client.py:945` | parallel RPC | batch timeouts | pool lifecycle in function scope | **INFERRED** |
| `simivision/chat_service.py:135` | 1-worker `with` pool | chat timeout | short-lived | LOW–MED |
| `server.py:820,839,975` | ad hoc 1-worker pools | homepage / cache | some `with`, some manual | **INFERRED** |
| `worker_proxy.py:752` | 1-worker | sync proxy call | `with` pool | LOW |

### 3.5 Long-running service loops (daemon threads, singleton)

| File:line | Thread name | W/K | Stop API |
|-----------|-------------|-----|----------|
| `live_subnets.py:622` | `live-subnets-sync` | K (heavy) | **INFERRED** flag on stop |
| `subnet_universe.py:791,815` | `subnet-universe-refresh`, kick | K/W | daemon |
| `message_intel/summary_bot.py:985` | `telegram-summary-bot` | K | `stop_summary_bot()` |
| `message_intel/*_alert.py` | gainers / stake / trend | K | matching `stop_*` in `stop_background_workers` |
| `message_intel/listener_service.py:733,843` | heartbeat, watchdog | K | service stop |
| `message_intel/outcome_loop.py:147` | `mi-outcome-watchdog` | K | daemon |
| `telegram_listener.py:121` | Telethon loop | K | **INFERRED** stop on listener shutdown |
| `price_tracker.py:465,570` | price loops | K | class lifecycle |
| `pump/state.py:350` | `pump-ladder-fetch` | K | daemon |
| `pump/refresh.py:115` | `pump-ladder-scan` | K | daemon |
| `whales/warm.py:184` | `whale-ledger-warm` | K | one-shot thread per schedule |
| `disk_guard.py:292` | `data-volume-metrics` | B | daemon |
| `snapshot_guard.py:123` | `learning-snapshot-prewarm` | K | daemon |
| `calibration/pipeline.py:587` | `calibration-retrain` | K | daemon |
| `rpc_deadline.py:165` | `rpc-deadline-post` | B | fire-and-forget |
| `signals/alerts.py:241` | webhook post | B | fire-and-forget |
| `judges/council_routes.py:164` | `judges-cache-refresh` | K (heavy warm) | daemon |
| `cockpit/routes.py:62` | `cockpit-sections-refresh` | W | daemon |
| `server.py` various | `subnets-cache-refresh`, `simivision-cache-refresh`, `top-picks-cache-refresh`, `homepage-warm-render`, etc. | W | daemon; BG refresh guards reduce overlap |

### 3.6 Async timeout wrappers (no new OS thread by themselves)

These bound **wait** time on work that already runs in a thread pool:

| File:line | Mechanism |
|-----------|-----------|
| `server.py:705–716` `_to_thread_timeout` → `_DASHBOARD_EXECUTOR` |
| `server.py:3290` `asyncio.wait_for(asyncio.shield(aio), …)` |
| `internal/request_executor.py:44–45` `asyncio.wait_for` + `run_in_executor` |
| `internal/judges/council_routes.py:80` | `asyncio.to_thread` + `wait_for` |
| `internal/letter/routes.py:27,101` | same pattern |
| `internal/share_pages/routes.py:46,88,319,436` | same |
| `internal/signals/routes.py:33` | same |
| `internal/mindmap/routes.py:101–102` | `run_in_executor(REQUEST_EXECUTOR, …)` |
| `internal/cockpit/routes.py:104,133` | `wait_for` |
| `internal/load_shed.py:65` | semaphore acquire timeout |
| `internal/simivision/chat_service.py:456` | `wait_for` |
| `internal/ops/readiness_cache.py:350` | `wait_for` |

On timeout: asyncio cancels the **Future**, but the **underlying thread pool job keeps running** unless the callable cooperatively exits. **VERIFIED** (Python semantics + pick generation / resolver generation guards).

---

## 4. Per-site: timeout / restart — joined, cancelled, or abandoned?

### 4.1 Prediction resolver (`internal/council/resolver_scheduler.py`)

| Event | Behavior | Overlap? | Tag |
|-------|----------|----------|-----|
| Cycle exceeds budget | Main tick thread returns error; `_abandon_inflight_cycle` bumps `_cycle_generation`, replaces `_cycle_lock`, clears persist owner; pool **`shutdown(wait=False)`** | Orphan **`resolver-cycle-work`** thread continues grading/hydration until natural completion or process exit | **VERIFIED** |
| Next scheduled `_tick` (same scheduler) | **`_inflight_future` guard** — returns `previous_cycle_inflight` / `_refuse_inflight` while abandoned worker still running; does **not** spawn a second pool on ordinary retry | **No** (same instance) | **VERIFIED** (`test_resolver_cycle_timeout_does_not_overlap_inflight_work`) |
| `revive_prediction_resolver_scheduler` | May `stop()` + `start_prediction_resolver_scheduler` + synchronous `run_once()` while **prior** scheduler’s orphan still running | **Yes (#1552 class)** | **VERIFIED** (`test_resolver_revive.py`, `test_phase3_mid_guards_orphan_revive.py`) |
| `stop()` | Sets `_active=False`, `cancel_job` — **does not join** tick or pool worker | Orphan survives stop | **VERIFIED** |

Telemetry today: `log_lifecycle("abandon"|"timeout")`, `log_heavy_job_rss` (includes `threads=`). Cycle summary field **`abandoned_live`** is **misnamed**: in `resolver_scheduler.py` it is **incremented on timeout** (`_abandoned_live += 1`) and **never decremented** when the orphan thread exits — a **cumulative abandon count since scheduler construction**, not a live orphan gauge. **VERIFIED** (code read). Do **not** use it alone for revive gates or “drain” proofs.

### 4.2 Daily pick scheduler (`pick_scheduler.py`)

| Event | Behavior | Overlap? | Tag |
|-------|----------|----------|-----|
| Tick timeout | `_work_generation += 1`; pool shutdown non-waiting | Orphan may still run; `is_cancelled` prevents **save** only | **VERIFIED** |
| Reschedule after error | Short delay via `schedule_in_seconds` — **still blocked** on same `_inflight_future` until orphan `fut` completes | **No** (same instance) | **VERIFIED** |

### 4.3 Score snapshot producer (`score_snapshots.py`)

| Event | Behavior | Overlap? | Tag |
|-------|----------|----------|-----|
| Write wait timeout | Caller gets `write_timeout_*`; global executor keeps building | Next tick may hit `scoring_in_progress` or stack CPU | **VERIFIED** |
| Scheduler `stop()` | Cancels APScheduler job; **in-flight tick thread** not stopped | **Yes** | **VERIFIED** |
| `revive_score_snapshot_scheduler` | Recycle + `run_once` — same overlap class as resolver | **Yes** | **VERIFIED** (`tests/test_loop_stall_guard.py`) |

### 4.4 Pump desk snapshot (`desk_snapshot_scheduler.py`)

| Event | Behavior | Second pool worker overlap? | Tag |
|-------|----------|----------------------------|-----|
| Timeout | Returns error; orphan releases **`_cycle_lock`** in worker `finally` after slow `run_snapshot` | **No** (same scheduler) — **`_cycle_lock.acquire(blocking=False)`** fails on next tick → **`cycle_in_flight` skip** (~117–118) | **VERIFIED** |
| No generation token | Orphan always runs to completion on its pool thread | **No** extra submit while lock held; aligns with §3.4 **Partial (skip, not overlap)** | **VERIFIED** |

### 4.5 Heavy job gate (`internal/heavy_job_gate.py`)

Serializes resolver vs score snapshot vs pump **starts** — does **not** terminate abandoned workers. **VERIFIED** (resolver still abandons inside acquired slot; gate released after tick returns).

### 4.6 Loop stall guard (`internal/loop_stall_guard.py`)

On stale snapshot/resolver: calls **revive** then may **`os._exit`** worker. Orphan threads die with process — **containment**, not fix. **VERIFIED**

---

## 5. Local repro (real numbers)

**Artifact:** `tests/test_thread_abandon_leak_repro.py`  
**Command:** `.venv/bin/pytest tests/test_thread_abandon_leak_repro.py -v -s`  
**Environment:** Linux cloud agent VM, Python 3.12.3, pytest 9.2.0 (2026-11-04).

**Uses real scheduler code** — `PredictionResolverScheduler._run_refresh_cycle_with_timeout` with monkeypatched slow `_run_refresh_cycle` and short resolver budgets (same pattern as `tests/test_resolver_scheduler.py` / `test_phase3_mid_guards_orphan_revive.py`).

| Test | What it proves | What it does **not** prove |
|------|----------------|----------------------------|
| Single abandon | Named `resolver-cycle-work` thread exists while orphan blocked | Prod accumulation or retry overlap |
| Two scheduler instances (concurrent) | Two abandoned cycles ⇒ two named workers (synthetic **multi-instance** analogue only) | **Revive overlap** — use `tests/test_resolver_revive.py` / revive integration for #1552 class |

**Ordinary retry overlap is disproven in-tree:** `test_resolver_cycle_timeout_does_not_overlap_inflight_work` — second `_run_refresh_cycle_with_timeout` skips until first orphan finishes.

**Phase 0 code PR (not this plan PR) must ship hardened repro before merge:**

| Test | Required change |
|------|-----------------|
| `test_two_resolver_schedulers_two_named_workers` | **`baseline_named`** before threads start; record **two successful barrier rendezvous** (fail if `BrokenBarrierError`); assert **`peak_named >= baseline_named + 2`**; **`release.set()` in `finally`** |
| `test_sequential_abandon_drain_diagnostic` | Assert each timed-out cycle returns **`cycle_timeout`** in error **or** move to **`@pytest.mark.diagnostic`** and exclude from contract CI — print-only must not ship as regression guard |

Until hardened, the two-scheduler test is **documented contract only** (plan); Ditto CHANGES_REQUESTED clears when Phase 0 code lands the table above.

**Assertion:** fails if production abandon path stops creating named pool workers (e.g. joined shutdown or instant completion). RSS deltas are diagnostic prints only — not prod leak proof.
- RSS drift at this scale is noise; **do not infer** hundreds of MiB prod RSS from thread stacks without measurement.

---

## 6. Ranked fix options

| Rank | Option | Change size | Risk | Prod proof |
|------|--------|-------------|------|------------|
| **1** | **Replace per-cycle pools** with process-wide bounded executors (resolver / pick / desk — **separate pools or shared heavy pool with explicit queue semantics**); document head-of-line risk if `max_workers=1` and orphan cannot be killed | Medium (~200–400 LOC) | Med — scheduling semantics change | Sampler `live` + named-prefix counts flat under forced timeout staging |
| **2** | **Cooperative cancellation** already partial (`_work_generation`, resolver `gen != self._cycle_generation`) — extend to **all blocking steps** (RPC, hydration, soul_map RMW) with periodic `is_cancelled()` checks | Medium–large | Med — missed check leaves hang | **`live` orphans** return to 0 after timeout bursts; abandon **rate** vs orphan-completed **rate** balanced in logs |
| **3** | **Subprocess isolation** for resolver cycle / score snapshot build (`subprocess.run` with hard kill on timeout) | Large | Med — IPC, volume paths, startup cost | Process exit guarantees thread reclamation; measure worker RSS/threads after injected hang |
| **4** | **Single-flight lock** at scheduler level: do not schedule next tick until prior `_inflight_future.done()` **and** **`live` orphan count == 0** (not cumulative `abandoned_live`) | Small | **High liveness** — one hung orphan can wedge the loop permanently unless subprocess/kill | Fewer overlapping `resolver-cycle-work` threads in sampler peaks |
| **5** | **Revive gating (#1552):** refuse `revive_*` until **`live` orphans == 0** (or supervisor kills subprocess) | Small–medium | **Med** — false revive avoided; **one permanently hung orphan blocks revive forever** unless subprocess/kill path | No double scheduler `lifecycle event=start` while sampler shows `live>0` |
| **6** | **Join with cap** (`shutdown(wait=True)` + short grace) — **dangerous** on Fly (blocks tick thread) | Small | **High** — wedges health | Not recommended alone |
| **7** | Further **`MALLOC_ARENA_MAX` / malloc_trim** tuning | Small | Low | RSS only — **proven insufficient** for threads (#1558) |

**Existing logging to extend (read-only PR):** `log_heavy_job_rss` (`threads=`), `log_lifecycle`, score snapshot `completed-after-abandon`. **Replace reliance on monotonic `abandoned_live`** with the counter model in §8.

---

## 7. Recommendation (plain language)

**If the hypothesis holds**, the worker would start long chores on background threads, stop waiting when they overrun a budget, but leave those chores running — **revive / multi-scheduler overlap** could raise concurrent helper threads until work finishes or the process restarts; **same-scheduler retries are inflight-guarded** and do not add a second pool worker. Recent captures show **flat** ~22–24 threads, so that story is **not yet confirmed** in prod. `#1558` trimmed allocator RSS but did not change abandon semantics.

**After logging (§8)** proves or falsifies overlap growth, the safest behavioral fixes remain: **fewer throwaway pools**, **cooperative cancel** in long loops, and **subprocess + hard kill** for work that must not outlive its budget — plus **revive gating on `live` orphans**, not cumulative counters.

---

## 8. Logging-first observability (Phase 0 — no behavior change)

Joshua constraint: **logging only** first. Phase 0 may ship **the same deploy day** as morning-pick observability (#1561 / unrelated pick PR): it must **not** change timeout, shutdown, or revive behavior. It **will** add **one** `thread-orphan-sampler` daemon (+1 OS thread, ~2 log lines/min). **Staging episode** (§8.3 leg 1) runs on **staging only after** Phase 0 merges; it does **not** gate or delay the prod morning pick.

### 8.1 Counters (per heavy job family: resolver, daily pick, desk snapshot, score-snapshot write)

Shared helper (next PR): **`internal/orphan_job_metrics.py`** (name TBD) with:

- One process-wide **`threading.Lock`** (`_orphan_metrics_lock`) — counter mutations and **`OrphanJob` state transitions** hold this lock; keep critical sections **minimal**.
- **`Future.add_done_callback` must never run while `_orphan_metrics_lock` is held.** CPython may invoke a done callback **inline** on the registering thread when the future is already complete; the callback re-enters the metrics lock → **self-deadlock** with a plain `Lock`. **Do not** substitute `RLock` as the primary fix (masks re-entrancy bugs). **Wiring order:** (1) under lock: allocate `job_key`, insert **ACTIVE**, `submitted++`; (2) **release lock**; (3) `fut = pool.submit(...)`; (4) **`fut.add_done_callback(...)`** still **outside** lock; (5) callback body: acquire lock → transition table → release.
- Per-family aggregate counters: **`submitted`**, **`abandoned`**, **`orphan_completed`**, **`live`**.
- Per-submit **`OrphanJob`** record keyed by stable **`job_key`** (resolver: `resolver_cycle_id`; pick: tick id + monotonic seq; etc.) bound to the **`concurrent.futures.Future`**.

| Metric | Meaning | Update points |
|--------|---------|---------------|
| **`submitted`** | Pool work items submitted for a cycle/tick | `pool.submit` → create `OrphanJob` state **`ACTIVE`** (under lock) |
| **`abandoned`** | Caller gave up waiting (timeout path) | **`ACTIVE` → `ABANDONED`** transition (under lock) |
| **`orphan_completed`** | Abandoned worker finished | **`ABANDONED` → `CLOSED`** transition (under lock) |
| **`live`** | Orphans still running now | **`live += 1`** only on **`ACTIVE` → `ABANDONED`**; **`live -= 1`** only on **`ABANDONED` → `CLOSED`** — never compare generation outside this machine |

#### 8.1.1 Per-job state machine (fixes P1 race + double decrement)

**Problem:** today’s sketch increments `live` on the tick thread **after** `_abandon_inflight_cycle` bumps `_cycle_generation` (~788–800 before ~910–917). A pool worker can finish in between; a naive callback that tests `gen < self._cycle_generation` may **`live -= 1` before `live += 1`**, or decrement when **`live == 0`**. **`floor 0` must not be used** — it hides bugs.

**Rule:** abandon accounting is keyed to the **specific `Future` / `job_key`**, not to generation alone. Generation remains for **work cancellation**; metrics use **`OrphanJob.state`**.

```
                    submit (lock)
                         │
                         ▼
                    ┌─────────┐
         ┌─────────│ ACTIVE  │─────────┐
         │         └─────────┘         │
  fut.result      │              worker returns
  timeout         │              (still ACTIVE)
  (lock)          │                    │
         │         │                    │
         ▼         │                    ▼
    ┌──────────┐   │              ┌───────────┐
    │ ABANDONED│   │              │ COMPLETED │  (never incremented live)
    │ live++   │   │              │ (no live  │
    └────┬─────┘   │              │  change)  │
         │         │              └─────┬─────┘
  done_callback     │                    │
  (lock)            │                    │
         │         │                    │
         ▼         │                    ▼
    ┌──────────┐   │              ┌──────────┐
    │  CLOSED  │◄──┴──────────────│  CLOSED  │
    │ live--   │   abandon path   │          │
    │ orphan_  │   if still       │          │
    │ completed++                  │          │
    └──────────┘                    └──────────┘

  fut.cancelled() before run → CANCELLED_QUEUED → CLOSED (no live change)
```

**Transitions (all under `_orphan_metrics_lock`):**

| From | Event | To | Counter effects |
|------|-------|-----|-----------------|
| — | `register(fut, job_key)` on submit | **ACTIVE** | `submitted++` |
| **ACTIVE** | `mark_abandoned(job_key)` on caller timeout **after** `fut.done()` check: if already done → treat as normal complete, not abandon | **ABANDONED** or **COMPLETED** | **ABANDONED:** `abandoned++`, `live++`, registry `abandoned_at` |
| **ACTIVE** | worker finishes before timeout | **COMPLETED** | none on `live` |
| **ABANDONED** | `Future.add_done_callback` | **CLOSED** | `orphan_completed++`, `live--`, drop registry entry, log age |
| **COMPLETED** | callback | **CLOSED** | none on `live` |
| **ACTIVE** / pending | callback with **`fut.cancelled()`** and worker never ran | **CANCELLED_QUEUED** → **CLOSED** | **no** `live` / `orphan_completed` |

**`Future.add_done_callback` on cancelled futures (Python 3.12):** cancelling a **queued** future **does** invoke done callbacks when the executor drains the queue (`shutdown(..., cancel_futures=True)`). The callback **must** branch on **`fut.cancelled()`** (and/or `OrphanJob` still **ACTIVE** without **`mark_abandoned`**) — **never** treat cancellation as **`orphan_completed`**. Only **`ABANDONED` → `CLOSED`** decrements **`live`**.

**Single hook per future:** register **one** callback **after** `submit`, **outside** `_orphan_metrics_lock`, calling `_on_pool_future_done(family, job_key, fut)` which acquires the lock and runs the transition table. Do **not** also decrement in pool-worker `finally` (double-close risk).

#### 8.1.2 Callback registration vs lock (fixes self-deadlock)

| Step | Thread | Lock held? |
|------|--------|------------|
| Pre-register `job_key` → **ACTIVE**, `submitted++` | tick | **yes**, then **release** before submit |
| `pool.submit(worker)` | tick | **no** |
| `fut.add_done_callback(_on_pool_future_done, ...)` | tick | **no** — mandatory even if worker is fast |
| `_on_pool_future_done` | tick or pool | **yes** only inside callback body |
| `mark_abandoned(job_key)` on timeout | tick | **yes**; if `fut.done()` before lock, complete without **ABANDONED** |

**Sampler reads** (`live`, oldest age): acquire `_orphan_metrics_lock` briefly for snapshot; do not register callbacks under sampler.

**Per-scheduler wiring (next PR):**

| Scheduler | Register **ACTIVE** (lock → unlock) | `submit` + **`add_done_callback` outside lock** | `mark_abandoned(job_key)` |
|-----------|--------------------------------------|---------------------------------------------------|---------------------------|
| **Resolver** `resolver_scheduler.py` | Before `pool.submit(_run_cycle)` (~904) | Immediately after submit, before `fut.result` | `FuturesTimeoutError` (~909–917) after `_abandon_inflight_cycle` |
| **Daily pick** `pick_scheduler.py` | Before `pool.submit(_run_pick)` (~365) | After submit | `FuturesTimeoutError` (~370–375) |
| **Desk snapshot** `desk_snapshot_scheduler.py` | Before `pool.submit(_run)` (~141) | After submit | `FuturesTimeoutError` (~147–151) |
| **Score snapshot write** `score_snapshots.py` | Before submit | Extend existing callback (~1305), body uses lock | `caller_abandoned.set()` on timeout (~1308–1314) |

**Required tests (Phase 0 PR — `tests/test_orphan_job_metrics.py` or scheduler integration):**

1. **Timeout boundary — worker finishes first:** slow work released **just before** timeout fires; assert **`live == 0`**, **`abandoned == 0`**, job ends **COMPLETED**.
2. **Timeout boundary — abandon first:** block worker past timeout; assert **`live == 1`** until callback; then **`live == 0`**, **`orphan_completed == 1`**.
3. **Race — concurrent callback and timeout:** two threads call `mark_abandoned` and `_on_pool_future_done` with barrier; assert **`live`** never negative and exactly one increment/decrement pair.
4. **`future.cancelled()`:** submit no-op, `shutdown(wait=False, cancel_futures=True)` before worker starts; assert callback runs but **`live` unchanged**, **`orphan_completed` unchanged**.
5. **Exactly-once decrement:** inject double callback invocation (test hook); assert **`live`** does not go negative and **`CLOSED`** is idempotent.
6. **Self-deadlock guard:** submit work that **returns immediately** (or finishes before `add_done_callback` returns); assert metrics **`live == 0`** and test thread **does not hang** — proves callback registration stayed **outside** lock.

**`cancel_futures=True` accounting:** **`submitted`** counts registered jobs; **`abandoned`** counts caller timeouts on **started** work; **`CANCELLED_QUEUED`** jobs are neither **`abandoned`** nor **`orphan_completed`**. Do **not** expect **`submitted == abandoned + orphan_completed + cancelled`** without explicit **`cancelled_queued`** counter (optional log field).

Log **`live`**, **`oldest_live_orphan_age_seconds`**, and optionally the three totals at **job start** and **job end** on the tick/submit thread. Keep soul_map / cycle summary fields aligned: rename today's **`abandoned_live`** to **`abandoned_total`** or add parallel **`orphan_live`** so dashboards do not treat cumulative as live.

Also log **named thread counts** at boundaries: `resolver-cycle-work`, `daily-pick-work`, `desk-snapshot-work`, `snap-score`, `dpick-score`, plus **`active_count`** and existing **`threads=`** from `log_heavy_job_rss`.

**Structured events (in addition to boundaries):**

- **`orphan_abandoned`** — job id, generation, enforced timeout, **`live` after increment**, **`abandoned_at`** monotonic.
- **`orphan_completed`** — job id, generation, **`live` after decrement**, **age_seconds** since abandon.

**Registry for oldest age:** on abandon, store `{job_key: time.monotonic()}` under the metrics lock; remove on completion. **Hung orphan:** never completes ⇒ entry stays; age grows — visible only via sampler **`oldest_live_orphan_age_seconds`**, not via `orphan_completed` events alone.

### 8.2 Background sampler (required — bookends alone are insufficient)

Start **one** daemon thread at **worker boot** and at **web lifespan** (even when `BACKGROUND_ON_WEB=off`, web still runs boot daemons — include them): name **`thread-orphan-sampler`**, interval **30s**.

Each tick (cheap — no I/O beyond logging), under a **read lock** or short lock hold on metrics:

- `threading.active_count()` (exclude **`thread-orphan-sampler`** in analysis notes)
- RSS via existing helper
- Count threads matching heavy prefixes: `resolver-cycle-work`, `daily-pick-work`, `desk-snapshot-work`, `snap-score`, `dpick-score`
- **Web boot / warm (include in sampler):** `homepage-warm-boot`, `homepage-warm-render`, `homepage-warm` (`server.py` lifespan + on-demand warm paths)
- Current **`live`** totals per family from in-process counters
- **`oldest_live_orphan_age_seconds`** across the abandon registry ( **required every sample** — detects wedged orphans that never emit `orphan_completed`)

**Why:** an orphan can **start and finish between** tick start/end samples; only periodic samples + completion events establish whether **live population grows**. A stuck orphan with **`live=1`** forever looks like “no accumulation” unless **oldest age** climbs.

**Cost:** **+1 daemon thread**; log volume ≈ **2 lines/minute** at 30s (negligible vs existing `rss-heartbeat` / lifecycle noise).

### 8.3 Proof / disproof criteria

| Leg | Outcome | Interpretation |
|-----|---------|----------------|
| **Staging episode** (§1 leg 1) | After forced short timeouts, **`live` → 0** and **`oldest_live_orphan_age_seconds` → 0** within bounded wall time; **`orphan_completed ≈ abandoned`** for started work | Timeouts happen; **no sustained accumulation** on staging. **Note:** forced 1s budgets change abandon **rates** vs prod (orphan duration still job-bound) — compare **trends**, not absolute counts to prod. |
| **Staging episode** | **`live` or oldest age monotonic rise** during burst while **`orphan_completed` lags `abandoned`** | **Accumulation supported** on staging — proceed toward behavioral fixes (§6) |
| **Multi-day prod trend** (§1 leg 2) | **`max(live)`** and named-prefix **peaks flat** over ≥3 days at **30s sampler cadence** | **No detected accumulation** — does **not** prove zero short-lived orphans between samples |
| **Multi-day prod trend** | Rising **peak** band or sustained **`live ≥ 2`** **with rising oldest age** across days | **Accumulation supported** — not established by a single transient `live=2` |
| Either | High **`abandoned` total** but **`live` 0–1** and **oldest age ~0** after idle | Timeouts without pile-up — tune revive paranoia, not unbounded leak |

---

## 9. Suggested implementation order (after Phase 0 logging)

1. **Phase 0:** §8.1.1–8.1.2 state machine + lock-outside-callback wiring + sampler + events + **`tests/test_orphan_job_metrics.py`** (incl. fast-complete / deadlock guard) + **hardened repro table §5** (**this PR is plan-only**; next PR is code).
2. Refactor **resolver** to shared executor + **`live`**-gated revive (#1552).
3. Align **daily pick** and **desk snapshot**.
4. **Score snapshots** write path: caller timeout must cancel build (generation) or subprocess.
5. Staging torture (§8.3 leg 1): forced short timeouts on **staging worker**; accept **`live` bounded** and oldest age draining after burst before prod behavior changes.

---

## 10. Out of scope for this PR

- Application fixes, Fly deploy, workflow edits, merge to main.
- PR #1561 / branch `cursor/daily-pick-morning-plan-3740` (untouched).
