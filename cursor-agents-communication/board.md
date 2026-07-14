# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-14T21:45:00Z by Agent (`-6f98`) — **completion queue** (#215 canvas radar)  
**main:** `30c4141`

## Ditto boot (read first)

**`cursor-agents-communication/STATUS.md`** — one-page truth card.  
Automated queue **COMPLETE**. B2/A2/Phase K are **not** open. Ditto = monitor only.

## Repo
- `cryptoreporthub/subnet-dashboard`

## Read order (agents + Ditto)
1. **STATUS card** — `cursor-agents-communication/STATUS.md` (Ditto: start here)
2. **This file** — `cursor-agents-communication/board.md`
3. **Handoff** — `cursor-agents-communication/cursor-handoff-2026-07-14.md` (context + guardrails)
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
| **G7** Rajdhani section titles | Cursor | ✅ **merged** | #195 |
| **G12** favicon + font cleanup | Cursor | ✅ **merged** | #195 |

## Ready for next work

**In flight:** #215 — remove Chart.js radar CDN; canvas radar in `uplot_charts.js` (audit #10 completion).

**EXTREME audit:** ✅ **COMPLETE** — all 16 findings addressed (#215 closes #10 radar deferral).

**Automated queue:** COMPLETE — B6–C3 · G7+G12 · #198–#214. **A2:** `smoke` required on `main`.

Recent merges on `main` @ `30c4141`:

| PR | Phase | Summary |
|----|-------|---------|
| **#214** | Board | Call-quality lane complete (#201–#213) |
| **#213** | Council | Priced scoring + SimiVision call lines |
| **#212** | Data | Lazy OHLCV fill + audit #15/#16 polish |
| **#211** | Board | STATUS sync after #210 |
| **#210** | Council | Hourly prediction + learning signal stamps |
| **#207** | Council | Call reasons from signal-impact |
| **#204** | Learning | Impact dial through full loop |
| **#198** | UI | Council-first overhaul |
| **#195** | **G7+G12** | Rajdhani titles, favicon, fonts |
| **#190** | **C1** | uPlot sparklines |
| **#185** | **B6** | slowapi rate limit |

**Health:** `GET /health` · `GET /api/signal-hub/status` · `GET /api/calibration/status` · `GET /api/signals` · `GET /api/message-intel` → 200 OK

## Gate Status

| Phase | Status |
|-------|--------|
| **UI Phase 1** | ✅ merged #154 + #155 |
| **UI Phase 2** | ✅ merged #157 (Grok sign-off: CONDITIONAL — see phase-3-grok-design.md) |
| **J–O** | ✅ merged |

## Agent posture

| Agent | Status | Notes |
|-------|--------|-------|
| **Cursor** | **Active** | #215 canvas radar — final audit #10 item |
| **Ditto** | **Monitor** | Read-only — CI, Fly health, `/api/data-freshness` |

**Conflict surface:** `server.py` router includes + `tests/test_endpoint_contract.py`

## Rules
- Board + master plan override memory.
- Honest-empty > fake data.
- **Grok xhigh** for Phase 3+ design and pre-merge sign-off per table above.

## References
- `cursor-agents-communication/phase-3-grok-design.md`
- `docs/cursor-implementation-guide.md`
- `docs/master-plan-merged.md`
