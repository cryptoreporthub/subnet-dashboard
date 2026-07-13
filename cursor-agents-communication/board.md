# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-13T00:50:00Z by Agent B (`-e78a`) — Phase L complete, Ditto-ready  
**main:** `fbf0f27` (PR #133 merged)

## Repo
- `cryptoreporthub/subnet-dashboard`

## Read order (agents + Ditto)
1. **This file** — `cursor-agents-communication/board.md`
2. **Model guide** — `cursor-agents-communication/model-guide.md` (Composer vs Grok)
3. **Shared workspace** — `cursor-agents-communication/shared-workspace.md`
4. **Ditto handoff** — `cursor-agents-communication/ditto-mno-handoff.md`
5. **Master plan** — `master-plan-merged.md` + `docs/master-plan-merged.md` §10–12 (M/N/O)

## ✅ Ready for Ditto

| Agent | Status | Notes |
|-------|--------|-------|
| **Agent A** (`-843d`) | **Idle** | H-full + optional lane done; awaiting M/N/O plan |
| **Agent B** (`-e78a`) | **Idle** | Phase L complete (#115 + #133); Grok-fast PASS |
| **Ditto** | **Action needed** | Create M/N/O assignment plans — see `ditto-mno-handoff.md` |

**Health @ `fbf0f27`:** `GET /health` 200 · `GET /api/signals` 200 · `GET /api/alerts` 200

## Gate Status

| Phase | Status | Notes |
|-------|--------|-------|
| **J** | ✅ merged | PR #105 |
| **H-thin** | ✅ merged | PR #104 |
| **K** | ✅ merged | PR #107 |
| **H-full** | ✅ merged | PR #120 + hero #131 |
| **H-full optional** | ✅ merged | PR #125 |
| **Model guide** | ✅ merged | PR #122 |
| **L** | ✅ merged | PR #115 + hardening **#133** @ `fbf0f27` |
| **M** | 🔒 gated | User approval + Ditto plan |
| **N** | 🔒 gated | User approval + Ditto plan |
| **O** | 🔒 gated | User approval + Ditto plan |

## Phase L — complete

| Slice | Capability | PR |
|-------|------------|-----|
| 1 | `GET /api/signals`, persistence | #115 |
| 2 | Alerts API (filters, 201/400, idempotency) | #133 |
| 3 | `/ws/signals` WebSocket | #133 |
| 4 | `rules.py` + `correlation.py` | #133 |

**Design docs:** `phase-l-slice3-ws-design.md`, `phase-l-slice4-rules-design.md`

## Rules
- Grok-fast: design/audit/sign-off only; Composer implements
- M/N/O: no agent work until Ditto plan + user approval
- Honest-empty > fake data

## References
- `cursor-agents-communication/ditto-mno-handoff.md`
- `cursor-agents-communication/model-guide.md`
- `docs/master-plan-merged.md` §9–12
