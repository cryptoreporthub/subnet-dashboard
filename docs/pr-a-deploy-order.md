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

#1484 serves only **complete** snapshots and falls back to the **image seed** when the volume file is missing or not servable. Without #1486 the essential worker still boots the disk-keyed `score-snapshot-ensure` path, which does not arm the periodic producer. On an empty volume:

- Readers serve the **seed** (`seed` state), never a blank response.
- No process writes a fresh volume snapshot, so the volume stays empty and prod relies on the seed alone.

#1486 wires `score_snapshot_producer_enabled()` to `_start_score_snapshot_scheduler()` and deletes the ensure boot path.

## Merge and deploy order

1. #1483 membership from chain (alone).
2. #1484 complete-only snapshots, #1486 producer owner, #1485 stall guard, deployed together — **#1486 without #1485 crash-loops non-owner workers with a stale snapshot** (see above).
3. PR-D readers after.
