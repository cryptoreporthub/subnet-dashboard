# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-13T03:10:00Z by Agent A (`-843d`) — Phase O in PR  
**main:** `cc6de08`

## Repo
- `cryptoreporthub/subnet-dashboard`

## Read order (agents + Ditto)
1. **This file** — `cursor-agents-communication/board.md`
2. **Model guide** — `cursor-agents-communication/model-guide.md` (Composer vs Grok)
3. **Shared workspace** — `cursor-agents-communication/shared-workspace.md`
4. **Master plan** — `master-plan-merged.md` + `docs/master-plan-merged.md`
5. **Phase designs** — `phase-m-design.md`, `phase-n-design.md`, `phase-o-design.md`, L slice designs

## Ready for Ditto
**Agent A: Phase O PR open. Agent B idle.**

Recent merges on `main` @ `cc6de08` (all green CI):

| PR | Phase | Summary |
|----|-------|---------|
| **#138** | **N** | Calibration / retrain — Retrain → Cert → Fire |
| **#136** | **M** | Social ingestion — Telegram listener, `GET /api/message-intel` |
| **#115** | **L** | Signals pipeline, alerts API, WebSocket, rules engine |

**Health:** `GET /health` → 200 OK · `GET /api/calibration/status` → 200 · `GET /api/signals` → 200

## Gate Status

| Phase | Status | Notes |
|-------|--------|-------|
| **J** | ✅ merged | PR #105 |
| **H-full** | ✅ merged | PR #120 + #131 |
| **K** | ✅ merged | PR #107 |
| **L** | ✅ merged | PR #115 + hardening |
| **M** | ✅ merged | PR #136 |
| **N** | ✅ merged | PR #138 |
| **O** | 🟡 in PR | TAO Signal Hub — `phase-o-design.md` |

## Agent posture

| Agent | Status | Owns |
|-------|--------|------|
| **A** (`-843d`) | **Phase O** — signal hub PR | `internal/signal_hub/*`, council overlay |
| **B** (`-e78a`) | **Idle** | `templates/*`, `static/*`, analytics/indicators |

**Conflict surface:** `server.py` router includes + `tests/test_endpoint_contract.py`

## Rules
- Board + master plan + model guide override memory.
- Honest-empty > fake data.
- Auto-merge when CI green unless user says otherwise.

## References
- `cursor-agents-communication/phase-o-design.md`
- `cursor-agents-communication/phase-n-design.md`
- `docs/master-plan-merged.md` §12 (O)
