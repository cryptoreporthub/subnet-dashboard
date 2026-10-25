# Snapshot producer deploy order (MC #1479)

**Do not deploy the complete-only reader (#1484) alone on a new or wiped volume** without the producer owner change (#1486).

## Why

#1484 serves only **complete** snapshots and falls back to the **image seed** when the volume file is missing or not servable. Without #1486 the essential worker still boots the disk-keyed `score-snapshot-ensure` path, which does not arm the periodic producer. On an empty volume:

- Readers serve the **seed** (`seed` state), never a blank response.
- No process writes a fresh volume snapshot, so the volume stays empty and prod relies on the seed alone.

#1486 wires `score_snapshot_producer_enabled()` to `_start_score_snapshot_scheduler()` and deletes the ensure boot path.

## Merge and deploy order

1. #1483 membership from chain (alone).
2. #1484 complete-only snapshots, #1486 producer owner, #1485 stall guard, deployed together.
3. PR-D readers after.
