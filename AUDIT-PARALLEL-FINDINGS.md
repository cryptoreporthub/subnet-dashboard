# AUDIT-PARALLEL-FINDINGS — cryptoreporthub/subnet-dashboard @ 44fd2fb7
Pinned HEAD: 44fd2fb761017108856b488584d06531ba28af21 (git rev-parse verbatim)
Workstreams: A=completed B=completed C=completed D=completed (D1/D2 after env provisioning of requirements-pinned deps)

## VERDICT TABLE
A1 CONFIRMED (atomic tempfile+os.replace; exception worker_heartbeat.py:29 direct open "w") — internal/council/daily_pick_engine.py:47-49
A1b NOT FOUND->CORRECTED (direct open(...,"w") sites all tmp+rename except heartbeat) — internal/worker_heartbeat.py:29
A2 CONFIRMED (WAL SQLite shared web+worker) — internal/fetchers/_sqlite.py:29
A3 PARTIAL (flock only in pick_score_cache) — internal/council/pick_score_cache.py:104
B1 CONFIRMED (coalesced flight; timeout HOLD synthesized in-memory, not persisted) — server.py:3100,3159
B2 PARTIAL (string CONFIRMED in worker_proxy.py; 422 NOT FOUND — worker_proxy returns 200-degraded) — internal/worker_proxy.py:427
B3 CONFIRMED (AIO_WORKER_POOL_SIZE=24 fly.toml:112; default executor + dedicated request executor) — server.py:364
C1 CONFIRMED (heartbeat=file JSON ts vs receipts=SQLite-derived) — internal/worker_heartbeat.py:42
C2 CONFIRMED (reschedule in _tick/_schedule_next; backoff on failure; no silent death) — internal/council/resolver_scheduler.py:292,294
C3 CONFIRMED (freshness=embedded aware ts, max_age 120s; NOT mtime) — internal/worker_heartbeat.py:42-50
D1 COMPLETED (145 failed, 2489 passed, 4 skipped, 5 warnings in 146.75s (0:02:26))
D2 COMPLETED (exit 1; 3 failed, 7 passed; wc -c=6533; sha256=e643e3e368b75ff41a8411c8492bd863ea6c6dcf8d83057e64ccf5d1b1046bc3)
D3 PARTIAL (1 genuine mixing point conviction_decay.py:55; 1 safe normalizer conviction_index:130-136; 1 UNVERIFIED accuracy_lift/measure.py:26)

## D1 PYTEST SUMMARY (verbatim)
145 failed, 2489 passed, 4 skipped, 5 warnings in 146.75s (0:02:26)

## D2 stall_guard_traceback.txt metadata
wc -c: 6533
sha256sum: e643e3e368b75ff41a8411c8492bd863ea6c6dcf8d83057e64ccf5d1b1046bc3
D2_EXIT=1

## VERBATIM SNIPPETS (each <=900 chars, cited)

### S1 A1 atomic write — internal/council/daily_pick_engine.py:45-52
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(records, f, indent=2)
    os.replace(tmp, path)


def _today_str() -> str:

### S2 A2 WAL — internal/fetchers/_sqlite.py:25-36

### S3 A3 flock — internal/council/pick_score_cache.py:100-110

def _with_file_lock(fn):
    os.makedirs(os.path.dirname(LOCK_PATH) or ".", exist_ok=True)
    with open(LOCK_PATH, "a", encoding="utf-8") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)



### S4 B1 timeout hold — server.py:3095-3112
    except Exception as exc:
        logger.warning("daily-pick/weighed failed: %s", exc)
        return {"shortlist": [], "error": str(exc)}


def _daily_pick_timeout_hold() -> Dict[str, Any]:
    """Busy/timeout hydrate payload — never a clean scheduler HOLD."""
    return _attach_daily_pick_meta(
        {
            "status": "timeout",
            "date": datetime.now(timezone.utc).date().isoformat(),
            "action": "HOLD",
            "reason": "pick handler busy — retry shortly",
            "pick": None,
        }
    )



