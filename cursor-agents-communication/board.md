# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-12T17:55:00Z by Cursor Agent (subnet grouping UI lane)  
**main:** `1d50232` (H-full #120 merged)

## Repo
- `cryptoreporthub/subnet-dashboard`

## Source of Truth
- This board and `master-plan-merged.md` override memory, prior summaries, and informal instructions.
- Agents must read this file first.

## Phase Order (canonical)
1. **J** → Accuracy fix + tests
2. **H-full** → Premium UI cockpit restoration
3. **K** → CI quality gates
4. **L** → Real-time signals & alerts

> **H-thin** (PR #104) is the partial H shell already on `main`. **H-full** is the remaining premium UI work.

## Gate Status

| Phase | Status | Notes |
|-------|--------|-------|
| **J** | ✅ merged | PR #105 |
| **H-thin** | ✅ merged | PR #104 — 12 cockpit cards on `main` |
| **K** | ✅ merged · **unblocked** | PR #107 — CI gates on `main`; no longer gates H-full or L |
| **H-full** | ✅ merged | PR #120 on `main` |
| **H-full optional** | 🟢 **done** | Per-subnet grouping UI — branch `cursor/phase-h-subnet-grouping-ui-4e98` |
| **L** | 🟡 slice 1 | Agent B — backend-owned; separate from H-full |

## Active Work

### Optional lane — per-subnet grouping / collapse (H-full)

Parallel UI lane inside H-full; does **not** block L.

| Owner | Task | Status |
|---|---|---|
| **Agent B** | Data-flow audit + `netuid` alias on `/api/registry` | **Done** — `phase-h-subnet-grouping-audit.md` |
| **Agent A** | Collapsible per-subnet rollup in premium cockpit | **Done** — `cursor/phase-h-subnet-grouping-ui-4e98` |

**Rules:** frontend-only; bucket by `netuid ?? id`; **do not** group the 12-card `cockpit_sections` grid.

### H-full (Agent A) — frontend
- **Owner:** Agent A (`-843d`)
- **Scope:** `templates/*`, `static/*`, `tests/test_phase_h_ui.py`
- **Recommended branch:** `cursor/phase-h-full-premium-ac2c-42f7` (PR #120, 20 UI tests, Chart.js)
- **Alternates:** `cursor/phase-h-full-premium-ac2c`, `27f3`, PR #111 (`e78a`)
- **Backend context only:** `cursor/phase-h-full-premium-843d` (PR #110) — merge **after** UI branch
- **Do not touch:** `internal/signals/*`, resolver, grading, learning weights

### L (Agent B) — backend
- **Owner:** Agent B (`-e78a`)
- **Scope:** `internal/signals/*`, alerts, WebSocket; Jinja context via `server.py` only
- **Branch:** `cursor/phase-l-signal-pipeline-b061` (PR #115 draft)
- **Slice 1 done:** `GET /api/signals`, `/api/signals/summary`, `data/signals.json`
- **Remaining:** alerts (`GET/POST /api/alerts`), `/ws/signals`
- **Do not touch:** `templates/*`, `static/*`, resolver, grading weights
- **Extended branch to audit:** `cursor/phase-l-signals-alerts-b061` (PR #113) — do not duplicate

## Parallel Work (no file overlap)

```text
Agent A: templates/*, static/*, tests/test_phase_h_ui.py
Agent B: internal/signals/*, server.py (router + Jinja context only)
Conflict surface: server.py — coordinate if both open PRs; second merger rebases.
```

## Rules
- Stay scoped to the assigned phase.
- **Do not overlap H-full and L** unless the user explicitly approves parallel merge.
- Do not modify resolver, grading, or learning-engine logic unless required for compatibility.
- Keep changes minimal and behavior-preserving.

## Blockers
- None between Agent A and Agent B (parallel OK, no path overlap).
- User merge required before M/N/O.

## Coordination (Cloud Agents)
```text
Boot:  read cursor-agents-communication/board.md (this file)
       optional: search_memories("cursor-agents-communication board")
Write: save_memory(content=..., source="cursor-agents-communication")
Do NOT use fetch_memories(["f93f7202"]) for board state this sprint.
```

## References
- `master-plan-merged.md` (short canonical plan at repo root)
- `docs/master-plan-merged.md` (extended history and contracts)
- `cursor-agents-communication/shared-workspace.md` (handoff order)
- `cursor-agents-communication/concurrent-protocol.md` (J/H-thin sprint — superseded for H-full/L split)
