# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-14T02:30:00Z by Agent A (`-6f98`) — **Phase A complete** (#167 #168 #170); Phase B next  
**main:** `4250505`

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

## Phase A — EXTREME audit (complete)

| Task | Agent | Status | Notes |
|------|-------|--------|-------|
| **A1** cruft deletion | Ditto → Cursor | ✅ **merged** | #170 (superseded #165) |
| **A3/A4 prompts** | Ditto → Cursor | ✅ **merged** | #170 (superseded #166) |
| **Audit docs** | Ditto | ✅ **merged** | #167 |
| **A3** CORS + X-Frame-Options (#11) | Cursor | ✅ **merged** | #168 |
| **A4** Cockpit panel isolation (#8) | Cursor | ✅ **merged** | #168 |
| **A2** CI smoke gate | Cursor | ✅ **in progress** | #172 — start uvicorn + remove `|| true` |

## Active — Phase B (data truth)

| Task | Agent | Status | Notes |
|------|-------|--------|-------|
| **B1** bittensor feed + `/api/data-freshness` | Ditto + Cursor UI | backlog | audit #1 — stale registry |
| **B2–B6** async/scheduler/observability | Ditto | backlog | per IMPLEMENTATION_PLAN.md |

## Active — Phase 4 (hydration scripts)

| Task | Agent | Status | Notes |
|------|-------|--------|-------|
| **Phase 1–2** | B | ✅ **merged** | #154 · #155 · #157 |
| **G3+G4** | B | ✅ **merged** | #159 |
| **G9–G11** | B | ✅ **merged** | #161 — Grok sign-off PASS |
| **C4** hydration binders | B | backlog | `base.html` + chart paint |
| **C5** APY/confidence fix | B | backlog | after C4 |
| **C6** conviction tiers | B | backlog | after C5 |
| C3 htmx | Composer | backlog | Phase 6 |

## Ready for Ditto
**Phase 3 complete. Phase 4 C4 (hydration/chart binders) next — human go-ahead.**

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
| **A** (`-843d`) | **Phase A A3+A4** | learning, council, calibration, signal_hub, message_intel, cockpit |
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