### S5 B2 worker_proxy degraded — internal/worker_proxy.py:424-433
            "status": "degraded",
            "nodes": [],
            "edges": [],
            "detail": "Worker volume temporarily unavailable — trail will refill when the learning loop reconnects.",
            "path": path,
            **bot_contract(
                source="worker_heartbeat",
                degraded=True,
                mode="worker_unavailable",
                authoritative=False,

### S6 B3 pool — server.py:360-372

        start_background_workers()

    # ponytail: cap default asyncio thread pool — timed-out pick/weighed work can't exhaust all slots
    pool_cap = int(os.environ.get("AIO_WORKER_POOL_SIZE", "4"))
    aio_pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=pool_cap, thread_name_prefix="aio-web"
    )
    asyncio.get_running_loop().set_default_executor(aio_pool)

    yield
    if background_on_web() and background_boot_allowed():
        from internal.background_boot import stop_background_workers

### S7 C1/C3 is_alive — internal/worker_heartbeat.py:42-50
def is_alive(*, max_age_seconds: int = 120) -> bool:
    raw = read_heartbeat()
    if not raw or not raw.get("ts"):
        return False
    try:
        ts = datetime.fromisoformat(str(raw["ts"]).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        return age <= max_age_seconds
    except Exception:

### S8 C2 timeout/finally — internal/council/resolver_scheduler.py:480-500
            try:
                return fut.result(timeout=timeout)
            except FuturesTimeoutError:
                self._abandon_inflight_cycle()
                result = {
                    "ok": False,
                    "run_at": _now_iso(),
                    "resolved_now": 0,
                    "expired_now": 0,
                    "pending": 0,
                    "error": f"cycle_timeout_{timeout}s",
                }
                self._persist_cycle_summary(result)
                return result
        except BaseException:
            if not submitted:
                self._cycle_lock.release()
            raise
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


### S9 D3 mixing — internal/conviction_decay.py:43-56
def get_decay_state() -> Dict[str, Any]:
    """Return the current decay state for all mindmap nodes."""
    data = _load()
    nodes = data.get("nodes", {})
    # Compute decay values: conviction decays by 5% per day since last update
    now = datetime.now(timezone.utc)
    decayed: Dict[str, Any] = {}
    for netuid, node in nodes.items():
        conviction = node.get("conviction", 50.0)
        last_updated = node.get("last_updated")
        if last_updated:
            try:
                age = (now - datetime.fromisoformat(last_updated)).total_seconds()
                days = age / 86400.0

### S10 D3 safe normalizer — internal/conviction_index/__init__.py:125-137
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)




## WORKSTREAM A (findings-A-state.md)
# Workstream A — State Layer & Concurrency (commit 44fd2fb7)

## A1 — Atomic write pattern: CONFIRMED
tempfile+os.replace atomic writes throughout internal/ (grep "os.replace|tempfile"): internal/council/daily_pick_engine.py:49; resolver_scheduler.py:116-120; score_snapshots.py:115; pick_score_cache.py:98; resolver.py:166; price_reference.py:142-486 (os.fdopen+os.replace); +8 more.
A1b direct open(...,'w'): CORRECTED — initial single-quote grep returned zero; corrected grep found ~15 sites but ALL write to tmp then rename (e.g. daily_pick_engine.py:47 open(tmp,"w") -> :49 os.replace). EXCEPTION: internal/worker_heartbeat.py:29 `open(path,"w")` writes data/.worker_heartbeat directly (non-atomic truncate-in-place; reader can see partial/empty file).

## A2 — SQLite access: CONFIRMED
internal/fetchers/_sqlite.py:29 PRAGMA journal_mode=WAL; connect(timeout=10, check_same_thread=False); per-path threading.Lock + db_conn ctx mgr. internal/store/db.py:13-14 delegates. VOLUME_DB_PATH=data/volume_cache.db (internal/council/chain_client.py:36). Web+worker share WAL DB; busy timeout via connect(timeout=10).

## A3 — File locking: PARTIAL
flock ONLY in internal/council/pick_score_cache.py:104 (LOCK_EX) / :108 (LOCK_UN). No general inter-process lock on shared JSON; atomic rename (A1) is the only protection. worker_heartbeat.py has no lock.

## WORKSTREAM B (findings-B-request.md)
# Workstream B — Request Path & Latency (commit 44fd2fb7)

## B1 — /api/daily-pick: CONFIRMED
Route server.py:3159 (/weighed :3078). Coalesced single-flight (_coalesce_daily_pick_flight :3145): leader awaits asyncio.shield(aio) w/ PICK_READ_TIMEOUT; waiters shed to date-guarded stash on TimeoutError else _daily_pick_timeout_hold (:3100). _daily_pick_timeout_hold returns status="timeout"/action=HOLD/pick=None — synthesized in-memory payload, NOT persisted as scheduler HOLD; no lock/flag file. _daily_pick_pending_hold -> status="pending". _hydrate_daily_pick_lite: single JSON load + lite enrich (empty_whale_flow_badge("lite_read")), stashes raw pre-enrich copy so waiters shed to stash not busy-timeout payload.

