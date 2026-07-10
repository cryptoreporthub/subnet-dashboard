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
| Owns | `internal/learning/routes.py`, fly/ci workflows, scenario memory, pick history |

### Log
| Date (UTC) | Action | PR | main after |
|------------|--------|-----|------------|
| 2026-07-10 | Slice 1 foundation | #62 | merged |
| 2026-07-10 | Slice 2 SimiVision picks | #66 | merged |
| 2026-07-10 | Slice 4 Judge Council | #67 | `743c9ce` |
| 2026-07-10 | Slice 5 learning read APIs | #69 | `4f9da76` |

### In progress
- **#72** — slice 6 learning write APIs (rebase onto `acb3050` then merge)
- **Next after #72:** slice 8 scenario memory + pick history

### Do not touch
- `internal/ruggers/*`, `internal/indicators/*`, `internal/oracle/*` (Agent B)

---

## Agent B (`-e78a`)

**Focus:** whale intelligence, ruggers facade, indicators, oracle stub

| Field | Value |
|-------|-------|
| Cloud agent | `bc-cbcc1f5c-0b66-4d68-909d-8101dc52e78a` |
| Branch suffix | `-e78a` |
| Owns | `internal/whales/*`, `internal/ruggers/*`, `internal/indicators/*`, `internal/oracle/*` |

### Log
| Date (UTC) | Action | PR | main after |
|------------|--------|-----|------------|
| 2026-07-10 | Slice 3 Whale Intelligence | #65 | merged |
| 2026-07-10 | Slice 4 duplicate (closed) | #68 | — |
| 2026-07-10 | Slice 4b Ruggers router | #70 | `fc31f83` |
| 2026-07-10 | Slice 7 Indicators read | #71 | `acb3050` |
| 2026-07-10 | Slice 9 Oracle stub | — | **IN PROGRESS** |

### In progress
- **Slice 9** — `GET /api/oracle` on branch `cursor/oracle-stub-slice9-e78a`

### Do not touch
- `internal/learning/routes.py`, scenario memory, pick history (Agent A slice 6/8)

---

## STATUS SNAPSHOT

| Item | Value |
|------|-------|
| **main** | `acb3050` (includes #71 indicators) |
| **Rebuild** | Incremental FastAPI — one `server.py` + `include_router` only |
| **Open PRs** | #72 slice 6 (A, draft), slice 9 oracle (B) — parallel |
| **Next merge** | #72 after rebase, then #73 oracle; rebase if contract conflicts |
| **Closed forever** | #63 monolith, #68 duplicate judges |

## Shared rules

1. **Single foundation** — `server:app` only; never restore `server_original.py` monolith
2. **One slice = one PR** to `main` (no stacked PRs)
3. **Conflict surface** — `server.py` (include_router lines only), `tests/test_endpoint_contract.py`
4. **Parallel OK** when modules differ (`internal/oracle` vs `internal/learning`)
5. **Rebase before merge** if the other agent landed while your PR was open

## Slice queue

| # | Slice | Owner | Status |
|---|-------|-------|--------|
| 1 | FastAPI foundation | A | ✅ #62 |
| 2 | SimiVision picks | A | ✅ #66 |
| 3 | Whale Intelligence | B | ✅ #65 |
| 4 | Judge Council | A | ✅ #67 |
| 4b | Ruggers facade | B | ✅ #70 |
| 5 | Learning read APIs | A | ✅ #69 |
| 6 | Learning write APIs | A | 🟡 #72 |
| 7 | Indicators read | B | ✅ #71 |
| 8 | Scenario memory + pick history | A | pending (after #72) |
| 9 | Oracle stub | B | 🟡 in progress |
| 10 | Rotation tracker | A | pending |
| 11 | SimiVision chat | A | pending |
