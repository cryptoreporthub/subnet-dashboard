# AUDIT-FINDINGS — subnet-dashboard @ 44fd2fb7

- Repo: https://github.com/cryptoreporthub/subnet-dashboard
- Pinned commit: 44fd2fb761017108856b488584d06531ba28af21 (verified via `git rev-parse HEAD`)
- Audit date: 2026-09-03 (UTC)
- Method: read-only code audit; every claim below is backed by verbatim command output or file snippets with file:line.

## 1. STEP 0 — Auth gate (verbatim)

```
github.com
  ✓ Logged in to github.com account cryptoreporthub (GH_TOKEN)
  - Active account: true
  - Git operations protocol: https
  - Token: ghu_************************************
```

## 2. STEP 1 — Clone + pin (verbatim)

```
44fd2fb761017108856b488584d06531ba28af21
```
HEAD matches pin prefix 44fd2fb7. Note: repo was already present in workspace; `git checkout 44fd2fb7` re-pinned it. Pre-existing local modification to `ditto.json` was present and untouched.

## 3. STEP 2 — Test suite (verbatim)

Full suite (`python -m pytest tests/ -q 2>&1 | tail -5`), after installing requirements.txt (first run had 117 collection errors from missing deps in the sandbox venv):

```
138 failed, 2496 passed, 4 skipped, 6 warnings in 164.17s (0:02:44)
```

Stall-guard file run (`python -m pytest tests/test_loop_stall_guard.py -vv --tb=long > stall_guard_traceback.txt 2>&1`, exit code 1):

```
==================== 3 failed, 7 passed, 1 warning in 0.88s ====================
```

- `wc -c stall_guard_traceback.txt` → `6533 stall_guard_traceback.txt`
- `sha256sum stall_guard_traceback.txt` → `376da5183adff211711f22ccb33ead99499b87b0c05681d088cfa37b88273bab  stall_guard_traceback.txt`

## 4. The 3 failing tests (full tracebacks, verbatim from stall_guard_traceback.txt)

Failing tests:
1. `tests/test_loop_stall_guard.py::test_revive_recycles_running_scheduler_in_guard_age_window` — assert False is True (test line 133)
2. `tests/test_loop_stall_guard.py::test_revive_recycles_very_stale_running_scheduler` — assert False is True (test line 155)
3. `tests/test_loop_stall_guard.py::test_revive_false_on_ok_without_moving_mtime` — assert False is True (test line 280)

Full traceback file content (stall_guard_traceback.txt, 6533 bytes, SHA-256 above):

```
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

tmp_path = PosixPath('/tmp/pytest-of-openhands/pytest-2/test_revive_recycles_running_s0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f35145905f0>

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

tmp_path = PosixPath('/tmp/pytest-of-openhands/pytest-2/test_revive_recycles_very_stal0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f351457c5c0>

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

tmp_path = PosixPath('/tmp/pytest-of-openhands/pytest-2/test_revive_false_on_ok_withou0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3514590890>

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
  /app/.venv/lib/python3.12/site-packages/_pytest/config/__init__.py:1277
  PytestAssertRewriteWarning: Module already imported so cannot be rewritten: anyio
    self._mark_plugins_for_rewrite(hook)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_loop_stall_guard.py::test_revive_recycles_running_scheduler_in_guard_age_window - assert False is True
FAILED tests/test_loop_stall_guard.py::test_revive_recycles_very_stale_running_scheduler - assert False is True
FAILED tests/test_loop_stall_guard.py::test_revive_false_on_ok_without_moving_mtime - assert False is True
==================== 3 failed, 7 passed, 1 warning in 0.88s ====================
```

### Root cause (mechanically verified)

All 3 failures share one cause: tests simulate a "running" scheduler via the legacy attribute `sched._running = True` (tests/test_loop_stall_guard.py:129, 151, 276), but production `revive_score_snapshot_scheduler()` decides `running` from the LivenessTracker lifecycle:

- internal/council/score_snapshots.py:692-695 (inside `revive_score_snapshot_scheduler`, def at :673):
```python
        running = bool(
            sched and sched.liveness.snapshot().get("lifecycle") == "started"
        )
```
- internal/liveness.py:271-274: `start()` sets `self._lifecycle = "started"`; a freshly constructed `ScoreSnapshotScheduler()` is `"new"` (internal/liveness.py:223 `self._lifecycle = "new"`).

So `running` is False → `recycled` stays False → `assert out["recycled"] is True` fails at test lines 133/155/280. The tests never call `sched.start()` nor set liveness lifecycle, so the production contract (liveness-based) and the test contract (`_running`) diverged.

