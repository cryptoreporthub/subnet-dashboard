# review_orchestrator v0

Tick persistence only: per-tick JSON under `ticks/`, seq claims under `seq/`, and a single `active/in-flight.json` overlap marker.

Release of the in-flight marker runs in a `finally` after the tick write, matching the per-invocation `owner_token` stored in the marker (a reused `tick_id` cannot clear another run's claim). A `kill -9` mid-tick can leave a stale `active/in-flight.json`; overlap detection will treat later ticks as overlapping until that file is removed. Staleness eviction is deferred to v1.

Seq numbers are reserved under `seq/<n>.json` via create-if-absent; the reader orders valid ticks by `(seq, completed_at)` and ignores `completed_at` values more than five minutes ahead of wall clock.

A caller-supplied `tick_id` must be unique: an existing `tick-<id>.json` or an in-flight reservation for that id raises `DuplicateTickIdError`.

Run the contract tests:

```bash
.venv/bin/pytest tests/test_review_orchestrator_v0.py -v
```

Run the one-command exam (optionally under a parent `--state-dir`; each run uses its own `exam-<token>/` subdir):

```bash
.venv/bin/python -m tools.review_orchestrator.exam_v0
.venv/bin/python -m tools.review_orchestrator.exam_v0 --state-dir /path/to/store
```
