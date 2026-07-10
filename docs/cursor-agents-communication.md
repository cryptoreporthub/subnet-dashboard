# Cursor Agents Communication

> **Canonical copy lives in Ditto.** Search: `Cursor Agents Communication` or `subnet-dashboard agent coordination`.
> Dedicated graph: `cursor-agents-communication-fd6d30`
> Do not ask the user to relay messages between agents.

## Protocol (both agents)

### Before any repo work
1. `search_memories` in Ditto: `"Cursor Agents Communication"` + `"subnet-dashboard agent coordination"`
2. Read the **STATUS SNAPSHOT** and the other agent's **IN PROGRESS** section
3. Check open PRs on GitHub (`gh pr list --state open`)
4. Confirm your slice does not overlap the other agent's active files

### After merge, close, or slice decision
1. Append a dated log entry under **your** agent section in Ditto (`update_memory` on this artifact)
2. Refresh **STATUS SNAPSHOT** (main SHA, open PRs, next slice owner)
3. Link related PR numbers and branch names

---

## Agent A (`-843d`)

**Focus:** incremental rebuild core, Fly/CI, learning loop, predictions, SimiVision chat (later)

| Field | Value |
|-------|-------|
| Cloud agent | `bc-2cb7942b-4dc6-4266-9307-4446db6b843d` |
| Branch suffix | `-843d` |
| Owns | `internal/council/learning_routes.py`, fly/ci workflows, dashboard data fixes |

### Log
| Date (UTC) | Action | PR | main after |
|------------|--------|-----|------------|
| 2026-07-10 | Slice 1 foundation | #62 | merged |
| 2026-07-10 | Slice 2 SimiVision picks | #66 | merged |
| 2026-07-10 | Slice 4 Judge Council | #67 | `743c9ce` |
| 2026-07-10 | Slice 5 learning read APIs | #69 | `4f9da76` |

### In progress
- **Next:** Slice 6 — learning write APIs (`POST /api/feedback`, `POST /api/learning/trigger`, resolver run) — when assigned

### Do not touch
- `internal/ruggers/*` while Agent B has open ruggers PR
- Monolith restore (`restore-server-ruggers-watchlist`)

---

## Agent B (`-e78a`)

**Focus:** whale intelligence, ruggers facade, indicators, oracle stub

| Field | Value |
|-------|-------|
| Cloud agent | `bc-cbcc1f5c-0b66-4d68-909d-8101dc52e78a` |
| Branch suffix | `-e78a` |
| Owns | `internal/whales/*`, `internal/ruggers/*`, `internal/indicators/routes.py` (future) |

### Log
| Date (UTC) | Action | PR | main after |
|------------|--------|-----|------------|
| 2026-07-10 | Slice 3 Whale Intelligence | #65 | merged |
| 2026-07-10 | Slice 4 duplicate (closed) | #68 | — |
| 2026-07-10 | Slice 4b Ruggers router | #70 | **OPEN — rebase onto `4f9da76`** |

### In progress
- **PR #70** — ruggers watchlist facade; must rebase onto post-#69 `main` before merge

### Do not touch
- `internal/council/learning_routes.py`, `council_routes.py` (Agent A)
- Learning loop write endpoints (slice 6, Agent A)

---

## STATUS SNAPSHOT

| Item | Value |
|------|-------|
| **main** | `4f9da76` (includes #69 slice 5) |
| **Rebuild** | Incremental FastAPI — one `server.py` + `include_router` only |
| **Open PRs** | #70 ruggers (`-e78a`) |
| **Next merge** | #70 after rebase |
| **Closed forever** | #63 monolith, #68 duplicate judges |

## Shared rules

1. **Single foundation** — `server:app` only; never restore `server_original.py` monolith
2. **One slice = one PR** to `main` (no stacked PRs)
3. **Conflict surface** — `server.py` (include_router lines only), `tests/test_endpoint_contract.py`
4. **Parallel OK** when modules differ (`internal/ruggers` vs `internal/council/learning`)
5. **Rebase before merge** if the other agent landed while your PR was open

## Slice queue

| # | Slice | Owner | Status |
|---|-------|-------|--------|
| 1 | FastAPI foundation | A | ✅ #62 |
| 2 | SimiVision picks | A | ✅ #66 |
| 3 | Whale Intelligence | B | ✅ #65 |
| 4 | Judge Council | A | ✅ #67 |
| 4b | Ruggers facade | B | 🟡 #70 |
| 5 | Learning read APIs | A | ✅ #69 |
| 6 | Learning write APIs | A | pending |
| 7 | Indicators read | B | pending |
