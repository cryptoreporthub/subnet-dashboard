# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-14T08:15:00Z by Agent (`-5e45`) — **G7+G12 cleanup**  
**main:** `bc23671` (pre-merge)

## Repo
- `cryptoreporthub/subnet-dashboard`

## Read order (agents + Ditto)
1. **Handoff** — `cursor-agents-communication/cursor-handoff-2026-07-14.md` (Ditto → Cursor full ownership)
2. **This file** — `cursor-agents-communication/board.md`
3. **Model guide** — `cursor-agents-communication/model-guide.md`
4. **Implementation guide** — `docs/cursor-implementation-guide.md` (Grok token rules)
5. **Phase 3 Grok spec** — `cursor-agents-communication/phase-3-grok-design.md`
6. **Phase 3 backend spec** — `cursor-agents-communication/phase-3-grok-backend-design.md`

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
| **A2** CI smoke gate + branch protection | Cursor | ✅ **complete** | #172 + `smoke` required on `main` |

## Active — Phase B (data truth)

| Task | Agent | Status | Notes |
|------|-------|--------|-------|
| **B1** bittensor feed + `/api/data-freshness` | Cursor | ✅ **merged** | #174 feed + UI badge |
| **B1 UI** freshness badge | Cursor | ✅ **merged** | #177 |
| **B2** httpx + tenacity + aiocache | Cursor | ✅ **merged** | #179 — audit #4 |
| **B4** prometheusrock metrics | Cursor | ✅ **merged** | #181 — audit #13 |
| **B5** APY reconcile + candle gate | Cursor | ✅ **merged** | #182 |
| **B6** slowapi rate-limit | Cursor | ✅ **merged** | #185 |

## Active — Phase 4 (hydration scripts)

| Task | Agent | Status | Notes |
|------|-------|--------|-------|
| **Phase 1–2** | B | ✅ **merged** | #154 · #155 · #157 |
| **G3+G4** | B | ✅ **merged** | #159 |
| **G9–G11** | B | ✅ **merged** | #161 — Grok sign-off PASS |
| **C4** hydration binders | Cursor | ✅ **merged** | #186 |
| **C5** APY/confidence fix | Cursor | ✅ **merged** | #187 |
| **C6** conviction tiers | Cursor | ✅ **merged** | #189 |
| **C1** uPlot sparklines | Cursor | ✅ **merged** | #190 |
| **C2** SSE cockpit stream | Cursor | ✅ **merged** | #191 |
| **C3** CSS/mobile/a11y | Cursor | ✅ **merged** | #192 |
| **G7** Rajdhani section titles | Cursor | 🔄 **in PR** | `-5e45` |
| **G12** favicon + font cleanup | Cursor | 🔄 **in PR** | `-5e45` |

## Ready for next work
**Automated queue:** COMPLETE — B6 #185 · C4 #186 · C5 #187 · C6 #189 · C1 #190 · C2 #191 · C3 #192 · board #193. **A2:** `smoke` required check verified on `main`.

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
