# F02 — Replit fix-list standalone static review

- Pin: `ce3d820013d45577333ac8aada8c0d9e97c54129` (verified: `git cat-file -t` → `commit`; `git rev-parse <sha>^{commit}` → same SHA).
- Read method: every quote below fetched this session via `git show <pin>:<path> | nl -ba` from the git object DB — no workspace-snapshot carry-over.
- Working tree at read time: untracked only — `cursor-agents-communication/mission-control-log.md`, `data/predictions.json.lock`, `data/price_cache.json.lock`, `data/soul_map.json.lock`. Marked UNVERIFIED/out of scope per instructions; no tracked modifications; untracked files not used as evidence.
- No source or F02 document edits were made. No tests, audits, deployments, runtime checks, or production probes were run.

## 1. Root mismatch and source-path correction — VERIFIED

`git show <pin>:internal/loop_health.py` → `fatal: path 'internal/loop_health.py' does not exist in 'ce3d820013d45577333ac8aada8c0d9e97c54129'` (exit 128). The probe is `internal/learning/loop_health.py`. VERIFIED.

Probe fallback chain, `internal/learning/loop_health.py:124–153`:

```python
   124	def _snapshot_age_seconds(
   125	    path: Optional[str] = None,
   126	    soul_path: Optional[str] = None,
   127	) -> Optional[float]:
   128	    snap_path = path or SCORE_SNAPSHOTS_PATH
   129	    try:
   130	        from internal.council.score_snapshots import snapshot_age_seconds
   131	
   132	        age = snapshot_age_seconds(snap_path)
   133	        if age is not None:
   134	            return age
   135	    except Exception:
   136	        pass
   137	    try:
   138	        mtime = os.path.getmtime(snap_path)
   139	        return max(0.0, _utcnow().timestamp() - mtime)
   140	    except OSError:
   141	        pass
   142	    # Cross-process: worker may have written cycle summary before file flush.
   143	    try:
   144	        soul = _load_raw(soul_path or SOUL_MAP_PATH)
   145	        sched = soul.get("score_snapshot_scheduler") or {}
   146	        last = sched.get("last_cycle") if isinstance(sched, dict) else None
   147	        if isinstance(last, dict) and last.get("run_at"):
   148	            tick = _parse_iso(last.get("run_at"))
   149	            if tick is not None:
   150	                return max(0.0, (_utcnow() - tick).total_seconds())
   151	    except Exception:
   152	        pass
   153	    return None
```

Returns `None` only if all three sources fail. VERIFIED.

Guard-side probe import with warning, `internal/loop_stall_guard.py:71–79`:

```python
    71	def _snapshot_age_seconds() -> Optional[float]:
    72	    """Age in seconds of score_snapshots.json (None if unknown)."""
    73	    try:
    74	        from internal.learning.loop_health import _snapshot_age_seconds as _age
    75	
    76	        return _age()
    77	    except Exception as exc:
    78	        logger.warning("loop stall guard: snapshot age probe failed: %s", exc)
    79	        return None
```

VERIFIED.

Essential-mode gate, `internal/background_boot.py:542–550`:

```python
   542	    # Optional full-universe jobs stay off the essential worker. They can hold
   543	    # the GIL for long periods and compete with the worker's HTTP health port.
   544	    if heavy:
   545	        _warm_judges_cache()
   546	        _start_score_snapshot_scheduler()
   547	        _start_pick_audit_scheduler()
   548	        _start_outcome_snapshot_scheduler()
   549	        _start_calibration_snapshot_scheduler()
   550	        _start_dev_radar_github_scheduler()
```

VERIFIED. The GIL/health-port wording is a source-stated hypothesis, not measured evidence — agreed.

Essential-mode test, `tests/test_background_boot.py:104–145`:

