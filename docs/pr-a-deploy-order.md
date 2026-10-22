# PR-A deploy order (MC #1479)

**Do not deploy PR-B (#1484) alone on a new or wiped volume** without PR-A (#1485 stack).

## Why

PR-B serves only **complete** snapshots and falls back to the **image seed** when the volume file is missing or not servable. The essential worker today boots `score-snapshot-ensure` (disk-keyed revive), not the periodic producer. On an empty volume:

- Readers can serve the **seed** (`fresh` / `aged` / `seed` states).
- The **producer does not arm** until PR-A wires `score_snapshot_producer_enabled()` → `_start_score_snapshot_scheduler()`.
- `ensure_complete_snapshot()` does not replace a durable volume publish when the served state is already seed-servable — so the volume can stay empty while prod relies on seed-only service.

Repro script (Project store): `internal/1479-mc-design-decision/prb_alone_seed_gap.py` on PR-B head.

## Merge / deploy order

1. **PR-B** — complete-only writer, seed, readers (draft; merge when green).
2. **PR-A** — essential-worker producer; delete ensure boot path (this change).
3. Deploy **PR-B + PR-A together** (or PR-A on top of merged PR-B) before expecting volume-backed fresh snapshots on a new machine.

PR-C (stall guard on cycle receipt) and PR-D (pick endpoints) follow MC stack; not required to fix the seed-only gap alone.
