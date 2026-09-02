# Full-history root-cause sweep (findings only)

**Date:** 2026-09-02  
**HEAD at sweep:** `4fe565e1` (`feat(resolver): additive read-path diagnostic logging for prod capture (#1156)`)  
**Repo:** `cryptoreporthub/subnet-dashboard`  
**Scope:** read-only git + GitHub + Ditto. No production mutation, no code fix, no deploy.

Lens applied after the fact: upstream-first, topology (web vs worker), timeout floors, semantic HOLD vs transport error. See `AGENTS.md` operational discipline.

## Method limits (exhausted, not shortcut)

- **Not year-plus on `main`.** `git rev-list --count HEAD` = 2310. First commit on current `HEAD` lineage: `528ba62c` (2026-07-08). June history (`942ffbe1` 2026-06-09 initial) exists on `--all` (3449 commits) but `942ffbe1` is **not** an ancestor of `HEAD`. Pre-rebuild Flask/Gunicorn era is only partially reachable.
- GitHub issue search for HOLD/timeout is incomplete in `gh issue list --search` (many incidents live in PR bodies and MC logs instead). Issues cited below were opened by number or found in PR search.
- Runtime resource (which lock/CPU/GIL is exhausted) remains **unproven** without Patch D capture — same caveat as occupancy receipts `cursor-agents-communication/ditto-occupancy-e1e2-receipts-2026-08-30.md`.

---

## Ranked removals / weakenings (step 3)

Classifications: **confirmed** = git+PR body agree; **strong** = code+dates+symptom match, initiating cause still unproven; **plausible** = same shape, weaker coupling; **unweighed removal** = no contemporaneous discussion that the original failure was gone.

### 1. Daily-pick overlap guard → generation tokens (confirmed)

| | |
|---|---|
| **Added** | PR **#906** squash `fe002bb0` (on `HEAD`; 2026-08-13T12:09:32Z). Pre-squash slice `8f158de0` is **not** an ancestor of `HEAD`. `_work_thread.is_alive()` skip: `"daily pick tick skipped; previous worker still running"`. Stated reason: timed-out pump/daily-pick work accumulated daemon threads; Fly 8081 health timed out; web showed worker volume unavailable. |
| **Removed** | `1eb0a6bf` in PR **#1008** merged 2026-08-20T22:59:07Z (`d3e331aad`). PR body names `_work_thread.is_alive()` as the bug (skip-forever after 90s timeout) and replaces it with `ThreadPoolExecutor` + `fut.result(timeout=…)` + `shutdown(wait=False, cancel_futures=True)` + generation tokens. Test renamed to `test_daily_tick_timeout_then_immediate_retry_starts_new_worker`. |
| **Intent** | **Intentional incomplete replacement**, not silence. PR body claims “no skip-forever path.” Tokens discard **results**; they do not bound **lifetime or side effects**. `docs/daily-pick-scheduler-fix-deploy.md` admits Python cannot kill abandoned threads. |
| **Amplifiers** | **#1009** (`4428617b`, 2026-08-21): timeout still treated disk HOLD as `today_ready` → deferred to next UTC slot; fix forces 15-min retry (more overlapping generations). **#1021** (`e7b9d9f1`, 2026-08-22): parallel scoring; PR cites **1,712s** wall vs **90s** budget. **#1022** (`a8d690ef`): global TMC single-flight lock with no acquisition deadline. |
| **Symptoms** | Busy pick handler, HOLD writes from abandoned workers, GET/health starvation. Same family as #906’s original failure. |
| **Would refute** | Proof that `shutdown(cancel_futures=True)` joins the callable, or runtime showing a single generation and no TMC wait. Stdlib + #1008 comments refute the first. Patch D still open for the exact resource. |
| **Fix (describe only)** | Complete #1008’s stated goal: next tick starts **and** previous work is occupancy-bounded (join-with-deadline / true single-flight). Do **not** blindly restore #906 (reintroduces skip-forever). |

### 2. `_last_resolver_tick` deleted; three importers left (confirmed recovery defect)