```python
   104	def test_worker_essential_starts_pump_snapshot_but_skips_heavy_jobs(monkeypatch):
   ...
   137	    for name in (
   138	        "_warm_judges_cache",
   139	        "_start_score_snapshot_scheduler",
   140	        "_start_pick_audit_scheduler",
   141	        "_start_outcome_snapshot_scheduler",
   142	        "_start_calibration_snapshot_scheduler",
   143	        "_start_dev_radar_github_scheduler",
   144	    ):
   145	        getattr(__import__("internal.background_boot", fromlist=[name]), name).assert_not_called()
```

Asserts `_start_score_snapshot_scheduler` is not called in essential mode (`WORKER_HEAVY` set to `essential` at `:106`). VERIFIED.

Committed config, `fly.toml`:

```toml
    39	  # essential = pump/resolver/whale on worker; full enables live-subnet sync (heavier).
    40	  WORKER_HEAVY = "essential"
    82	  SCORE_SNAPSHOT_MAX_SUBNETS = "40"
    83	  SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS = "480"
   118	  WORKER_HTTP_PORT = "8081"
   134	[[vm]]
   135	  size = "shared-cpu-2x"
   136	  memory = "1gb"
   137	  processes = ["web"]
```

All VERIFIED as committed values. Agreed: a single `[[vm]]` stanza does not establish the deployed machine count, and none of these prove effective runtime configuration.

`immediate` flag, `internal/council/score_snapshots.py:475–486`:

```python
   475	    def start(self, immediate: bool = False) -> Dict[str, Any]:
   476	        if not self._is_registered():
   477	            return {"started": False, "reason": "not registered"}
   478	        already = self.liveness.snapshot().get("lifecycle") == "started"
   479	        self.liveness.start()
   480	        if immediate:
   481	            threading.Thread(target=self._tick, daemon=True, name="score-snap-tick").start()
   482	        else:
   483	            # After pick schedulers; full score is the heavy job.
   484	            # Persisted lifecycle=started is not proof a DateTrigger is armed
   485	            # (new process generation after prior boot).
   486	            schedule_in_seconds(JOB_ID, self._tick, SCORE_SNAPSHOT_FIRST_DELAY_SECONDS)
```

VERIFIED: `immediate=True` starts a tick thread after `start()` succeeds; it does not bypass the registration gate (`:476–477`).

**F1 agreement.** Do not broaden `if heavy:` — that would also start judges cache, pick-audit, outcome, calibration, and dev-radar jobs (`background_boot.py:545–550`). If F1 is approved, isolate `_start_score_snapshot_scheduler()` behind a narrow separate condition and update the essential-mode test to expect exactly that scheduler while retaining the "not called" assertions for the other five. If F1 is declined, treat the producer as not expected in that mode and design the guard's stale-age/missing-age response accordingly.

## 2. F2 — comment-only correction — VERIFIED

`internal/worker.py:108–111`:

```python
   108	    # Loop stall guard (loop-stall-guard commit d03a3789): watch the pump desk
   109	    # snapshot age; if it stays stale across consecutive checks, revive in place
   110	    # then exit so the supervisor restarts the worker fresh. Must stay wired in
   111	    # alongside the scheduler self-heal below.
```

`server.py:275–277`:

```python
   275	            # Loop stall guard: watches pump desk snapshot age and resolver tick
   276	            # age; exits the worker process when both stay stale so the Fly
   277	            # supervisor restarts it fresh (re-runs start_background_workers).
```

Both comments misstate the guard (it watches the council score-snapshot age; "pump desk" is wrong, and exit is driven by snapshot age alone). Guard separation, `internal/loop_stall_guard.py`:

```python
   163	        if resolver_age is not None and resolver_age > MAX_RESOLVER_AGE_SECONDS:
   164	            logger.warning(
   165	                "loop stall guard: resolver tick stale (age=%ss, threshold=%ss) — warn only",
   166	                int(resolver_age),
   167	                MAX_RESOLVER_AGE_SECONDS,
   168	            )
   169	
   170	        if (
   171	            resolver_age is not None
   172	            and resolver_age > RESOLVER_REVIVE_AFTER_SECONDS
   173	            and not resolver_revived
   174	        ):
   175	            resolver_revived = True
   176	            _try_revive_resolver()
```