## 5. STEP 3 — Hypothesis verdicts

| # | Hypothesis | Verdict |
|---|---|---|
| 3a | Non-atomic JSON writes via direct `open(...,'w')` truncate | PARTIAL — state files are atomic (tmp+`os.replace`); worker heartbeat file is a direct truncate write |
| 3b | AIO_WORKER_POOL_SIZE read/consumed | CONFIRMED — read at server.py:364, set to "24" in fly.toml:112, consumed as the asyncio default executor thread cap |
| 3c | Daily-pick scoring synchronously in GET request path | NOT FOUND for GET /api/daily-pick — handler never scores; timeout returns synthesized HOLD, not persisted; scheduler HOLD persisted via `write_scheduler_hold` → `_save` (atomic); fcntl lock exists only for pick_score_cache |
| 3d | /api/ops/readiness reads JSON heartbeat while M6 gate reads SQLite receipts | NOT FOUND as stated — readiness→learning health reads file heartbeat/HTTP peer; no "M6" string and no SQLite receipts exist in code; "receipt" only in message_intel (non-SQLite) |
| 3e | Naive/aware datetime mixing | PARTIAL — one real site (internal/conviction_decay.py:55); all other parse sites normalize to UTC |

### 3a. Non-atomic JSON writes — PARTIAL

`grep -rn "open(.*'w')" internal/ server.py | grep -v -i atomic` → EMPTY (zero hits). Double-quote variant hits are all tmp-file writes followed by `os.replace`:

- internal/council/daily_pick_engine.py:45-49 (`_save`):
```python
def _save(records: List[Dict[str, Any]], path: Optional[str] = None) -> None:
    path = path or DAILY_PICKS_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(records, f, indent=2)
    os.replace(tmp, path)
```
- internal/council/resolver.py:161-166 (`_save_json`, used for PREDICTIONS_PATH at resolver.py:1109, 1169, 1321, 1461):
```python
def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
```
- internal/council/score_snapshots.py:109/115: `save_score_snapshot` also ends in `os.replace(tmp, snap_path)`.

EXCEPTION — heartbeat is a direct truncate write (internal/worker_heartbeat.py:20-32, path default `data/.worker_heartbeat` from :17):
```python
def touch_heartbeat() -> None:
    """Worker calls on boot and on periodic tick."""
    payload = {
        "pid": os.getpid(),
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_mode": os.environ.get("RUN_MODE", "worker"),
    }
    path = _path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
```
A crash mid-write can leave a truncated/partial heartbeat JSON. Readers (`read_heartbeat`, internal/worker_heartbeat.py:33) tolerate this, but it is the one non-atomic state-file write found.

### 3b. AIO_WORKER_POOL_SIZE — CONFIRMED

`grep -rn "AIO_WORKER_POOL_SIZE" . --include="*.py" --include="*.toml"` (pycache excluded):
- fly.toml:112: `AIO_WORKER_POOL_SIZE = "24"`
- server.py:364: `pool_cap = int(os.environ.get("AIO_WORKER_POOL_SIZE", "4"))`
- internal/request_executor.py:5: docstring reference.

Consumption (server.py:363-369):
```python
    # ponytail: cap default asyncio thread pool — timed-out pick/weighed work can't exhaust all slots
    pool_cap = int(os.environ.get("AIO_WORKER_POOL_SIZE", "4"))
    aio_pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=pool_cap, thread_name_prefix="aio-web"
    )
    asyncio.get_running_loop().set_default_executor(aio_pool)
```
So the 24-thread pool is the asyncio default executor for `run_in_executor`/`to_thread` on the web process. Request-time aggregation uses a separate dedicated pool (internal/request_executor.py:27 `REQUEST_EXECUTOR = concurrent.futures.ThreadPoolExecutor(...)`), so AIO_WORKER_POOL_SIZE does not size that one.

### 3c. Daily-pick scoring in request path — NOT FOUND (GET does not score)

`grep -rn "def.*daily" server.py routers.py internal/council/daily_pick.py` → routers.py does not exist; handler is `api_daily_pick` at server.py:3160. Its docstring and body (server.py:3160-3176):
```python
async def api_daily_pick(full: bool = False):
    """Today's pick from stored JSON. Hydrate GET never waits on scoring.
    ...
    """
    _ = full
    started = time.monotonic()
    timeout_s = PICK_READ_TIMEOUT
    fut, stash = _coalesce_daily_pick_flight()
```
On timeout (server.py:3195-3210) it sheds to the stashed payload or returns `_daily_pick_timeout_hold()` (server.py:3100-3111) — a synthesized dict with `"status": "timeout", "action": "HOLD"`, never written to disk in the request path.