| | |
|---|---|
| **Added** | Soul-map / cross-process tick helper: `40a6dc27` (2026-07-26), used by stall-guard `d03a3789` (2026-08-09), resolver revive **#1051** `59abaf0a` (2026-08-26). Doctrine: `.agents/memory/resolver-and-learning-availability.md` — web must not trust in-process scheduler. |
| **Removed** | PR **#1090** / `98677e74` (2026-08-28T07:33:16Z) — “loop_health replaces `_last_resolver_tick` soul_map heuristics with `_resolver_liveness_view`.” Function deleted in `6e211754`. **Importers not updated:** `internal/loop_stall_guard.py`, `internal/council/resolver_scheduler.py`, `internal/learning/routes.py` (grep at `98677e74`). |
| **Intent** | Hour-slot / #1079 migration. **No** re-derivation that stall-guard revive still imported the symbol. **Regression by omission** (unweighed vs those callers). |
| **Restore** | **#1151** / `44fd2fb7` (2026-09-01) — compat shim. Does not prove initiating resolver stall. |
| **Symptoms** | Resolver going silent / no automatic stale-tick revive. Matches #1112 (closed via #1151). Initiating `cycle_timeout_180s` still unknown (Ditto 2026-09-01: timeout path **does** re-arm). |
| **Would refute** | ImportError-free probe returning age before #1151 — contradicted by missing `def` at `6b29d3eb`. |

### 3. LivenessTracker AST gate vs leftover `_running` / start skip (strong)

| | |
|---|---|
| **Added** | **#1028** (2026-08-23): `tests/test_no_handrolled_liveness.py` forbids `_running` / `_last_run_ok` / `_last_run_at` in `*scheduler*.py`. |
| **Weakened** | Migrations **#1087/#1090/#1095** removed flags the AST gate forbade. **#1126** (2026-08-29): `ensure_pump_ladder_scheduler` still read `_scheduler._running` → `AttributeError` (Sentry 2026-08-28 19:26:40Z). **#1128**: `DailyPickScheduler.start` / hour start returned “already running” when persisted lifecycle=`started` **without** `schedule_in_seconds` — jobs **absent from `/jobs`** while health painted `ok`. |
| **Intent** | Honest derived liveness. Call-site graph incomplete (blast-radius miss). |
| **Symptoms** | Silent schedulers, HOLD/ok mismatch (semantic vs structural: lifecycle `ok` ≠ job armed). |
| **Would refute** | `/jobs` showing DateTriggers through the #1087–#1128 window. Step 0 on machine `7841024b3712e8` pid 648 is cited as jobs absent. |

### 4. Timeout-abandon without join (strong; same Python fact as #1)

- Resolver: **#1100** `70d5c3b0` — generation lock release on `cycle_timeout_*` so `cycle_in_flight` does not wedge; orphan thread keeps running.
- Score snapshots: **#1017** — occupancy was cleared on waiter timeout; second full-universe score started. Fix keeps occupancy until write finishes. **#1113 still OPEN:** “cycle timeout abandons unjoined pool threads (`write_timeout_480s` + resolver `cycle_timeout`)”.
- **Timeout floors:** 90s daily-pick, 180s resolver (`fly.toml` `RESOLVER_CYCLE_TIMEOUT_SECONDS`), 480s snapshot write, 8s pick handler / homepage / evidence wait. Bimodal upper mode = these ceilings, not “slow on average.”

### 5. Thread-pool cap #801 undone by fly.toml 24 (strong / unweighed)

- **#801** `413b1f17` (2026-08-04): `AIO_WORKER_POOL_SIZE` default **4** — “timed-out pick threads cannot exhaust the pool.”
- `ade027e7` (2026-08-10): `fly.toml` sets `AIO_WORKER_POOL_SIZE = "24"` (+ `MAX_IN_FLIGHT_REQUESTS = "48"`). Commit message is env concurrency / CSS / snapshot-guard — **does not re-verify** the #801 exhaustion case.
- `internal/request_executor.py`: dedicated pool default **4**, shared by learning-health and ops evidence (Ditto 2026-09-01). Timed-out sync work keeps the worker. Matches endpoint timeouts + `source=refreshing` without proving it is *the* stall.

### 6. Fly `/health` timeout 10s → 5s (plausible; wrong-layer)