and `:178–217` (score-snapshot age drives the strike counter and the `os._exit(1)` at `:217`). Separate env-overridable thresholds at `:58–64`:

```python
   58	MAX_RESOLVER_AGE_SECONDS = max(
   59	    1800, _env_int("LOOP_STALL_GUARD_MAX_RESOLVER_AGE_SECONDS", 21600)
   60	)
   61	RESOLVER_REVIVE_AFTER_SECONDS = max(
   62	    900,
   63	    _env_int("LOOP_STALL_GUARD_RESOLVER_REVIVE_SECONDS", 1800),
   64	)
```

VERIFIED. Agree: correct both comments, do not repoint the guard.

## 3. F3 — missing age is unknown, not healthy — VERIFIED

`internal/loop_stall_guard.py:178–181`:

```python
   178	        if age is None:
   179	            consecutive_stale = 0
   180	            logger.info("loop stall guard: no snapshot age signal (boot/feature-off), resetting")
   181	            continue
```

VERIFIED: `None` resets the stale counter at INFO — not evidence of producer health. A prior snapshot file or soul-map cycle record still yields a numeric age (`learning/loop_health.py:137–153` above), so `None` is not the inevitable essential-mode steady state. Probe-import failure also reaches `None` but logs a WARNING (`:78`), so the two cases are distinguishable in logs. VERIFIED. The policy table (intentionally-disabled / expected-but-unregistered / no-first-artifact-yet / fresh / stale / revive-in-progress) is a required spec, not current behavior — agreed. Note the guard never checks whether snapshots are *expected* before evaluating a numeric stale age; if the scheduler is disabled but an old file remains, strikes still count, and the reviver can return `disabled`:

```python
   815	    if not _enabled():
   816	        return {"revived": False, "reason": "disabled"}
```

(`_enabled()` default "on": `score_snapshots.py:740–746` — `os.environ.get("SCORE_SNAPSHOT_SCHEDULER_ENABLED", "on")`), and a later strike can still reach the exit branch if the effective kill setting allows it (`:201–217`). VERIFIED.

## 4. Three separate decisions — VERIFIED

Stale-recovery already exists, `internal/loop_stall_guard.py:197–199`:

```python
   197	        if consecutive_stale == 1 and not revived:
   198	            revived = True
   199	            _try_revive()
```

Pinned line ranges in `internal/council/score_snapshots.py`:

- `:798–814` — reviver declaration/docstring: "Loop stall guard strike 1 calls this... Blocks on the guard thread for up to ``SCORE_SNAPSHOT_WRITE_TIMEOUT_SECONDS`` (default 600s) while ``run_once`` completes — not fire-and-forget."
- `:815–816` — `if not _enabled(): return {"revived": False, "reason": "disabled"}`.
- `:836–849` — `tick_in_progress = (_write_future_active() or _TICK_ACTIVE or bool(sched and sched._tick_active))` → returns `{"revived": False, "reason": "tick_in_progress", ...}`.
- `:855–860` — `start_out = start_score_snapshot_scheduler(immediate=False)` ... `tick_out = sched.run_once()`.

```python
   855	    start_out = start_score_snapshot_scheduler(immediate=False)
   856	    tick_out: Dict[str, Any] = {"ok": False, "error": "no_scheduler"}
   857	    with _lock:
   858	        sched = _scheduler
   859	    if sched is not None:
   860	        tick_out = sched.run_once()
```

- `:507–508` — `def run_once(...): return self._tick(reschedule=False)`.
- `:567–589` — `_tick()` checks `self._scoring_in_progress()` first (`:570`), then the heavy-job slot (`:580`); skip results `scoring_in_progress` (`:571`) and `heavy_job_busy` (`:582`).
- `internal/heavy_job_gate.py:18–30`:

