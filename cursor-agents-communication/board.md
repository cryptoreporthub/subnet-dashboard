# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-12T19:55:00Z by Agent B (`-e78a`)  
**main:** `95b4c20`

## Repo
- `cryptoreporthub/subnet-dashboard`

## Read order (agents + Ditto)
1. **This file** — `cursor-agents-communication/board.md`
2. **Model guide** — `cursor-agents-communication/model-guide.md` (Composer vs Grok)
3. **Shared workspace** — `cursor-agents-communication/shared-workspace.md`
4. **Ditto handoff** — `cursor-agents-communication/ditto-phase-l-handoff.md`
5. **Master plan** — `master-plan-merged.md` + `docs/master-plan-merged.md` §9 (L)

## Gate Status

| Phase | Status | Notes |
|-------|--------|-------|
| **J** | ✅ merged | PR #105 |
| **H-thin** | ✅ merged | PR #104 |
| **K** | ✅ merged | PR #107 |
| **H-full** | ✅ merged | PR #120 |
| **H-full optional** | ✅ merged | PR #125 |
| **L slice 1** | ✅ on branch | `GET /api/signals`, persistence — PR #115 |
| **L slices 2–4** | 🟢 **in progress** | Agent B — alerts, WS, rules engine |

## Active Work — Phase L (Agent B)

| Slice | Scope | Status |
|-------|--------|--------|
| 1 | `GET /api/signals`, `/api/signals/summary`, `data/signals.json` | ✅ done |
| 2 | `GET/POST /api/alerts` | ✅ done |
| 3 | `/ws/signals` WebSocket | ✅ done |
| 4 | Rules engine (SELL > HOT, dedup) | ✅ done |

**Branch:** `cursor/phase-l-signal-pipeline-b061`  
**Audit:** PR #113 (`cursor/phase-l-signals-alerts-b061`) — reference only; do not duplicate wholesale  
**Do not touch:** `templates/*`, `static/*`, resolver, grading weights

## Rules
- Stay scoped to assigned phase.
- Agent B: `internal/signals/*`, `server.py` router + Jinja context only.
- Honest-empty > fake data.

## References
- `cursor-agents-communication/model-guide.md`
- `cursor-agents-communication/phase-h-subnet-grouping-audit.md`
- `docs/master-plan-merged.md` §9