- `c7e63d6e` (2026-07-13): timeout **10s**, grace 60s.
- `31f411d32` (2026-07-31): timeout **5s**, grace **90s**. Message: “fail health checks faster so a wedged machine is replaced sooner.” Treats proxy 503 as the bug.
- `085cba73` (2026-08-21) 5s→12s for GIL flap — **not an ancestor of `HEAD`**. Prod on main stayed at 5s (`git blame fly.toml` L30).

### 7. Misfire grace absorbing backlog (plausible; already named in the prompt)

- APScheduler DateTrigger default grace **1s**.
- `54805bb5` (2026-08-22): default **60s**.
- `2e5b27ab` / **#1131** (2026-08-29): **180s** so hour is not `EVENT_JOB_MISSED` while daily tick holds the executor 90s (prod: 1.35s late, grace=1). Fixes **missed re-arm**, not occupancy. Prompt’s template: grace vs occupancy.

### 8. Resolver cycle timeout 120→180 (plausible; mitigation)

- Cap added `cbe79d07` (2026-07-27) 120s.
- **#1107** `24488f4e` (2026-08-28): 180s. `fly.toml` comment: “prod stall ~16:56Z — cycle_timeout_120s wedge recurring; bump cap.” MC log: do not bump higher if it wedges again. Absorbs duration; does not bound the cycle’s side effects (#4).

### 9. Readiness busy → longer wait + stale cache (plausible)

- **#730** (2026-08-02): readiness wait 4s→8s; serve last-good instead of naked busy; resolver `heavy_job_busy` did not bump `_last_run_at`. Quietens **busy** string; build cost unchanged.

### 10. Worker-split v2 then rollback (confirmed, different family)

- Enablement `#572` / GHA `e728dce3`; rollback `8a3bad9f` (2026-07-31): stop forcing broken split_v2. Board: web→worker private HTTP unreachable. **#710** `e6ca90fb`: hot-path TaoStats `time.sleep` on event loop (py-spy). Topology + blocking I/O, not the #906/#1008 chain.

### Live-subnets overlap guard — still present

`0da001c9` (2026-08-12) skip-while-`prev.is_alive()` remains in `internal/live_subnets.py:204`. Not removed. Contrast with daily-pick.

### Ranks 2/3 contain-90s then revert

`4e27bead` reverts contain-abandon — **not** an ancestor of `HEAD`. Did not land on current main.

---

## Config / infra drift (step 4)