```python
   18	@contextmanager
   19	def heavy_job_slot(name: str) -> Iterator[bool]:
   20	    """Acquire exclusive heavy-job slot; yield False if another job is running."""
   21	    global _holder
   22	    acquired = _lock.acquire(blocking=False)
   23	    if not acquired:
   24	        yield False
```

Non-blocking in-process lock, not a worker-mode check. VERIFIED.

- `:510–524` — `_scoring_in_progress()` returns True on in-memory write flags (`_scoring_write_in_progress() or _TICK_ACTIVE or self._tick_active`, `:511`) or a persisted cycle with `phase == "scoring"`, parseable `run_at`, and age < `SCORE_SNAPSHOT_STUCK_SECONDS` (`:518–524`); default 900 at `:32` (`SCORE_SNAPSHOT_STUCK_SECONDS = int(os.environ.get("SCORE_SNAPSHOT_STUCK_SECONDS", "900"))`). VERIFIED.

**Addition (source-verified, relevant to decision 2):** the module-level starter lazily constructs and registers a scheduler when none exists — `score_snapshots.py:749–756`:

```python
   749	def start_score_snapshot_scheduler(immediate: bool = False) -> Dict[str, Any]:
   750	    if not _enabled():
   751	        return {"started": False, "reason": "disabled"}
   752	    global _scheduler
   753	    with _lock:
   754	        if _scheduler is None:
   755	            _scheduler = ScoreSnapshotScheduler()
   756	    return _scheduler.start(immediate=immediate)
```

So in essential mode the guard's revive path can create, register, and start the producer without ever passing the `background_boot.py` gate — and because `start(immediate=False)` schedules a periodic tick (`:486`), a single successful revive leaves a registered periodic scheduler for the process lifetime. This supports Replit's "can attempt" framing and sharpens it: attempt ≠ success (the tick can still skip on `scoring_in_progress` or `heavy_job_busy`), and a declined F1 should explicitly decide whether the revive path may also enable the producer. Falsifier: env `SCORE_SNAPSHOT_SCHEDULER_ENABLED` off makes the reviver return `disabled` (`:815–816`).

All VERIFIED. Agree: startup registration, stale-age recovery, and no-age response are three independent decisions; gating only a new no-age escalation would leave the existing numeric-stale revive path unchanged.

## 5. Revive race and exit behavior — VERIFIED (with conditions)

- Latch consumed on attempt, `loop_stall_guard.py:197–199` (above): `revived = True` is set before `_try_revive()` runs; a failed attempt still consumes it. VERIFIED.
- Code defaults, `loop_stall_guard.py:53–68`: `ENABLED` True, `INTERVAL_SECONDS` max(30, 240), `MAX_SNAPSHOT_AGE_SECONDS` max(300, 5400), `MAX_RESOLVER_AGE_SECONDS` max(1800, 21600), `RESOLVER_REVIVE_AFTER_SECONDS` max(900, 1800), `CONSECUTIVE_CHECKS` max(1, 2), `BOOT_GRACE_SECONDS` max(60, 1500), `KILL_ENABLED` True. All env-overridable. Committed code defaults, not runtime values. VERIFIED.
- Race: `tick_in_progress` (`:836–849`) returns without refreshing; if the snapshot is still stale on the next check, `consecutive_stale` reaches 2 and `os._exit(1)` fires at `:201–217` while work is in progress — possible, conditioned on effective strike/kill settings and timing. A possible race, not a universal outcome. VERIFIED.
- Synchronous revive: `_try_revive()` (`:114–121`) calls `revive_score_snapshot_scheduler()` on the guard thread; the reviver calls `run_once()` synchronously (`:860`). While blocked there (up to the write timeout — code default 600 at `score_snapshots.py:33–35`, committed Fly value 480 at `fly.toml:83`), the guard loop cannot count another strike. VERIFIED. A run merely exceeding the 240s interval therefore cannot itself cause a kill while the guard thread is blocked in a revive.
- Caller timeout, `score_snapshots.py:439–447`:

