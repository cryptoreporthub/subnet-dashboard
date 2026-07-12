# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-12T16:40:00Z by Cursor Agent A (`-843d`)  
**main:** `1d50232`

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

> **H-thin** (PR #104) is the partial H shell on `main`. **H-full** shipped in PR #120 (Chart.js, 13 sections).

## Gate Status

| Phase | Status | Notes |
|-------|--------|-------|
| **J** | ✅ merged | PR #105 |
| **H-thin** | ✅ merged | PR #104 — 12 cockpit cards on `main` |
| **K** | ✅ merged · **unblocked** | PR #107 — CI gates on `main` |
| **H-full** | ✅ merged | PR #120 — premium cockpit on `main` |
| **L** | 🟢 **active** | Agent B — backend-owned; PR #115 slice 1 |

## Active Work

### H-full (Agent A) — complete on `main`
- **Merged:** PR #120 (`cursor/phase-h-full-premium-ac2c-42f7`)
- **Optional follow-up:** backend context builders on PR #110 (`cursor/phase-h-full-premium-843d`) if extra Jinja context needed
- **Close superseded:** PR #111 (`e78a` alternate H-full)

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
