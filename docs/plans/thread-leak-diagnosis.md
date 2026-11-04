# Thread / abandon leak diagnosis (plan only)

**Status:** Diagnosis + fix plan — **no product code changes in this PR.**  
**Repo:** `cryptoreporthub/subnet-dashboard`  
**Prod context:** Fly 1GB VM, web (Uvicorn) + inline or dedicated worker (`RUN_MODE=worker`).  
**Related:** #1552 (orphaned resolver vs revived scheduler overlap), #1558 / PR #1538 (`MALLOC_ARENA_MAX=2` RSS containment — does **not** stop thread accumulation from abandoned work).

---

## 1. Executive summary

Production captures show the **worker** holding ~21–26 threads at boot and ~22–24 steady, while **web** reports ~8 threads at boot. `MALLOC_ARENA_MAX=2` cut worker RSS (~500 → ~285 MiB) by shrinking glibc arenas; **thread count and abandon-orchestration bugs are unchanged.**

The dominant leak class is **not** forgotten daemon tick threads (those are bounded and named). It is **ephemeral `ThreadPoolExecutor` instances** created per resolver cycle, daily-pick tick, desk snapshot, etc., combined with **`future.result(timeout=…)` + `pool.shutdown(wait=False, cancel_futures=True)`**. That pattern **returns on timeout without joining** the worker thread; `cancel_futures` only drops **queued** work, not a thread already running Python code. Repeated timeouts stack **orphan threads** until they finish (often minutes for resolver/scoring). **Revive** paths (`revive_prediction_resolver_scheduler`, loop stall guard, boot status-aware revive) can **start a new scheduler generation** while orphans from the previous generation still run — the #1552 overlap class.

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
| `resolver_scheduler.py:864–958` | `resolver-cycle-work` | `fut.result(timeout=timeout)` | `_abandon_inflight_cycle`; `pool.shutdown(wait=False, cancel_futures=True)` | **Yes** — generation bump + lock replace; orphan keeps running until `_run_refresh_cycle` finishes. Next `_tick` can submit while `abandoned_live>0`. Revive (`1393–1474`) **stop+start** scheduler while orphan may live. | **VERIFIED** (code + `tests/test_resolver_revive.py`, `tests/test_phase3_mid_guards_orphan_revive.py`) |
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
| Next scheduled `_tick` | Can run while `abandoned_live > 0`; may skip if `_inflight_future` not done | **Yes** | **VERIFIED** |
| `revive_prediction_resolver_scheduler` | May `stop()` + `start_prediction_resolver_scheduler` + synchronous `run_once()` while orphan still running | **Yes (#1552 class)** | **VERIFIED** |
| `stop()` | Sets `_active=False`, `cancel_job` — **does not join** tick or pool worker | Orphan survives stop | **VERIFIED** |

Telemetry: `log_lifecycle("abandon"|"timeout")`, `log_heavy_job_rss("prediction_resolver"|"prediction_resolver_worker")`, resolver cycle summary `abandoned_live` in soul_map. **VERIFIED**

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

The test mirrors resolver abandon: each cycle creates `ThreadPoolExecutor(max_workers=1, thread_name_prefix="resolver-cycle-work")`, submits `sleep(2)`, waits `0.05s`, then `shutdown(wait=False, cancel_futures=True)`.

| Metric | Baseline | After 8 sequential abandons | Rapid 8-cycle overlap |
|--------|----------|----------------------------|------------------------|
| `threading.active_count()` | 1 | 1 (+0) | N/A |
| `VmRSS` (kB) | 83596 | 83724 (+128) | N/A |
| Named `resolver-cycle-work` threads (peak) | 0 | 0 (orphans finished before scan) | **8 concurrent** |

**Interpretation (VERIFIED on this run):**

- Sequential abandons with 2s work and 5s post-wait did not raise **steady-state** `active_count()` — orphans exited before measurement.
- **Rapid** abandons (1s work, 0.01s timeout, 0.02s spacing) produced **8 simultaneous** pool worker threads — the production failure mode when resolver/pick timeouts recur faster than cycle duration (e.g. 360s resolver budget with overlapping retries every 1–2 min).
- RSS drift (+128 kB) is noise at this scale; prod leak is **thread stack + native allocations inside long resolver/scoring stacks**, not captured in a 3s micro-benchmark.

---

## 6. Ranked fix options

| Rank | Option | Change size | Risk | Prod proof |
|------|--------|-------------|------|------------|
| **1** | **Single process-wide bounded executor** for resolver / daily pick / desk snapshot (max 1–2 workers each or one shared “heavy-job” pool); **reuse** instead of `ThreadPoolExecutor()` per cycle | Medium (~200–400 LOC) | Low–med — must preserve generation/cancel semantics | Log `threading.active_count()` + `threads=` in existing `log_heavy_job_rss` at **start/end** of each job; Fly metric or Axiom query on `rss-heartbeat` lines; compare thread count at resolver **cycle boundary** before/after deploy |
| **2** | **Cooperative cancellation** already partial (`_work_generation`, resolver `gen != self._cycle_generation`) — extend to **all blocking steps** (RPC, hydration, soul_map RMW) with periodic `is_cancelled()` checks | Medium–large | Med — missed check leaves hang | Stage trace + `abandoned_live` should **stop increasing** under forced timeout tests |
| **3** | **Subprocess isolation** for resolver cycle / score snapshot build (`subprocess.run` with hard kill on timeout) | Large | Med — IPC, volume paths, startup cost | Process exit guarantees thread reclamation; measure worker RSS/threads after injected 360s hang |
| **4** | **Single-flight lock** at scheduler level: do not `schedule_in_seconds` next tick until prior `_inflight_future.done()` **and** `abandoned_live == 0` | Small | Med — reduces throughput; may stall learning loop | Fewer overlapping `resolver-cycle-work` threads in `ps -L` / thread dump |
| **5** | **Revive gating (#1552):** refuse `revive_*` until orphan count zero or force-kill via subprocess supervisor | Small–medium | Low for false revive; needs orphan visibility | No double scheduler generation in logs (`resolver lifecycle event=start` while `abandoned_live>0`) |
| **6** | **Join with cap** (`shutdown(wait=True)` + short grace) — **dangerous** on Fly (blocks tick thread) | Small | **High** — wedges health | Not recommended alone |
| **7** | Further **`MALLOC_ARENA_MAX` / malloc_trim** tuning | Small | Low | RSS only — **proven insufficient** for threads (#1558) |

**Existing logging to reuse:** `internal/process_memory.log_heavy_job_rss` (includes `threads=`), `log_lifecycle` patchd events, resolver cycle summary fields `abandoned_live`, score snapshot `completed-after-abandon` log line.

---

## 7. Recommendation (plain language)

The app starts long chores (grading predictions, building scores, daily picks) on background threads, then gives up waiting when they take too long — but **never actually stops those chores**. Each time that happens, it spins up another helper thread while the old one is still running, so thread count creeps up on the worker until memory pressure or a restart. Fixing `#1558` trimmed unused memory from the allocator but did not change this behavior. The safest practical fix is to **stop creating a new thread pool for every cycle**, use **one small pool per job type** (or run the heaviest work in a **subprocess you can kill**), and make long loops **check a cancel flag** so timed-out work exits quickly instead of lingering behind a “revived” scheduler.

---

## 8. Suggested implementation order (when approved)

1. Add **thread count + `abandoned_live`** to structured metrics at resolver/pick/snapshot boundaries (read-only observability PR).
2. Refactor **resolver** to shared 1-worker executor + explicit orphan counter gate for revive (**#1552**).
3. Align **daily pick** and **desk snapshot** with the same pattern.
4. Re-evaluate **score_snapshots** global write executor: caller timeout should either cancel build (generation) or move build to subprocess.
5. Load test: repeated forced `RESOLVER_CYCLE_TIMEOUT_SECONDS=1` in staging; accept criteria: **steady thread count**, `abandoned_live` bounded.

---

## 9. Out of scope for this PR

- Application fixes, Fly deploy, workflow edits, merge to main.
- PR #1561 / branch `cursor/daily-pick-morning-plan-3740` (untouched).
