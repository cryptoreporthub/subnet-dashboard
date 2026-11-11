---
name: SQLite store concurrency
---

The review-orchestrator tick store is SQLite in WAL mode, one writer. Three behaviours cost real debugging time and are not obvious from the code:

- Converting `journal_mode` to WAL needs an exclusive lock and does **not** invoke the busy handler, so a concurrent writer gets `SQLITE_BUSY` immediately even with a 5s `busy_timeout`. Read `PRAGMA journal_mode` first and only convert when it is not already `wal`, with a short retry loop. Losers of a fresh-store race see `wal` on the next look.
- DROP-then-CREATE of a view (the `latest` reader view) is two statements, so two writers racing on a fresh store both pass a "view is missing" check and one gets "view already exists". Re-check inside `BEGIN IMMEDIATE` before rewriting, or use a single idempotent statement.
- `PRAGMA journal_mode=WAL` on every connect makes every read a write. Keep the schema/PRAGMA work conditional so concurrent readers do not serialise.

`connect` separates transient contention (locked/busy -> re-raise) from corruption (anything else -> `StoreCorruptError`); do not wrap both in one handler or a busy store looks corrupt.

**Why:** the parallel-tick stress tests exposed each of these in turn while migrating tick persistence off the per-tick file store.

**How to apply:** any time a module opens SQLite itself (helper script, worker, CLI) rather than reusing `tools/review_orchestrator/db.connect`.
