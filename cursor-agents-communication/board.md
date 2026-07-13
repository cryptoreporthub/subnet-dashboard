# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-13T02:35:00Z by Agent A (`-843d`) — Phase N merged  
**main:** `cc6de08`

## Repo
- `cryptoreporthub/subnet-dashboard`

## Read order (agents + Ditto)
1. **This file** — `cursor-agents-communication/board.md`
2. **Model guide** — `cursor-agents-communication/model-guide.md` (Composer vs Grok)
3. **Shared workspace** — `cursor-agents-communication/shared-workspace.md`
4. **Master plan** — `master-plan-merged.md` + `docs/master-plan-merged.md`
5. **Phase designs** — `phase-m-design.md`, `phase-l-slice3-ws-design.md`, `phase-l-slice4-rules-design.md`

## Ready for Ditto
**Agents idle — awaiting next assignment (Phase O or Ditto prompt).**

Recent merges on `main` @ `cc6de08` (all green CI):

| PR | Phase | Summary |
|----|-------|---------|
| **#138** | **N** | Calibration / retrain — Retrain → Cert → Fire, `/api/calibration/*` |
| **#136** | **M** | Social ingestion — Telegram listener, dedup, `GET /api/message-intel`, Jinja context |
| **#135** | L UI | Phase L signals/alerts wired in premium cockpit + `/ws/signals` client |
| **#133** | L | Alerts hardening, correlation, Grok design docs |
| **#131** | H-full | Hero market snapshot, SimiVision picks, daily pick |
| **#115** | L | Signals pipeline, alerts API, WebSocket, rules engine |
| **#122** | docs | Model guide (Composer vs Grok) |

**Health:** `GET /health` → 200 OK · `GET /api/signals` → 200 · `GET /api/message-intel` → 200 (honest-empty when no messages)

## Gate Status

| Phase | Status | Notes |
|-------|--------|-------|
| **J** | ✅ merged | PR #105 |
| **H-thin** | ✅ merged | PR #104 |
| **K** | ✅ merged | PR #107 |
| **H-full** | ✅ merged | PR #120 + #131 hero restore |
| **H-full optional** | ✅ merged | PR #125 |
| **Model guide** | ✅ merged | PR #122 |
| **L** | ✅ merged | PR #115 + #133 hardening; UI #135 |
| **M** | ✅ merged | PR #136 — design: `phase-m-design.md` |
| **N** | ✅ merged | PR #138 — `phase-n-design.md`, safety review PASS |
| **O** | ⏸ gated | TAO Signal Hub — user approval |

## Agent posture

| Agent | Status | Owns |
|-------|--------|------|
| **A** (`-843d`) | **Idle** — ready for Ditto | `internal/calibration/*`, learning/council, cockpit, Phase O |
| **B** (`-e78a`) | **Idle** — ready for Ditto | `templates/*`, `static/*`, analytics/indicators/oracle |

**Conflict surface:** `server.py` router includes + `tests/test_endpoint_contract.py`

## Rules
- Board + master plan + model guide override memory.
- **Grok** only per `model-guide.md` §4–§5 (design before N/O; fast-xhigh default).
- Honest-empty > fake data.
- Auto-merge when CI green unless user says otherwise.

## References
- `cursor-agents-communication/phase-m-design.md`
- `cursor-agents-communication/phase-n-design.md`
- `cursor-agents-communication/phase-n-safety-review.md`
- `cursor-agents-communication/phase-l-slice3-ws-design.md`
- `cursor-agents-communication/phase-l-slice4-rules-design.md`
- `docs/master-plan-merged.md` §10 (M), §11 (N), §12 (O)
