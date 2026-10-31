# Snapshot producer deploy order (MC #1479)

**Do not deploy the complete-only reader (#1484) alone on a new or wiped volume** without the producer owner change (#1486).

**Non-owner workers stay idle in the loop stall guard (#1486).** `revive_score_snapshot_scheduler` and
`start_score_snapshot_scheduler` return `not_owner` on a `WORKER_HEAVY=off` worker (or hop, or
`SCORE_SNAPSHOT_SCHEDULER_ENABLED=off`), so such a process can never freshen `score_snapshots.json`.
The loop stall guard therefore reads its snapshot age only on the owner: `_snapshot_age_seconds()`
returns `None` for every other process, and a `not_owner` revive result is treated as idle. A
non-owner worker with a stale volume file never revives, strikes or exits, so there is no crash loop.
This is enforced in code and covered by `tests/test_loop_stall_guard.py`, not by deploy order.

#1485 (PR-C) is a separate improvement to the same guard (the owner is judged by its cycle receipt,
and a running scoring tick by its progress). It is not required for non-owner safety. Merging and
deploying #1486 and #1485 together is still the plan; deploying needs Joshua's explicit GO.

## Why

On **main @ `affd0c6a` (PR-B #1484 merged)**, #1484 serves only **complete** snapshots and falls back to the **image seed** when the volume file is missing or not servable. The essential worker still registers **`score-snapshot-ensure`**, which calls `ensure_complete_snapshot()` → `revive_score_snapshot_scheduler()` when the volume is missing or not fresh-complete. That path **can arm the scheduler and run a cycle** (including on a stale volume file), but it is a **boot-time ensure/revive hook**, not the periodic owner producer #1486 adds.

Without **#1486**, production still lacks a dedicated **`score_snapshot_producer_enabled()`** gate and the deferred **`score-snapshots`** boot job that keeps the essential worker owning periodic publishes. On a **wiped or empty volume**, readers stay on the **seed** (never blank), but nothing guarantees the **essential worker** keeps refreshing the volume after boot unless ensure/revive fires again.

**#1486** wires the essential worker to `_start_score_snapshot_scheduler()` when `score_snapshot_producer_enabled()` is true, gates `start_score_snapshot_scheduler` / `revive_score_snapshot_scheduler` with **`not_owner`** on non-producer workers (and the stall guard stays idle there), and **removes** the `score-snapshot-ensure` boot path so production relies on the owner producer instead of the one-shot ensure job.

## Merge and deploy order

1. #1483 membership from chain (alone).
2. #1484 complete-only snapshots, #1486 producer owner, #1485 stall guard, deployed together.
3. PR-D readers after.