The persisted scheduler HOLD is written by the background scheduler via `write_scheduler_hold` (internal/council/daily_pick_engine.py:159-180), through atomic `_save`:
```python
def write_scheduler_hold(reason: str) -> Dict[str, Any]:
    """Persist an honest HOLD when the background tick cannot finish scoring."""
    ...
    existing = _find_today(records)
    if isinstance(existing, dict) and not existing.get("scheduler_hold") and existing.get("pick"):
        # Never clobber a real published pick.
        return existing
    records = _upsert_today(records, payload)
    _save(records)
```
No lock file guards the daily-pick JSON itself; the only fcntl lock in internal/council is for the score cache (internal/council/pick_score_cache.py:41 `LOCK_PATH = CACHE_PATH + ".lock"`, :104 `fcntl.flock(lf.fileno(), fcntl.LOCK_EX)`). Scoring on demand exists only on `/api/daily-pick/weighed` (server.py:3079-3098), which reads stored JSON and scores the shortlist under `PICK_HANDLER_TIMEOUT`, returning `{"shortlist": [], "status": "timeout"}` on timeout.

### 3d. Health source split — NOT FOUND as hypothesized (real sources documented)

`grep -rn "receipt" internal/worker_peer.py` → EMPTY (zero hits). worker_peer.py is file-heartbeat/HTTP based (internal/worker_peer.py:1): `"""Worker peer liveness — file heartbeat (v1 inline) or HTTP (split v2 web → worker)."""` with `_file_peer` using `read_heartbeat()` (:12-18) and `_remote_peer` using `fetch_worker_json_sync` (:24-33).

`/api/ops/readiness` → `build_readiness_report` (internal/ops/readiness.py:181); its learning section (`_learning_loop_health`, readiness.py:49-66) proxies worker `/api/learning/health` on split_v2 or calls `build_learning_loop_health()` (internal/learning/loop_health.py), which consumes the worker peer heartbeat (loop_health.py:226 `hb_age = _heartbeat_age_seconds(worker_peer)`; :358-359 reads `peer.get("heartbeat")`). So readiness/learning health read the JSON file heartbeat (`data/.worker_heartbeat`, internal/worker_heartbeat.py:17) or HTTP peer — not SQLite.

`grep -rn "M6" internal/ --include="*.py"` → EMPTY (zero hits). `receipt` appears only in internal/message_intel/{calibration,engine,proof,rollup,routes}.py and internal/simivision/weighing_room.py; `grep -rn "sqlite" internal/message_intel/*.py` → EMPTY — message_intel receipts are not SQLite-backed in this tree. The hypothesized "M6 gate reads SQLite receipts" split does not exist at this commit; both health surfaces derive from the file heartbeat / worker HTTP peer.

### 3e. Naive datetime — PARTIAL

`grep -rn "datetime.now()" internal/ --include="*.py"` (pycache excluded) → EMPTY: the codebase consistently uses `datetime.now(timezone.utc)` (e.g. internal/worker_heartbeat.py:23, internal/conviction_decay.py:49, server.py:3104).

`grep -rn "fromisoformat" internal/` → 20+ hits; most normalize Z and tz, e.g. internal/accuracy_lift/measure.py:23-29 and internal/council/price_reference.py:36-46 both coerce naive to UTC.

One real naive/aware mixing site — internal/conviction_decay.py:49-56:
```python
    now = datetime.now(timezone.utc)
    decayed: Dict[str, Any] = {}
    for netuid, node in nodes.items():
        conviction = node.get("conviction", 50.0)
        last_updated = node.get("last_updated")
        if last_updated:
            try:
                age = (now - datetime.fromisoformat(last_updated)).total_seconds()
```
`datetime.fromisoformat(last_updated)` is used raw: if `last_updated` is naive ISO (no offset), `now - naive` raises `TypeError: can't subtract offset-naive and offset-aware datetimes`, which is swallowed by the bare `except Exception: pass` — so affected nodes silently keep undecayed conviction. Also internal/council/score_snapshots.py:86 `datetime.fromisoformat(value.replace("Z", "+00:00"))` can return naive for offset-less input, but its caller compares against mtime epoch (score_snapshots.py:91-95), not a datetime, so no mixing there.

## 6. Environment note (test reproducibility)

First `pytest tests/` run produced `117 errors during collection` (ModuleNotFoundError: apscheduler) because the sandbox venv lacked requirements.txt deps; after `python -m pip install -r requirements.txt` the suite ran as reported in §3. The 138 full-suite failures include environment-induced ones (e.g. plugin/version drift); the 3 stall-guard failures reproduce deterministically at this commit and are analyzed in §4.