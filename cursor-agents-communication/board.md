# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-13T21:55:00Z by Agent B (`-e78a`) — Phase 3 **G9–G11** in PR  
**main:** `b4326bf`

## Repo
- `cryptoreporthub/subnet-dashboard`

## Read order (agents + Ditto)
1. **This file** — `cursor-agents-communication/board.md`
2. **Model guide** — `cursor-agents-communication/model-guide.md`
3. **Implementation guide** — `docs/cursor-implementation-guide.md` (Grok token rules)
4. **Phase 3 Grok spec** — `cursor-agents-communication/phase-3-grok-design.md`
5. **Phase 3 backend spec** — `cursor-agents-communication/phase-3-grok-backend-design.md`

## Grok switches (required)

| Step | Model | When |
|------|-------|------|
| Design / audit | **Grok xhigh** (`grok-4.5-xhigh`) | Before Composer builds Phase 3+ visual/UX |
| Implementation | **Composer** | After Grok spec locked |
| Pre-merge sign-off | **Grok xhigh** | Before merge on visual/behavioral phases |

Composer spawns Grok via subagent — no manual model picker needed. Batch tasks; scope files only.

## Active — Phase 3 complete, Phase 4 next

| Task | Agent | Status | Notes |
|------|-------|--------|-------|
| **Phase 1–2** | B | ✅ **merged** | #154 · #155 · #157 |
| **G3** caret UX | B | ✅ **merged** | #159 |
| **G4** inline → CSS | B | ✅ **merged** | #159 |
| **G9** confidence calibration | B | 🔄 **PR open** | resolver hit-rate prior |
| **G10** effective weights | B | 🔄 **PR open** | regime-aware, no persist |
| **G11** round-robin resolver | B | 🔄 **PR open** | `RESOLVER_BATCH_SIZE` |
| C3–C6 | Composer | backlog | Phase 4/6 |

## Ready for Ditto
**Phase 3 G9–G11 PR pending human review. Phase 4 (C4–C6 hydration) next after merge.**

Recent merges on `main` @ `82bbde7` (CI green):

| PR | Phase | Summary |
|----|-------|---------|
| **#157** | **Phase 2** | G1/G2/G5/G6/G8 visual fixes |
| **#155** | **Phase 1 C2** | Cockpit section partials |
| **#154** | **Phase 1 C1** | CSS split |

**Health:** `GET /health` · `GET /api/signal-hub/status` · `GET /api/calibration/status` · `GET /api/signals` · `GET /api/message-intel` → 200 OK

## Gate Status

| Phase | Status |
|-------|--------|
| **UI Phase 1** | ✅ merged #154 + #155 |
| **UI Phase 2** | ✅ merged #157 (Grok sign-off: CONDITIONAL — see phase-3-grok-design.md) |
| **J–O** | ✅ merged |

## Agent posture

| Agent | Status | Owns |
|-------|--------|------|
| **A** (`-843d`) | **Idle** | learning, council, calibration, signal_hub, message_intel, cockpit |
| **B** (`-e78a`) | **Phase 3 G3+G4** | templates, static, analytics, indicators, oracle, whales |

**Conflict surface:** `server.py` router includes + `tests/test_endpoint_contract.py`

## Rules
- Board + master plan override memory.
- Honest-empty > fake data.
- **Grok xhigh** for Phase 3+ design and pre-merge sign-off per table above.

## References
- `cursor-agents-communication/phase-3-grok-design.md`
- `docs/cursor-implementation-guide.md`
- `docs/master-plan-merged.md`