## B2 — /api/pump-alerts 422: PARTIAL (string CONFIRMED; 422 NOT FOUND)
"Worker volume temporarily unavailable" originates internal/worker_proxy.py (:427,:452,:470,:498,:514,:531,:555,:570,:580,:595) but worker_proxy returns status_code=200 degraded JSONResponse — NOT 422; no status_code=4xx in worker_proxy. /api/pump-alerts server.py:2462 -> _fetch_pump_alerts_payload (file-backed ladder, sub-second). pump_tracker/routes.py:80-81 degraded text; tribunal_hero.py:500 reads detail. "422" in server.py only docstring :3163. Rate limit: internal/rate_limit.py slowapi, _STRICT_LIMIT="30/minute", default 120/minute, ENABLE_RATE_LIMIT=1; strict_limit only /api/mindmap/feedback (server.py:2240) + learning/routes.py:1170 — pump-alerts not strictly limited; no middleware converts repeated 422s to 403. _fly_client_ip trusts first XFF hop.

## B3 — AIO_WORKER_POOL_SIZE: CONFIRMED
fly.toml:112 "24"; server.py:364 default "4"; ThreadPoolExecutor(max_workers=pool_cap, prefix="aio-web") as default loop executor in lifespan (ponytail comment: timed-out pick/weighed work can't exhaust slots). internal/request_executor.py: REQUEST_WORKER_POOL_SIZE default 4 (min 2), dedicated REQUEST_EXECUTOR prefix="request-work" for council hero aggregation; to_thread_timeout = asyncio.wait_for(loop.run_in_executor(REQUEST_EXECUTOR, fn), ...). mount_load_shed + WorkerVolumeProxyMiddleware mounted.

## WORKSTREAM C (findings-C-health.md)
# Workstream C — Health & Observation Split (commit 44fd2fb7)

## C1 — Heartbeat vs receipts: CONFIRMED (split surfaces)
Heartbeat (file JSON): internal/worker_heartbeat.py touch_heartbeat writes data/.worker_heartbeat {pid, ts, run_mode}; is_alive(max_age_seconds=120) compares embedded aware ts vs datetime.now(timezone.utc). Consumers: internal/health/routes.py:39 (file/heartbeat-only liveness), :87 (minimal worker liveness, split_v2 web probe); internal/learning/loop_health.py:187,226,241,343,358-377,467 (_heartbeat_age_seconds; file heartbeat inline or HTTP probe split v2); internal/learning/routes.py:220-229; internal/bots/sentinel.py:448-456; internal/data_volume.py:49. Receipts (derived): internal/message_intel/calibration.py:176-225 (_resolved_receipts, hit/miss, verified_resolved_count); rollup.py:1061 (reliability = resolved qualified receipts + beta smoothing), :1219-1232 (<=6 auditable receipts/subnet); proof.py (proof band mandate). Endpoints read different sources: file-heartbeat liveness vs receipt-derived reliability.

## C2 — Resolver lifecycle: CONFIRMED (reschedule guaranteed)
internal/council/resolver_scheduler.py: JOB_ID :64; RESOLVER_REFRESH_MINUTES=15 (:47); RESOLVER_CYCLE_TIMEOUT_SECONDS=120 (:50); min(cycle_timeout,90) :59. _tick (:294): heavy_job_slot gate — not acquired -> persist skip + liveness.record_skip + _schedule_next(min(2,max(1,refresh_minutes))) when _active. After result: record_success/failure/skip; failures -> backoff _backoff_minutes=min(refresh*2^n, max_backoff). _run_refresh_cycle_with_timeout (:460-497): inner finally releases _cycle_lock if gen current; FuturesTimeoutError -> _abandon_inflight_cycle + error cycle_timeout_{t}s + _persist_cycle_summary; outer finally pool.shutdown(wait=False, cancel_futures=True). Next run via schedule_in_seconds(JOB_ID, self._tick, seconds) (:292) — loop does not die silently; BaseException path releases lock if not submitted then re-raises.

## C3 — Timestamp staleness: CONFIRMED (embedded ts, not mtime)
internal/worker_heartbeat.py:42-50 is_alive: freshness = embedded "ts" ISO (aware Z) vs datetime.now(timezone.utc), max_age_seconds=120; NOT file mtime. No st_mtime/stat( in internal/health/, learning/loop_health.py, worker_heartbeat.py, data_volume.py (grep empty). Approval freshness separate: internal/approval/service.py:166-193 _freshness_blocks expires approval when freshness.status in {stale,missing,degraded} and worsened vs at-request.

## WORKSTREAM D (findings-D-tests.md)
# Workstream D — Tests & Correctness (commit 44fd2fb7)

## D1 — Full suite: COMPLETED (after env provisioning)
Run1: 117 collection errors exit 2 (apscheduler missing). Retry: 97 collection errors exit 2 (slowapi x95, sentry_sdk x1, aiocache x1) — all pinned in requirements.txt (slowapi==0.1.9, sentry-sdk==2.19.0, aiocache==0.12.3) -> environment gap, not repo defect. After installing pinned versions, final run summary verbatim: `145 failed, 2489 passed, 4 skipped, 5 warnings in 146.75s (0:02:26)`. Note: APScheduler installed 3.11.3 vs requirements pin 3.10.4 (drift).

## D2 — stall_guard file: COMPLETED
pytest tests/test_loop_stall_guard.py -vv --tb=long > stall_guard_traceback.txt; D2_EXIT=1; wc -c = 6533; sha256 = e643e3e368b75ff41a8411c8492bd863ea6c6dcf8d83057e64ccf5d1b1046bc3. Summary: `3 failed, 7 passed, 1 warning in 0.65s`. Failures: test_revive_recycles_running_scheduler_in_guard_age_window, test_revive_recycles_very_stale_running_scheduler, test_revive_false_on_ok_without_moving_mtime — all `assert False is True`.

## D3 — Naive/aware mixing: PARTIAL
Zero naive datetime.now() in internal/ (grep excluding timezone.utc -> empty). Dominant pattern: aware _utcnow_z() + fromisoformat(value.replace("Z","+00:00")). Mixing points:
1. internal/conviction_decay.py:55 `age = (now - datetime.fromisoformat(last_updated)).total_seconds()`; now = datetime.now(timezone.utc) (:48); fromisoformat yields NAIVE dt if stored string lacks offset -> aware-minus-naive TypeError; inside try (:54), except type UNVERIFIED.
2. internal/conviction_index/__init__.py:130-136 SAFE: naive dt assumed UTC (dt.replace(tzinfo=timezone.utc)).
3. internal/accuracy_lift/measure.py:26 fromisoformat(raw) after Z->+00:00; naive-input handling UNVERIFIED.
Other fromisoformat sites (approval/service.py:111, bots/mission_control.py:350, bots/sentinel.py:158, bots/shield.py:96, council/ab_benchmark.py:239, analytics/soul_weights_chip.py:14) use the Z-replace aware pattern.

## FULL TRACEBACK: stall_guard_traceback.txt (verbatim)
/app/.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:217: PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
The event loop scope for asynchronous fixtures will default to the fixture caching scope. Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to function scope. Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future. Valid fixture loop scopes are: "function", "class", "module", "package", "session"

  warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-8.3.5, pluggy-1.5.0 -- /app/.venv/bin/python
cachedir: .pytest_cache
rootdir: /opt/workspace_base/subnet-dashboard
plugins: anyio-4.9.0, libtmux-0.39.0, asyncio-0.26.0, cov-6.1.1, forked-1.6.0, xdist-3.6.1
asyncio: mode=Mode.STRICT, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 10 items

tests/test_loop_stall_guard.py::test_probe_failures_are_warning_level_and_fail_closed PASSED [ 10%]
tests/test_loop_stall_guard.py::test_revive_resets_stale_snapshot_age PASSED [ 20%]
tests/test_loop_stall_guard.py::test_try_revive_targets_score_snapshot_scheduler PASSED [ 30%]
tests/test_loop_stall_guard.py::test_revive_recycles_running_scheduler_in_guard_age_window FAILED [ 40%]
tests/test_loop_stall_guard.py::test_revive_recycles_very_stale_running_scheduler FAILED [ 50%]
tests/test_loop_stall_guard.py::test_revive_honest_when_tick_in_progress PASSED [ 60%]
tests/test_loop_stall_guard.py::test_revive_false_when_file_already_young_and_no_write PASSED [ 70%]
tests/test_loop_stall_guard.py::test_revive_false_on_skip_or_ok_without_file_write PASSED [ 80%]
tests/test_loop_stall_guard.py::test_revive_false_on_ok_without_moving_mtime FAILED [ 90%]
tests/test_loop_stall_guard.py::test_try_revive_contract_uses_score_snapshot_revive PASSED [100%]

=================================== FAILURES ===================================
__________ test_revive_recycles_running_scheduler_in_guard_age_window __________

tmp_path = PosixPath('/tmp/pytest-of-openhands/pytest-3/test_revive_recycles_running_s0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f8c1881ddf0>

    def test_revive_recycles_running_scheduler_in_guard_age_window(tmp_path, monkeypatch):
        """5400–7200s window: guard already stale; recycle whenever _running."""
        snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
        guard_stale_age = MAX_SNAPSHOT_AGE_SECONDS + 100
        assert guard_stale_age < snaps.SCORE_SNAPSHOT_MAX_AGE_SECONDS
        _make_stale_snapshot(snap_path, age_seconds=guard_stale_age)
        monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write_that_saves(snap_path))
    
        snaps.stop_score_snapshot_scheduler()
        sched = snaps.ScoreSnapshotScheduler()
        sched._running = True
        snaps._scheduler = sched
    
        age_before = loop_health._snapshot_age_seconds(str(snap_path))
        assert age_before > MAX_SNAPSHOT_AGE_SECONDS
    
        try:
            out = snaps.revive_score_snapshot_scheduler()
>           assert out["recycled"] is True
E           assert False is True

tests/test_loop_stall_guard.py:133: AssertionError
______________ test_revive_recycles_very_stale_running_scheduler _______________

tmp_path = PosixPath('/tmp/pytest-of-openhands/pytest-3/test_revive_recycles_very_stal0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f8c18986180>

    def test_revive_recycles_very_stale_running_scheduler(tmp_path, monkeypatch):
        snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
        _make_stale_snapshot(snap_path, age_seconds=snaps.SCORE_SNAPSHOT_MAX_AGE_SECONDS + 100)
        monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write_that_saves(snap_path))
    
        snaps.stop_score_snapshot_scheduler()
        sched = snaps.ScoreSnapshotScheduler()
        sched._running = True
        snaps._scheduler = sched
    
        try:
            out = snaps.revive_score_snapshot_scheduler()
>           assert out["recycled"] is True
E           assert False is True

tests/test_loop_stall_guard.py:155: AssertionError
_________________ test_revive_false_on_ok_without_moving_mtime _________________

tmp_path = PosixPath('/tmp/pytest-of-openhands/pytest-3/test_revive_false_on_ok_withou0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f8c1881db50>

    def test_revive_false_on_ok_without_moving_mtime(tmp_path, monkeypatch):
        """ok:True without save_score_snapshot must not count as revived."""
        snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
        _make_stale_snapshot(snap_path, age_seconds=snaps.SCORE_SNAPSHOT_MAX_AGE_SECONDS + 100)
    
        monkeypatch.setattr(
            snaps,
            "write_full_universe_snapshot",
            lambda progress_cb=None: {
                "ok": True,
                "count": 0,
                "written_at": "2026-08-21T00:00:00Z",
                "path": str(snap_path),
            },
        )
    
        snaps.stop_score_snapshot_scheduler()
        sched = snaps.ScoreSnapshotScheduler()
        sched._running = True
        snaps._scheduler = sched
    
        try:
            out = snaps.revive_score_snapshot_scheduler()
>           assert out["recycled"] is True
E           assert False is True

tests/test_loop_stall_guard.py:280: AssertionError
=============================== warnings summary ===============================
../../../app/.venv/lib/python3.12/site-packages/_pytest/config/__init__.py:1277
  /app/.venv/lib/python3.12/site-packages/_pytest/config/__init__.py:1277: PytestAssertRewriteWarning: Module already imported so cannot be rewritten: anyio
    self._mark_plugins_for_rewrite(hook)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_loop_stall_guard.py::test_revive_recycles_running_scheduler_in_guard_age_window - assert False is True
FAILED tests/test_loop_stall_guard.py::test_revive_recycles_very_stale_running_scheduler - assert False is True
FAILED tests/test_loop_stall_guard.py::test_revive_false_on_ok_without_moving_mtime - assert False is True
==================== 3 failed, 7 passed, 1 warning in 0.65s ====================
