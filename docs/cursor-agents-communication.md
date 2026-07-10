# Cursor Agents Communication

> **Canonical copy lives in Ditto.** Search: `Cursor Agents Communication` or `subnet-dashboard agent coordination`.
> Dedicated graph: `cursor-agents-communication-fd6d30`
> Do not ask the user to relay messages between agents.

## Parallel ownership (no toe-stepping)

| Agent | Owns (`internal/*`) | Current slice | Do NOT touch |
|-------|---------------------|---------------|--------------|
| **A (`-843d`)** | `learning/routes.py`, `council/pick_history.py`, `council/rotation_tracker.py`, `freshness.py`, `council/weights.py`, fly/ci | **10a** rotation-tracker, freshness, weights | `analytics/*`, `oracle/*`, `indicators/*`, `ruggers/*`, `whales/*` |
| **B (`-e78a`)** | `whales/*`, `ruggers/*`, `indicators/*`, `oracle/*`, `analytics/*`, `pump_tracker.py` | **10b** pump-analytics + price-tracking | `learning/routes.py`, `council/weights`, rotation-tracker, freshness |

**Conflict surface only:** `server.py` (include_router lines) + `tests/test_endpoint_contract.py` — rebase before merge if both PRs open.

---

## Agent A (`-843d`)

### Log
| Date (UTC) | Action | PR | main after |
|------------|--------|-----|------------|
| 2026-07-10 | Slices 1–2, 4–6, 8 | #62 #66 #67 #69 #72 #74 | `c578236` |

### In progress
- **Slice 10a** — `GET /api/rotation-tracker`, then freshness + weights

---

## Agent B (`-e78a`)

### Log
| Date (UTC) | Action | PR | main after |
|------------|--------|-----|------------|
| 2026-07-10 | Slices 3, 4b, 7, 9 | #65 #70 #71 #73 | `23852d2` |
| 2026-07-10 | Slice 10b pump + price-tracking | — | **IN PROGRESS** |

### In progress
- **Slice 10b** — branch `cursor/pump-price-tracking-slice10b-e78a`

---

## STATUS SNAPSHOT

| Item | Value |
|------|-------|
| **main** | `23852d2` |
| **Open PRs** | 10a (A), 10b (B) — parallel |
| **Next** | merge whichever is ready; second rebases onto first if needed |

## Slice queue

| # | Slice | Owner | Status |
|---|-------|-------|--------|
| 1–9 | Foundation through oracle | both | ✅ |
| 10a | Rotation-tracker + freshness + weights | A | 🟡 in progress |
| 10b | Pump analytics + price-tracking | B | 🟡 in progress |
| 11 | SimiVision chat | A | pending |
