# review_orchestrator

Tick persistence in a SQLite store (`orchestrator.sqlite`), plus the v1a dead-man
check. One writer (`run_tick`); the dead-man reads the `latest` view.

## Store

Each tick opens a row in `ticks` with `outcome = 'running'`, runs its work outside
any transaction, then closes the row `completed` (or `failed`, with a duration, if
the work raises). `seq` is `INTEGER PRIMARY KEY AUTOINCREMENT`, so the newest row is
`MAX(seq)`.

Nothing compares a candidate heartbeat against a stored order value. `latest` and
`read_latest_tick` recompute the newest row as `MAX(seq)`, so a corrupt or bogus
incumbent cannot block a newer tick. This replaces the v0 `seq/` reservation and
`heartbeat/latest.json` comparison, whose `(seq, tick_id)` guard was the round-3
blocker.

A running row older than 40 minutes is swept to `abandoned` before the next tick
measures overlap, so a tick killed between start and completion cannot pin
`overlap` on for the life of the store. `overlap` is measured as "does another
running row exist right now", after the sweep.

The schema ties the two columns together:

```sql
CHECK ((outcome IN ('running', 'abandoned')) = (duration_ms IS NULL))
```

so a completed row with no duration, or a running row with one, is rejected at the
store boundary.

## Corruption, unavailability, and repair

`db.connect` raises `StoreCorruptError` only when the bytes are not a database
("not a database", or "malformed"). Every other open failure — a read-only
directory, a missing permission, a filesystem that cannot do WAL — raises
`StoreUnavailableError`, because `repair` cannot help with those and reporting
them as corruption sends the operator down the wrong path. A lock is neither:
`connect` re-raises the sqlite `OperationalError` so the caller retries.

`run_tick` surfaces both errors; the dead-man reports either as
`heartbeat_unreadable` rather than crashing. Recover a corrupt store explicitly:

```bash
.venv/bin/python -m tools.review_orchestrator.persist repair --state-dir /path/to/store
```

This moves the corrupt store aside as `orchestrator.sqlite.corrupt-<stamp>` and the
next tick creates a fresh one. In an unwritable directory `repair` raises
`StoreUnavailableError` instead of letting a `PermissionError` escape.

The store is WAL, so a reader needs write access to the state directory (to create
or write the `-shm` wal-index beside the database). Run the dead-man with the same
filesystem access as the writer.

## Tests and exams

```bash
.venv/bin/pytest tests/test_review_orchestrator_v0.py -v
.venv/bin/pytest tests/test_review_orchestrator_v1a.py -v
.venv/bin/python -m tools.review_orchestrator.exam_v0
.venv/bin/python -m tools.review_orchestrator.exam_v1a
```

Each exam accepts `--state-dir` to run in a disposable `exam-<token>/` subdir.

## v1a dead-man

`evaluate_deadman(state_dir, max_age_minutes=40, now=None)` reads the store's latest
row and returns one reason:

- `heartbeat_unreadable` — no row, an unreadable `started_at`, or a corrupt store;
- `heartbeat_future` — `started_at` or the derived completion more than five minutes ahead;
- `attempt_stale` — started and never finished past the limit (a running or swept row);
- `completed_stale` — completion past the limit;
- `tick_failed` — the latest row is a finished tick with `outcome = 'failed'`; a newer
  running row defers the verdict to that attempt, so a retry in flight is not reported;
- `last_alert_failed` — `last_alert_ok = 0`;
- `ok`.

The staleness reasons outrank `tick_failed`, which outranks `last_alert_failed`.

The completion time is derived as `started_at + duration_ms`; there is no separate
heartbeat file. The CLI prints the reason and exits 0/1, or 3 on an unexpected error.
