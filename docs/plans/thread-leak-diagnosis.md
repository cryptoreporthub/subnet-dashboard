# Thread / abandon leak diagnosis (plan only)

**Status:** Diagnosis + fix plan — **no product code changes in this PR.**  
**Repo:** `cryptoreporthub/subnet-dashboard`  
**Prod context:** Fly 1GB VM, web (Uvicorn) + inline or dedicated worker (`RUN_MODE=worker`).  
**Related:** #1552 (orphaned resolver vs revived scheduler overlap), #1558 / PR #1538 (`MALLOC_ARENA_MAX=2` RSS containment — does **not** stop thread accumulation from abandoned work).

---

## 1. Executive summary

Production captures show the **worker** holding ~21–26 threads at boot and ~**22–24 steady** (flat in recent operator windows), while **web** reports ~8 threads at boot. `MALLOC_ARENA_MAX=2` cut worker RSS (~500 → ~285 MiB) by shrinking glibc arenas; **that does not prove or disprove thread accumulation from abandon paths.**

**Hypothesis (unproven in prod):** the main growth mechanism is **not** forgotten daemon tick threads (those are bounded and named) but **ephemeral `ThreadPoolExecutor` instances** per resolver cycle, daily-pick tick, desk snapshot, etc., plus **`future.result(timeout=…)` + `pool.shutdown(wait=False, cancel_futures=True)`**. That pattern returns on timeout without joining the worker; `cancel_futures` only drops **queued** work, not a thread already running Python. Under **rapid** timeouts, overlapping orphans can pile up until work finishes (often minutes for resolver/scoring). **Revive** paths (#1552) may start a new scheduler generation while prior orphans still run.

**Falsifier:** if structured logging + the background sampler (§8) show **`live` orphan count ≤ 1** at peak and **process `active_count` flat** across **three** daily-pick mornings plus normal resolver cycles on the worker, treat thread-growth-from-abandon as **disproven** for that workload (RSS drift remains a separate question).

**First approved step:** **logging only** — no scheduler/executor behavior changes; logging does not alter memory layout (same deploy day as morning-pick observability is OK).

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
| `resolver_scheduler.py:864–958` | `resolver-cycle-work` | `fut.result(timeout=timeout)` | `_abandon_inflight_cycle`; `pool.shutdown(wait=False, cancel_futures=True)` | **Yes** — generation bump + lock replace; orphan keeps running until `_run_refresh_cycle` finishes. Next `_tick` can submit while **`live` orphans > 0** (cumulative `abandoned_live` also rises). Revive (`1393–1474`) **stop+start** scheduler while orphan may live. | **VERIFIED** (code + behavioral tests — those tests do **not** assert OS thread counts) |
| `pick_scheduler.py:364–377` | `daily-pick-work` | `FuturesTimeoutError` | `_work_generation += 1`; `shutdown(wait=False)` | **Yes** — new tick can start new pool while orphan runs (`is_cancelled` gate on save only). | **VERIFIED** |
| `pump/desk_snapshot_scheduler.py:120–153` | `desk-snapshot-work` | `FuturesTimeoutError` | `shutdown(wait=False)`; **no** generation bump | **Yes** — orphan holds `_cycle_lock` until `finally` in worker; next tick may skip `cycle_in_flight`. | **VERIFIED** |
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
| Next scheduled `_tick` | Can run while cumulative `abandoned_live > 0` and/or **live** orphans > 0; may skip if `_inflight_future` not done | **Yes** | **VERIFIED** |
| `revive_prediction_resolver_scheduler` | May `stop()` + `start_prediction_resolver_scheduler` + synchronous `run_once()` while orphan still running | **Yes (#1552 class)** | **VERIFIED** |
| `stop()` | Sets `_active=False`, `cancel_job` — **does not join** tick or pool worker | Orphan survives stop | **VERIFIED** |

Telemetry today: `log_lifecycle("abandon"|"timeout")`, `log_heavy_job_rss` (includes `threads=`). Cycle summary field **`abandoned_live`** is **misnamed**: in `resolver_scheduler.py` it is **incremented on timeout** (`_abandoned_live += 1`) and **never decremented** when the orphan thread exits — a **cumulative abandon count since scheduler construction**, not a live orphan gauge. **VERIFIED** (code read). Do **not** use it alone for revive gates or “drain” proofs.

### 4.2 Daily pick scheduler (`pick_scheduler.py`)

| Event | Behavior | Overlap? | Tag |
|-------|----------|----------|-----|
| Tick timeout | `_work_generation += 1`; pool shutdown non-waiting | Orphan may still run; `is_cancelled` prevents **save** only | **VERIFIED** |
| Reschedule after error | Short delay via `schedule_in_seconds` — can overlap orphan | **Yes** | **VERIFIED** |

### 4.3 Score snapshot producer (`score_snapshots.py`)

| Event | Behavior | Overlap? | Tag |
|-------|----------|----------|-----|
| Write wait timeout | Caller gets `write_timeout_*`; global executor keeps building | Next tick may hit `scoring_in_progress` or stack CPU | **VERIFIED** |
| Scheduler `stop()` | Cancels APScheduler job; **in-flight tick thread** not stopped | **Yes** | **VERIFIED** |
| `revive_score_snapshot_scheduler` | Recycle + `run_once` — same overlap class as resolver | **Yes** | **VERIFIED** (`tests/test_loop_stall_guard.py`) |

### 4.4 Pump desk snapshot (`desk_snapshot_scheduler.py`)

| Event | Behavior | Overlap? | Tag |
|-------|----------|----------|-----|
| Timeout | Returns error; orphan releases `_cycle_lock` in `finally` after slow `run_snapshot` | Skipped ticks while lock held | **VERIFIED** |
| No generation token | Orphan always runs to completion | **Yes** | **VERIFIED** |

### 4.5 Heavy job gate (`internal/heavy_job_gate.py`)

Serializes resolver vs score snapshot vs pump **starts** — does **not** terminate abandoned workers. **VERIFIED** (resolver still abandons inside acquired slot; gate released after tick returns).

### 4.6 Loop stall guard (`internal/loop_stall_guard.py`)

On stale snapshot/resolver: calls **revive** then may **`os._exit`** worker. Orphan threads die with process — **containment**, not fix. **VERIFIED**

---

## 5. Local repro (real numbers)

**Artifact:** `tests/test_thread_abandon_leak_repro.py`  
**Command:** `.venv/bin/pytest tests/test_thread_abandon_leak_repro.py -v -s`  
**Environment:** Linux cloud agent VM, Python 3.12.3, pytest 9.2.0 (2026-11-04).

The test mirrors resolver abandon (stdlib only — does not import `resolver_scheduler`): each cycle creates `ThreadPoolExecutor(max_workers=1, thread_name_prefix="resolver-cycle-work")`, submits slow work, short `result(timeout=…)`, then `shutdown(wait=False, cancel_futures=True)`.

| Metric | Baseline | After 8 sequential abandons | Rapid 8-cycle overlap |
|--------|----------|----------------------------|------------------------|
| `threading.active_count()` | 1 | 1 (+0) | N/A |
| `VmRSS` (kB) | 83596 | 83724 (+128) | N/A |
| Named `resolver-cycle-work` threads (peak) | 0 | 0 (orphans finished before scan) | **8 concurrent** |

**Assertion:** `peak_named >= cycles` (8) under rapid abandons — fails if overlap does not occur (e.g. joined shutdown). Sequential phase is diagnostic print only (orphans drain before scan).

- Sequential abandons with 2s work and 5s post-wait did not raise **steady-state** `active_count()` — orphans exited before measurement.
- **Rapid** abandons (1s work, 0.01s timeout, 0.02s spacing) produced **8 simultaneous** pool worker threads — demonstrates **overlap** when cycles recur faster than work duration (production analogue: resolver/pick timeouts faster than cycle wall time).
- RSS drift (+128 kB) is noise at this scale; **do not infer** hundreds of MiB prod RSS from thread stacks without measurement.

---

## 6. Ranked fix options

| Rank | Option | Change size | Risk | Prod proof |
|------|--------|-------------|------|------------|
| **1** | **Replace per-cycle pools** with process-wide bounded executors (resolver / pick / desk — **separate pools or shared heavy pool with explicit queue semantics**); document head-of-line risk if `max_workers=1` and orphan cannot be killed | Medium (~200–400 LOC) | Med — scheduling semantics change | Sampler `live` + named-prefix counts flat under forced timeout staging |
| **2** | **Cooperative cancellation** already partial (`_work_generation`, resolver `gen != self._cycle_generation`) — extend to **all blocking steps** (RPC, hydration, soul_map RMW) with periodic `is_cancelled()` checks | Medium–large | Med — missed check leaves hang | **`live` orphans** return to 0 after timeout bursts; abandon **rate** vs orphan-completed **rate** balanced in logs |
| **3** | **Subprocess isolation** for resolver cycle / score snapshot build (`subprocess.run` with hard kill on timeout) | Large | Med — IPC, volume paths, startup cost | Process exit guarantees thread reclamation; measure worker RSS/threads after injected hang |
| **4** | **Single-flight lock** at scheduler level: do not schedule next tick until prior `_inflight_future.done()` **and** **`live` orphan count == 0** (not cumulative `abandoned_live`) | Small | **High liveness** — one hung orphan can wedge the loop permanently unless subprocess/kill | Fewer overlapping `resolver-cycle-work` threads in sampler peaks |
| **5** | **Revive gating (#1552):** refuse `revive_*` until **`live` orphans == 0** or supervisor kills subprocess | Small–medium | Low for false revive; needs live visibility | No double scheduler `lifecycle event=start` while sampler shows `live>0` |
| **6** | **Join with cap** (`shutdown(wait=True)` + short grace) — **dangerous** on Fly (blocks tick thread) | Small | **High** — wedges health | Not recommended alone |
| **7** | Further **`MALLOC_ARENA_MAX` / malloc_trim** tuning | Small | Low | RSS only — **proven insufficient** for threads (#1558) |

**Existing logging to extend (read-only PR):** `log_heavy_job_rss` (`threads=`), `log_lifecycle`, score snapshot `completed-after-abandon`. **Replace reliance on monotonic `abandoned_live`** with the counter model in §8.

---

## 7. Recommendation (plain language)

**If the hypothesis holds**, the worker would start long chores on background threads, stop waiting when they overrun a budget, but leave those chores running — so **overlapping** timeouts could raise concurrent helper threads until work finishes or the process restarts. Recent captures show **flat** ~22–24 threads, so that story is **not yet confirmed** in prod. `#1558` trimmed allocator RSS but did not change abandon semantics.

**After logging (§8)** proves or falsifies overlap growth, the safest behavioral fixes remain: **fewer throwaway pools**, **cooperative cancel** in long loops, and **subprocess + hard kill** for work that must not outlive its budget — plus **revive gating on `live` orphans**, not cumulative counters.

---

## 8. Logging-first observability (Phase 0 — no behavior change)

Joshua constraint: **logging only** first (may ship same day as morning-pick work); must not change memory behavior or scheduling.

### 8.1 Counters (per heavy job family: resolver, daily pick, desk snapshot, score-snapshot write)

| Metric | Meaning | Update points |
|--------|---------|---------------|
| **`submitted`** | Pool work items submitted for a cycle/tick | On `pool.submit` |
| **`abandoned`** | Caller gave up waiting (timeout path) | On `FuturesTimeoutError` + non-wait shutdown |
| **`orphan_completed`** | Abandoned worker thread exited (`finally` in pool worker) | Decrement **`live`**; increment **`orphan_completed`** |
| **`live`** | Orphans still running now | **`live += 1` on abandon**, **`live -= 1` on orphan_completed** (floor 0) |

Log **`live`** (and optionally the three totals) at **job start** and **job end** on the tick/submit thread. Keep soul_map / cycle summary fields aligned: either rename today's **`abandoned_live`** to **`abandoned_total`** or add parallel **`orphan_live`** so dashboards do not treat cumulative as live.

Also log **named thread counts** at boundaries: `resolver-cycle-work`, `daily-pick-work`, `desk-snapshot-work`, `snap-score`, `dpick-score`, plus **`active_count`** and existing **`threads=`** from `log_heavy_job_rss`.

**Structured events (in addition to boundaries):**

- **`orphan_abandoned`** — job id, generation, enforced timeout, **`live` after increment**, age 0.
- **`orphan_completed`** — job id, generation, **`live` after decrement**, **age_seconds** since abandon (proves drain vs accumulate).

### 8.2 Background sampler (required — bookends alone are insufficient)

Start **one** daemon thread at worker boot (and web if inline worker path): name **`thread-orphan-sampler`**, interval **30s**.

Each tick (cheap — no I/O beyond logging):

- `threading.active_count()` (document sampler thread excluded in analysis if needed)
- RSS via existing helper
- Count threads matching heavy prefixes (same list as §8.1)
- Optional: current **`live`** totals from in-process counters

**Why:** an orphan can **start and finish between** tick start/end samples; only periodic samples + completion events establish whether **live population grows**.

**Cost:** **+1 daemon thread**; log volume ≈ **2 lines/minute** at 30s (negligible vs existing `rss-heartbeat` / lifecycle noise).

### 8.3 Proof / disproof criteria

| Outcome | Interpretation |
|---------|----------------|
| Sampler max **`live` ≤ 1** and **`active_count` band stable** over 3 daily picks + resolver days | **Hypothesis falsified** for current prod workload |
| Repeated **`live ≥ 2`** with rising named-prefix peaks | **Hypothesis supported** — proceed to behavioral fixes (§6) |
| High **`abandoned` total** but **`live` always 0–1** | Timeouts happen; **no accumulation** — fix revive/overlap paranoia, not unbounded leak |

---

## 9. Suggested implementation order (after Phase 0 logging)

1. **Phase 0:** §8 counters + sampler + abandon/completion events (**this PR is plan-only**; next PR is code).
2. Refactor **resolver** to shared executor + **`live`**-gated revive (#1552).
3. Align **daily pick** and **desk snapshot**.
4. **Score snapshots** write path: caller timeout must cancel build (generation) or subprocess.
5. Staging torture: `RESOLVER_CYCLE_TIMEOUT_SECONDS=1`; accept **`live` bounded**, sampler peaks stable.

---

## 10. Out of scope for this PR

- Application fixes, Fly deploy, workflow edits, merge to main.
- PR #1561 / branch `cursor/daily-pick-morning-plan-3740` (untouched).
