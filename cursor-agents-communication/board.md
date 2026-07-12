# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-12T23:05:00Z by Agent A (`-843d`) — post-merge coordination  
**main:** `5055a80`

## Repo
- `cryptoreporthub/subnet-dashboard`

## Read order (agents + Ditto)
1. **This file** — `cursor-agents-communication/board.md`
2. **Model guide** — `cursor-agents-communication/model-guide.md` (Composer vs Grok)
3. **Shared workspace** — `cursor-agents-communication/shared-workspace.md`
4. **Ditto handoff** — `cursor-agents-communication/ditto-phase-l-handoff.md`
5. **Master plan** — `master-plan-merged.md` + `docs/master-plan-merged.md` §9 (L)

## Post-merge coordination (Agent A) — **DONE**

| Task | PR | Merge commit | Status |
|------|-----|--------------|--------|
| Model guide | **#122** | `449b991` | ✅ merged (pre-task) |
| L signals pipeline | **#115** | `dc8c611` | ✅ merged (pre-task; includes slices 1–4) |
| H-full hero restore | **#131** | `5055a80` | ✅ merged (on current `main`) |

**Health verified @ `5055a80`:** `GET /health` → 200 OK · `GET /api/signals` → 200 success (128 signals)

**Agent A:** idle — no open merge gates.

## Gate Status

| Phase | Status | Notes |
|-------|--------|-------|
| **J** | ✅ merged | PR #105 |
| **H-thin** | ✅ merged | PR #104 |
| **K** | ✅ merged | PR #107 |
| **H-full** | ✅ merged | PR #120 + hero restore #131 |
| **H-full optional** | ✅ merged | PR #125 |
| **Model guide** | ✅ merged | PR #122 — `cursor-agents-communication/model-guide.md` |
| **L** | ✅ merged | PR #115 — signals, alerts, WebSocket, rules engine |

## Phase L — merged (Agent B)

| Slice | Capability | Status |
|-------|------------|--------|
| 1 | `GET /api/signals`, `/api/signals/summary`, `data/signals.json` | ✅ |
| 2 | `GET/POST /api/alerts`, `POST /api/alerts/subscribe` | ✅ |
| 3 | `/ws/signals` WebSocket | ✅ |
| 4 | `rules.py` — SELL > HOT, dedup | ✅ |

**Next:** M/N/O gated on user approval. Frontend signal consumers optional (Agent A, explicit task only).

## Rules
- Stay scoped to assigned phase.
- **Model guide:** merge/rebase/board → Composer; Grok only per §4–§5 triggers.
- Honest-empty > fake data.

## References
- `cursor-agents-communication/model-guide.md`
- `cursor-agents-communication/phase-l-pr113-audit.md`
- `cursor-agents-communication/phase-h-subnet-grouping-audit.md`
- `docs/master-plan-merged.md` §9
