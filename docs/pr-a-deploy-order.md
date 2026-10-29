# Snapshot producer deploy order (MC #1479)

**Do not deploy the complete-only reader (#1484) alone on a new or wiped volume** without the producer owner change (#1486).

**#1486 must not deploy without #1485 (PR-C).** This is a hard dependency, not a preference:

#1486 makes a non-owner worker refuse to produce. `revive_score_snapshot_scheduler` and
`start_score_snapshot_scheduler` return `not_owner` on a `WORKER_HEAVY=off` worker (PR-A commit
`01b6e00d`). Only #1485's stall-guard change teaches the loop stall guard what `not_owner` means.
With #1486 but without #1485, a non-owner worker whose volume holds a stale `score_snapshots.json`
gets `not_owner` from the strike-1 revive, the snapshot never freshens, and the guard escalates to
`os._exit(1)` — the supervisor restarts the worker, the stale snapshot is still there, and the
worker crash-loops until the volume freshens some other way. Deploy #1484 + #1486 + #1485 together
(in the same image), or hold #1486 back.

## Why

On **main @ `affd0c6a` (PR-B #1484 merged)**, #1484 serves only **complete** snapshots and falls back to the **image seed** when the volume file is missing or not servable. The essential worker still registers **`score-snapshot-ensure`**, which calls `ensure_complete_snapshot()` → `revive_score_snapshot_scheduler()` when the volume is missing or not fresh-complete. That path **can arm the scheduler and run a cycle** (including on a stale volume file), but it is a **boot-time ensure/revive hook**, not the periodic owner producer #1486 adds.

Without **#1486**, production still lacks a dedicated **`score_snapshot_producer_enabled()`** gate and the deferred **`score-snapshots`** boot job that keeps the essential worker owning periodic publishes. On a **wiped or empty volume**, readers stay on the **seed** (never blank), but nothing guarantees the **essential worker** keeps refreshing the volume after boot unless ensure/revive fires again.

**#1486** wires the essential worker to `_start_score_snapshot_scheduler()` when `score_snapshot_producer_enabled()` is true, gates `start_score_snapshot_scheduler` / `revive_score_snapshot_scheduler` with **`not_owner`** on non-producer workers, and **removes** the `score-snapshot-ensure` boot path so production relies on the owner producer instead of the one-shot ensure job.

## Merge and deploy order

1. #1483 membership from chain (alone).
2. #1484 complete-only snapshots, #1486 producer owner, #1485 stall guard, deployed together — **#1486 without #1485 crash-loops non-owner workers with a stale snapshot** (see above).
3. PR-D readers after.
