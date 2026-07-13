# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-13T20:45:00Z by Agent B (`-e78a`) — Phase 2 **merged** (#157)  
**main:** `d2a6dd7`

## Repo
- `cryptoreporthub/subnet-dashboard`

## Read order (agents + Ditto)
1. **This file** — `cursor-agents-communication/board.md`
2. **Model guide** — `cursor-agents-communication/model-guide.md`
3. **Master plan** — `docs/master-plan-merged.md`
4. **Phase designs** — `phase-m-design.md`, `phase-n-design.md`, `phase-o-design.md`, L slice designs

## Active — Phase 3 (UX + backend)

| Task | Agent | Status | Notes |
|------|-------|--------|-------|
| **Phase 1** C1 + C2 | B (`-e78a`) | ✅ **merged** | #154 · #155 |
| **Phase 2** G1–G8 | B (`-e78a`) | ✅ **merged** PR #157 |
| **G3–G11** | — | ready | await human go-ahead |
| C3–C6 | Composer | backlog | Phase 4/6 per guide |

## Ready for Ditto
**Phase 2 merged on `main`. Phase 3 (G3–G11) next after human go-ahead.**

Recent merges on `main` @ `d2a6dd7` (CI green):

| PR | Phase | Summary |
|----|-------|---------|
| **#157** | **Phase 2** | G1/G2/G5/G6/G8 visual fixes — canvas wraps, contrast, sparklines |
|----|-------|---------|
| **#155** | **Phase 1 C2** | Split `premium_cockpit.html` → 22 section partials |
| **#154** | **Phase 1 C1** | Split `style.css` → 6 focused CSS files |
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
| **B** (`-e78a`) | **Idle** — Phase 3 ready | templates, static, analytics, indicators, oracle, whales |

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
