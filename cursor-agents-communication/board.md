# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-15T02:45:00Z by Agent (`-6f98`) — **N/O Step 0 LOCKED; #221 merged**  
**main:** `778ad13`

## Ditto boot (read first)

**`cursor-agents-communication/STATUS.md`** — one-page truth card.  
**Step 0 spec:** `cursor-agents-communication/phase-n-o-step0-spec.md` (binding).

## Repo
- `cryptoreporthub/subnet-dashboard`

## N/O (approved 2026-07-15)
- **APPROVED** + **Step 0 LOCKED** — Agent A (`-843d`) + Agent B (`-e78a`).
- Specs: `gameplan-N-O.md` · `phase-n-o-step0-spec.md`
- Models: Composer 2.5 default; **Grok token-save** (`grok-4.5-fast-xhigh` first).
- Old Phase O (`phase-o-design.md` / `signal_hub`) = **SUPERSEDED / COMPLETE — do not rebuild**.
- **A start:** N2 (or N3/O1 in parallel). **B start:** N4 first.

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

**Phase N/O — Step 0 LOCKED.** A/B Composer builds unblocked after Step 0 PR merges.

**Automated July 14 queue:** COMPLETE. **A2:** `smoke` required on `main`.

Recent merges on `main` @ `778ad13`:

| PR | Phase | Summary |
|----|-------|---------|
| **#221** | Docs | N/O gameplan + Grok token-save + pre-flight |
| **#218** | Ops | Fly 1GB + post-deploy restart/health gate |
| **#217** | Social | Message-intel social sentiment |
| **#215** | UI | Canvas radar replaces Chart.js CDN |

**Health:** `GET /health` · `GET /api/data-freshness` · `GET /api/signal-hub/status` · `GET /api/calibration/status` · `GET /api/message-intel` → 200 OK  
**Fly:** machine `shared-cpu-1x:1024MB`, checks passing (was critical on 256MB).

**Housekeeping done:** closed stale open PRs #101 #110 #112 #129 #130 #134 #139 #153 #165 #166 #184.

## Gate Status

| Phase | Status |
|-------|--------|
| **UI Phase 1** | ✅ merged #154 + #155 |
| **UI Phase 2** | ✅ merged #157 (Grok sign-off: CONDITIONAL — see phase-3-grok-design.md) |
| **J–M** | ✅ merged |
| **N/O** | 🟡 APPROVED — not started |

## N/O queue
| Agent | Slices | Status |
|-------|--------|--------|
| **A** (`-843d`) | N2, N3, O1, O4, O5 | awaiting agent start |
| **B** (`-e78a`) | N1, N4, O2, O3 | awaiting agent start |

Full spec: `cursor-agents-communication/gameplan-N-O.md`. Models: Composer 2.5 default; **Grok token-save** (`grok-4.5-fast-xhigh` first; escalate `xhigh` only after FAIL/CONDITIONAL).

## Agent posture

| Agent | Status | Notes |
|-------|--------|-------|
| **Cursor** | **Idle** | Queues + Fly fix complete; monitor only |
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