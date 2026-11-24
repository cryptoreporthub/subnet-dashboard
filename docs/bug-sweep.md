# Bug pattern sweep

This register lists every place in the repo that matches a bug pattern first found in `server.py`. It is for whoever fixes bugs next. Run `python scripts/bug_pattern_sweep.py` to reproduce every count. The sweep parsed all tracked Python files outside `tests/`. The counts below are from 2026-11-17 at commit `135b1dd`. On 2026-11-24, `main` at `2a199ae` matched them except for swallowed exceptions, which fell from 225 to 223. Where this register and `docs/roadmap-proposal.md` disagree, the proposal is newer.

The first three sections are faults. Each instance matches a pattern that a probe or a review confirmed in `server.py`. The last three sections are candidates. A match there needs a look before anyone calls it a bug.

## Fix these first

### A timeout that does not time out (3 places)

A `with ThreadPoolExecutor(...)` block waits for its worker when the block ends. A `result(timeout=...)` inside it raises on time, and then the block still waits for the hung worker. A probe measured 20.3 seconds against an 8 second timeout at `server.py:837`.

- `internal/learning/dashboard_context.py:120`
- `internal/simivision/chat_service.py:135`
- `server.py:837`

Create the executor without `with` and call `shutdown(wait=False, cancel_futures=True)` in a `finally`. That stops the caller waiting. It does not stop a running worker, and pool workers are non-daemon, so a hung worker can block interpreter exit and repeated timeouts can stack workers (issue #1113). Add a single-flight guard, and where an exit-time join can hang CI, run the work on a daemon thread as `_warm_homepage_cache` does at `server.py:929`. The fault PR F1-A on `fix/f1a-timeout-bound` fixes all three sites. The chat site still leaks one worker per timed-out message, which the guard closes.

### Timestamps that end in `+00:00Z` (3 places)

`datetime.now(timezone.utc).isoformat() + "Z"` produces a string no strict ISO 8601 parser accepts.

- `internal/council/state_vector.py:1313`
- `server.py:2802`
- `server.py:2405`

Use `.isoformat().replace("+00:00", "Z")`. The plan covers all three as D3. The `state_vector.py` site writes a stored value, so check its readers first.

### Routes that send the exception text to the client (54 places)

A route handler catches an exception and returns `str(exc)` in the reply. A probe showed a file path leaking this way from `/api/pick-explain`. The plan fixes only the routes that start in `server.py`. These are the rest.

| File | Places |
|---|---|
| `internal/learning/routes.py` | 15 |
| `internal/analytics/store_routes.py` | 8 |
| `internal/message_intel/routes.py` | 6 |
| `internal/analytics/routes.py` | 5 |
| `internal/pump_tracker/routes.py` | 4 |
| `internal/trace/routes.py` | 4 |
| `server.py` | 4 |
| `internal/conviction_index/routes.py` | 2 |
| `internal/indicators/routes.py` | 2 |
| `internal/judges/council_routes.py` | 2 |
| `internal/mindmap/routes.py` | 1 |
| `internal/oracle/routes.py` | 1 |

Fix them with the `degraded()` helper that R10 of the refactor plan adds. Log the exception, and return a fixed code.

## Look at these next

### Exceptions swallowed with `pass` (223 places on main at 2a199ae)

An `except Exception: pass` hides the failure and leaves no log line. Some are correct, such as a best-effort cleanup. Each one needs a decision. Either the state it hides is legitimate and deserves a debug log, or it hides a bug.

| File | Places |
|---|---|
| `internal/background_boot.py` | 17 |
| `internal/council/resolver.py` | 17 |
| `internal/council/resolver_scheduler.py` | 9 |
| `internal/live_subnets.py` | 7 |
| `internal/metrics.py` | 7 |
| `internal/learning/loop_health.py` | 6 |
| `internal/council/score_snapshots.py` | 5 |
| `internal/council/snapshot_coverage.py` | 5 |
| `internal/council/state_vector.py` | 5 |
| `internal/freshness.py` | 5 |
| `internal/learning/pump_alert.py` | 5 |
| `internal/share_pages/routes.py` | 5 |
| `server.py` | 5 |
| `internal/judges/subnet_judges.py` | 4 |
| `internal/learning/prediction_loop.py` | 4 |

Start with `internal/council/resolver.py` and `internal/background_boot.py`. They hold 34 of the matches and they run the learning loop and the boot sequence.

### JSON written straight to its final path (59 places)

`json.dump` to an open file can leave a half-written file if the process dies, and a reader can see it mid-write. `internal/file_utils.py` already has `safe_write_json`, which writes a temporary file and renames it. Some matches may already write to a temporary path, so check each one.

| File | Places |
|---|---|
| `internal/freshness.py` | 3 |
| `internal/live_subnets.py` | 2 |
| `internal/pump/combined_ledger.py` | 2 |
| `scripts/backfill_chain_prices.py` | 2 |
| `datastore/pump_tracker.py` | 1 |
| `internal/analytics/trail_cursor.py` | 1 |
| `internal/approval/service.py` | 1 |
| `internal/bots/shield.py` | 1 |
| `internal/conviction_decay.py` | 1 |
| `internal/conviction_index/__init__.py` | 1 |
| `internal/council/ab_benchmark.py` | 1 |
| `internal/council/daily_pick_engine.py` | 1 |
| `internal/council/pick_history.py` | 1 |
| `internal/council/pick_scheduler.py` | 1 |
| `internal/council/pick_score_cache.py` | 1 |

### Data paths that ignore `DATA_DIR` (133 places)

A literal such as `"data/soul_map.json"` depends on the working directory and ignores the `DATA_DIR` setting. This is one reason test runs modify tracked files. Some matches are defaults that the code joins with `DATA_DIR` later, so check each one.

| File | Places |
|---|---|
| `internal/indicators/indicator_engine.py` | 8 |
| `server.py` | 6 |
| `internal/bots/market_desk.py` | 5 |
| `internal/freshness.py` | 5 |
| `internal/ruggers/watchlist.py` | 5 |
| `internal/calibration/pipeline.py` | 4 |
| `internal/learning/pump_lead_train.py` | 4 |
| `internal/signals/alerts.py` | 4 |
| `internal/whales/service.py` | 4 |
| `internal/conviction_alerts/evaluate.py` | 3 |
| `internal/letter/brain_letter.py` | 3 |
| `internal/message_intel/reset_store.py` | 3 |
| `datastore/pump_tracker.py` | 2 |
| `internal/conviction_decay.py` | 2 |
| `internal/council/emission_monitor.py` | 2 |

## Checked and clean

The sweep found no blocking `requests`, `time.sleep`, or `subprocess.run` call directly inside an `async def`, no mutable default argument, no naive `utcnow()`, and no GET route that calls a function named like a writer. The last check matches by name only. The write in `GET /api/top-pick/hour` goes through a helper with another name, so a name search does not prove the absence of others.

## How to use this

- Fix the first three sections in one small PR each, failing test first.
- Add the three fault patterns to CI. `scripts/bug_pattern_sweep.py` exits 0 today whatever it finds. Give it a `--fail-on` option and a stored baseline, so that a new instance fails the build.
- Treat the candidate sections as review queues, one file at a time, highest count first.