| Date (UTC) | Commit / PR | Old → new | Stated reason | Flag |
|---|---|---|---|---|
| 2026-07-14 | `321a678d` | ~256MB → shared-cpu-1x **1gb** | health critical; proxy no candidate | emergency |
| 2026-07-31 | `31f411d32` | health timeout **10s→5s** | replace wedged machine faster | symptom-layer |
| 2026-08-04 | #801 `413b1f17` | AIO pool default **4** | stop pick-thread exhaustion | later undone |
| 2026-08-10 | `ade027e7` | AIO **24**, MAX_IN_FLIGHT **48** | concurrency + APP_BASE_URL | **never revisited vs #801** |
| 2026-08-10 | `285255e7` | duplicate MAX_IN_FLIGHT key; keep 48 | TOML parse | |
| 2026-08-13 | #906 topology | dedicated worker CPU `561d6979` performance-1x | split worker | later v1 inline |
| 2026-08-20 | `0769f631` (#1008 bundle) | web **shared-cpu-2x** | CPU starvation emergency | **on HEAD**; superseded |
| 2026-08-22 | #1024 `9e98a333` | **performance-1x / 4gb** | pin so deploy does not revert to 2x/2gb OOM | current `fly.toml`; emergency never “unwound” |
| 2026-08-21 | `085cba73` | health **12s** | GIL flap | **not on HEAD** |
| 2026-08-22 | `54805bb5` | misfire grace **60s** | missed one-shots | |
| 2026-08-28 | #1107 | resolver cycle **120→180s** | recurring cycle_timeout_120s | mitigation |
| 2026-08-29 | #1131 `2e5b27ab` | misfire **180s** | hour MISSED during 90s daily | grace vs occupancy |
| (current) | `fly.toml` | `LOOP_STALL_GUARD_KILL` **unset** | policy KILL=0; code default `True` (`internal/loop_stall_guard.py:68`) | **config/policy split** |

`WORKER_HEAVY=essential`, `INLINE_WORKER=1`, `BACKGROUND_ON_WEB=off` (#452 restored off after #437 set essential on 1GB web).

---

## Schema / persistence (step 5)

- `internal/learning/predictions_store.py` `load_predictions(persist=True)` runs `_migrate_phases` / `_migrate_expert_labels` / `_migrate_evidence` and may rewrite `predictions.json` on **read** (`eb114684`, `907b1b12`). Evidence builders call this on the request path (Ditto 2026-09-01) — timeout cancel does not stop the rewrite. Classic self-inflicted: request-thread + migrate-on-read.
- **#1090** field replacement (`resolver.running` / `last_ok` → tracker `status`/`lifecycle`/`last_success_at`). Consumers that still expected the old shape got the **degraded fallback** (`running=false`, `last_ok=null`) which was misread as unscheduling (upstream invariant: consumer/probe vs producer).
- Soul-map lifecycle written beside `last_cycle` in **#1051**; web health can show `started`/`ok` while `/jobs` empty (**#1128**) — persisted meaning drifted from “job armed.”
- No evidence in this sweep of a silent SQLite FK drop. JSON files remain the store.

---

## Dependencies (step 6)

| Pin | History | Changelog / behavior |
|---|---|---|
| `apscheduler==3.10.4` | `d7f2cc21` B3 (2026-07-14); **no version bump** in `requirements.txt` since | Default DateTrigger `misfire_grace_time=1` (APScheduler 3.x). We papered this in app code (60s then 180s), not a library bump. |
| `fastapi==0.112.4` / `uvicorn[standard]==0.31.1` | pinned `6cd3b552` / `f515740b`; Flask→FastAPI `9faaf42b` (2026-06-26) on `--all` | Foundation change, not a silent minor bump. |
| `starlette<1.0.0` | `1fe1e954` then later unpinned in current `requirements.txt` (only fastapi/uvicorn/httpx/apscheduler listed at top) | Not tied to current stalls. |
| No APScheduler major bump found | — | Timeout/thread lifecycle changes in **our** wrappers, not upstream 4.x. |

---

## “Fix that fixed the wrong thing” (step 7)

| Episode | Merged “fix” | What it actually changed | Recurrence |
|---|---|---|---|
| #906 worker 8081 timeout | overlap skip + essential-worker gate | Occupancy for daily-pick | Reopened by #1008 |
| #1008 orphan skip-forever | abandon + new generation | Results gated; workers not | HOLD/busy ~9d later (receipts: merge 2026-08-20, incident ~2026-08-30 00:15Z) |
| #1009 today_ready | 15-min retry | More ticks vs stuck slot | Convoy with orphans |
| #1021 parallel fetch | 4 workers | Faster in theory; 2× slower in A/B | #1022 lock |
| #1022 TMC single-flight | one lock, no deadline | Stops herd; can convoy | Patch D unproven |
| #730 busy readiness | 8s wait + stale report | Fewer naked `busy` | Build still expensive |
| #1107 180s | longer cycle cap | Fewer `cycle_timeout_120s` strings | Stall can last 180s; #1113 orphans |
| #1131 misfire 180s | hour not MISSED | Job kept | Occupancy unchanged |
| 31f411d32 health 5s | faster Fly replace | More 503 flaps under GIL | 12s fix never on main |
| #1090 registry lookup | delete helper | Health schema honest | Stall-guard dead until #1151 |
| #801 pool=4 | cap executor | Then fly.toml 24 | Shared REQUEST_EXECUTOR theory |

Semantic vs structural: treating HOLD as “the site is down” mixed domain abstention with handler-busy timeouts. HOLD-from-abandoned-write is structural; HOLD-from-council is semantic.

---

## Incident vs removal timeline (step 8)

Approximate; dates are merge/commit unless noted as prod.

```
2026-07-24  #452 BACKGROUND_ON_WEB=off; destroy orphan workers
2026-07-26  loop_health + _last_resolver_tick
2026-07-27  resolver 120s cycle timeout; snapshot write timeout
2026-07-31  split_v2 rollback; health timeout 10s→5s; #698/#710 event-loop wedges
2026-08-02  #730 readiness busy cosmetic; #888 hydrate-on-miss (graded:0)
2026-08-04  #801 AIO pool=4
2026-08-09  loop stall guard added (KILL default True in code)
2026-08-10  AIO pool fly.toml=24  ← weeks before occupancy saga
2026-08-12  live_subnets is_alive overlap (kept); uptime #895
2026-08-13  #906 overlap guard LIVE
2026-08-20  #1008 removes guard + VM 2x   [9d before 08-30 busy/HOLD]
2026-08-21  #1009 15-min retry; #1017 snapshot occupancy
2026-08-22  #1021 nested pool; #1022 TMC lock; VM 4GB; misfire 60s
2026-08-23  #1028 AST liveness gate
2026-08-26  #1051 resolver revive; #1058 hydrate starvation incident
2026-08-27  #1072 site unhealthy; liveness migrations
2026-08-28  #1090 deletes _last_resolver_tick; #1100 abandon resolver;
            #1107 180s; prod stall ~16:56Z; soak restart 18:52:52Z
2026-08-29  #1112 filed (dead import); #1113 unjoined threads OPEN;
            #1126/#1128 start-path / _running leftovers; misfire 180s
2026-08-30  occupancy receipts; rank-1 single-flight; ranks 2/3 reverted off-main
2026-09-01  #1151 shim restore; pump bound snapshot #1147
2026-09-02  #1156 read-path INFO diagnostics (prod may drop INFO)
```

Slow-burn: **#801→pool 24 (6 days)** before later hydrate timeouts; **#906→#1008 (7 days)** then **#1008→08-30 incident (~9 days)**; **#1090→#1112 (~1 day)** faster because revive is a probe path.

---

## Best-supported recurring pattern

**Confidence: strong (not a single confirmed root for every incident).**

The recurring mechanism is **incomplete replacement of an occupancy/liveness contract**: a later PR removes or forbids the old primitive (`is_alive` skip, `_last_resolver_tick`, `_running`) while substituting something that looks equivalent (generation tokens, LivenessTracker, registry view) but does not preserve **worker lifetime**, **job arming**, or **all callers**. Timeout floors then convert unbounded work into exact 90s/180s/480s/8s/5s modes; grace and cap bumps make the symptom rarer without restoring occupancy.

There are **at least three rhyming threads**, not one:

1. Daily-pick occupancy (#906→#1008→#1009→#1021→#1022) — confirmed code chain; resource unproven.
2. Resolver **recovery** (#1090 importers) — confirmed; **initiating** timeout cause unproven (heavy gate / executor / JSON read hang).
3. Liveness migration call-site misses (#1126/#1128) — confirmed AttributeError / missing DateTrigger.

**What would move this to confirmed-unifying:** one Patch D window showing the same blocked primitive (e.g. TMC lock or REQUEST_EXECUTOR saturation) under daily-pick busy **and** resolver `cycle_timeout_180s` **and** evidence 8.0s. Absent that, do not merge the three into one story.

**Described fix (not implemented):** (a) occupancy-complete #1008, not restore #906; (b) keep shim + stall-guard on registry age; (c) pin `LOOP_STALL_GUARD_KILL=0` in `fly.toml` if policy is KILL=0; (d) treat 8.000/90/180 as floors in diagnosis; (e) mutation-test + 3-cycle soak on any scheduler patch.

---

## Checked, nothing (do not re-walk)

- **Deleted test files** (`git log --diff-filter=D -- tests/`): empty sample; overlap test was **renamed** in #1008, not deleted.
- **APScheduler library bump:** none; grace is app-level.
- **Live-subnets `is_alive` overlap:** still in tree (`internal/live_subnets.py:204`).
- **SQLite FK / schema constraint removals:** none found on scheduler/resolver paths.
- **#1008 ranks 2/3 contain commit `4e27bead`:** not on `HEAD`.
- **Health 12s `085cba73`:** not on `HEAD`.
- **Flask/Gunicorn year-plus:** not on `HEAD`; rebuild starts 2026-07-08.
- **Circuit breaker #698:** still in `fly.toml` (`WORKER_PROXY_CIRCUIT_OPEN_SECONDS = "30"`); v1 inline makes proxy a legacy shape, not a new removal.
- **INFO vs WARNING on Fly:** diagnostic gap (1B capture), not a protection removal.
- **External infra / Fly platform outage as primary:** every cited incident has a matching self-inflicted diff in-window; that does not prove zero platform contribution, only that we did not need one to explain the code.