```python
   439	        return fut.result(timeout=timeout)
   440	    except FuturesTimeoutError:
   441	        caller_abandoned.set()
   442	        logger.warning(
   443	            "score snapshot build timed out after %ds "
   444	            "(build continues in background)",
   445	            timeout,
   446	        )
   447	        return {"ok": False, "error": f"write_timeout_{timeout}s"}
```

A caller timeout does not stop the underlying build. VERIFIED. "Do not exit mid-write" would be behavior to add, not an existing guarantee. Agreed.

## 6. Worker supervision and `wait` — VERIFIED (command/ordering); UNVERIFIED (blocking)

`scripts/fly_web_entrypoint.sh` at the pin:

- Worker started in background, `:34–36`:

```sh
    34	  nice -n 10 env RUN_MODE=worker WORKER_HEAVY="${WORKER_HEAVY:-essential}" python -m internal.worker &
    35	  echo $! > "$INLINE_WORKER_PIDFILE"
    36	  echo "inline worker pid=$(cat "$INLINE_WORKER_PIDFILE")"
```

- Supervisor subshell, `:43–64`; heartbeat-stale branch:

```sh
    53	      elif ! python -c "from internal.worker_heartbeat import is_alive; import sys; sys.exit(0 if is_alive(max_age_seconds=180) else 1)"; then
    54	        echo "inline worker heartbeat stale (pid=$pid), restarting..."
    55	        kill "$pid" 2>/dev/null || true
    56	        wait "$pid" 2>/dev/null || true
    57	        rm -f "$INLINE_WORKER_PIDFILE"
    58	        need_restart=1
    59	      fi
    60	      if [ "$need_restart" = 1 ]; then
    61	        _start_inline_worker
    62	      fi
```

- Missing/dead-PID branch sets `need_restart=1` without kill/wait (`:51–52`); web exec at `:69` (`exec python scripts/run_web_with_guard.py`).

Verified: the `wait` at `:56` has no explicit timeout and its result is ignored; the stale path proceeds toward restart after it returns. UNVERIFIED: whether that `wait` actually blocks, how long, and the resulting restart timing (the worker is a child of the outer shell, while `wait` runs inside the backgrounded supervisor subshell — POSIX semantics for waiting a non-child are not established here). Agreed: do not claim the web process or machine restarts; the guard's `os._exit(1)` exits only its worker process, and runtime restart timing cannot be inferred from the script alone.

## 7. Proposed verification only — acknowledged, not run

All six proposed checks (F1 isolation test, no-age vs stale-age separation, disabled vs unregistered, in-progress/caller-timeout revive, GIL falsifier measurement, runtime env inspection) remain for a separately approved implementation/runtime task. Not performed.

## Corrections to Replit's review

None of Replit's citations were wrong; all quoted line ranges matched the pinned objects. Two refinements from this pass:

1. **Slot release timing:** `_tick` releases `heavy_job_slot` before `_tick_body` runs (`score_snapshots.py:588–589`: "release gate before ~127×2 scoring — holding it wedged resolver for hours"), so the busy-check only reflects the slot at that instant, not for the duration of scoring.
2. **Lazy registration (Section 4 addition):** the revive path can itself create and register the scheduler in essential mode (`:753–756`), and a successful revive leaves a periodic producer running (`:486`) — a mechanism the three-decision split should account for when F1 is declined.

## Runtime unknowns (unchanged by this review)

Effective production values of all env knobs (`WORKER_HEAVY`, `LOOP_STALL_GUARD_*`, `SCORE_SNAPSHOT_*`, `RESOLVER_*`), Fly machine env/secrets, deployed machine count, actual artifact ages, revive outcomes, guard exit history, heartbeat/kill/restart timing, and GIL behavior under scoring load. Nothing in this review infers production behavior from `fly.toml` or code defaults.
