# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-13T20:05:00Z by Agent B (`-e78a`) — Phase 1 **C1 complete** (awaiting human review)  
**main:** `276cd19` · **branch:** `cursor/c1-css-split-4e98`

## Repo
- `cryptoreporthub/subnet-dashboard`

## Read order (agents + Ditto)
1. **This file** — `cursor-agents-communication/board.md`
2. **Model guide** — `cursor-agents-communication/model-guide.md`
3. **Master plan** — `docs/master-plan-merged.md`
4. **Phase designs** — `phase-m-design.md`, `phase-n-design.md`, `phase-o-design.md`, L slice designs

## Active — Phase 1 (UI structural splits)

| Task | Agent | Status | Notes |
|------|-------|--------|-------|
| **C1** — split `style.css` → 6 files | B (`-e78a`) | 🔄 **in progress** | `base`, `layout`, `dashboard`, `chat`, `premium`, `responsive` + template links |
| C2–C6 | — | blocked | after C1 merge + human review |

## Ready for Ditto
**Phases J–O merged. Phase 1 UI work started (C1).**

Recent merges on `main` @ `b1db31a` (CI green):

| PR | Phase | Summary |
|----|-------|---------|
| **#140** | **O** | TAO Signal Hub — `/api/signal-hub/*`, council overlay, L bridge |
| **#138** | **N** | Calibration / retrain — `/api/calibration/*`, Retrain → Cert → Fire |
| **#136** | **M** | Social ingestion — Telegram listener, `GET /api/message-intel` |
| **#115** | **L** | Signals, alerts, WebSocket, rules engine |
| **#105** | **J** | Accuracy fix — resolver, grading, replay |

**Health:** `GET /health` · `GET /api/signal-hub/status` · `GET /api/calibration/status` · `GET /api/signals` · `GET /api/message-intel` → 200 OK

## Gate Status

| Phase | Status |
|-------|--------|
| **J** | ✅ merged PR #105 |
| **H-full** | ✅ merged PR #120 + #131 |
| **K** | ✅ merged PR #107 |
| **L** | ✅ merged PR #115 + #133 + #135 |
| **M** | ✅ merged PR #136 |
| **N** | ✅ merged PR #138 |
| **O** | ✅ merged PR #140 |

## Agent posture

| Agent | Status | Owns |
|-------|--------|------|
| **A** (`-843d`) | **Idle** | learning, council, calibration, signal_hub, message_intel, cockpit |
| **B** (`-e78a`) | **C1** — CSS split | templates, static, analytics, indicators, oracle, whales |

**Conflict surface:** `server.py` router includes + `tests/test_endpoint_contract.py`

## Rules
- Board + master plan override memory.
- Honest-empty > fake data.
- Grok per `model-guide.md` for new high-risk subsystems only.

## References
- `cursor-agents-communication/phase-o-design.md`
- `cursor-agents-communication/phase-n-design.md`
- `cursor-agents-communication/phase-m-design.md`
- `docs/master-plan-merged.md`
