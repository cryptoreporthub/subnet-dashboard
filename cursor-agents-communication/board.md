# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-12T22:45:00Z by Agent B (`-e78a`)  
**main:** `dc8c611` (Phase L merged — PR #115)

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
| **L** | ✅ merged | PR #115 — signals, alerts, WebSocket, rules engine |

## Phase L — merged (Agent B)

| Slice | Capability | Status |
|-------|------------|--------|
| 1 | `GET /api/signals`, `/api/signals/summary`, `data/signals.json` | ✅ |
| 2 | `GET/POST /api/alerts`, `POST /api/alerts/subscribe` | ✅ |
| 3 | `/ws/signals` WebSocket | ✅ |
| 4 | `rules.py` — SELL > HOT, dedup | ✅ |

**Next:** Agent A may wire frontend consumers; M/N/O gated on user approval.

## Rules
- Stay scoped to assigned phase.
- Agent B: `internal/signals/*`, `server.py` router + Jinja context only.
- Honest-empty > fake data.

## References
- `cursor-agents-communication/model-guide.md`
- `cursor-agents-communication/phase-h-subnet-grouping-audit.md`
- `docs/master-plan-merged.md` §9
