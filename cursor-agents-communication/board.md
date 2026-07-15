# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-15T05:32:00Z — **Phase N/O + Phase P COMPLETE**  
**main:** `7e1f0b3`

## Ditto boot (read first)

**`cursor-agents-communication/STATUS.md`** — one-page truth card.  
**Step 0 spec:** `cursor-agents-communication/phase-n-o-step0-spec.md` (binding).

## Repo
- `cryptoreporthub/subnet-dashboard`

## N/O (approved 2026-07-15)
- **APPROVED** + **Step 0 LOCKED** — Agent A (`-843d`) + Agent B (`-e78a`).
- Specs: `gameplan-N-O.md` · `phase-n-o-step0-spec.md`
- Models: Composer 2.5 default; **Grok slow + medium** (escalate to **high** only if medium fails / unsatisfactory).
- Old Phase O (`phase-o-design.md` / `signal_hub`) = **SUPERSEDED / COMPLETE — do not rebuild**.
- **A:** N2→N3→O1→O4→O5 ✅ **#227 merged**. **B:** N4→N1→O2→O3 ✅ **#228 merged**. **Phase N/O code-complete.**

## Read order (agents + Ditto)
1. **STATUS card** — `cursor-agents-communication/STATUS.md` (Ditto: start here)
2. **This file** — `cursor-agents-communication/board.md`
3. **Handoff** — `cursor-agents-communication/cursor-handoff-2026-07-14.md` (context + guardrails)
3. **Model guide** — `cursor-agents-communication/model-guide.md`
4. **Implementation guide** — `docs/cursor-implementation-guide.md` (Grok token rules)
5. **Phase 3 Grok spec** — `cursor-agents-communication/phase-3-grok-design.md`
6. **Phase 3 backend spec** — `cursor-agents-communication/phase-3-grok-backend-design.md`

## Grok switches (slow-medium default)

| Step | Model | When |
|------|-------|------|
| Design / audit | **Grok slow + medium** | Before Composer builds Phase 3+ visual/UX — escalate to **high** only if FAIL/unsatisfactory |
| Implementation | **Composer** | After Grok spec locked |
| Pre-merge sign-off | **Grok slow + medium** | Before merge on visual/behavioral phases — escalate to **high** only if FAIL/unsatisfactory |

Composer spawns Grok via subagent — starts slow + medium; no manual model picker needed. Batch tasks; scope files only.

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

**Phase N/O + Phase P COMPLETE** (#227 · #228 · #232). Agents idle — monitor backtest lift.  
**Human optional:** custom domain DNS (`DEPLOY.md`). Ditto defines next roadmap slice.

**Automated July 14 queue:** COMPLETE. **A2:** `smoke` required on `main`.

Recent merges on `main` @ `778ad13`:

| PR | Phase | Summary |
|----|-------|---------|
| **#225** | Docs | Grok slow+medium default (not fast-first) |
| **#223** | Docs | Step 0 architecture lock |
| **#221** | Docs | N/O gameplan + pre-flight |
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
| **N/O** | ✅ **COMPLETE** — #227 (A) + #228 (B) |
| **P** | ✅ **COMPLETE** — #232 (prod flags + N1 hardening) |
| **P** | 🟢 **ACTIVE** — prod flags + N1 follow-through |

## N/O queue
| Agent | Slices | Status |
|-------|--------|--------|
| **A** (`-843d`) | P1–P3 | **in PR** — prod flags + snapshot persist |
| **B** (`-e78a`) | — | idle / monitor backtest UI |

Specs: `gameplan-N-O.md` + `phase-n-o-step0-spec.md`. Models: Composer 2.5; **Grok slow + medium** (escalate **high** only if FAIL/unsatisfactory).

## Agent posture

| Agent | Status | Notes |
|-------|--------|-------|
| **Cursor** | **Idle** | Queues + Fly fix complete; monitor only |
| **Ditto** | **Monitor** | Read-only — CI, Fly health, `/api/data-freshness` |

**Conflict surface:** `server.py` router includes + `tests/test_endpoint_contract.py`

## Rules
- Board + master plan override memory.
- Honest-empty > fake data.
- **Grok slow + medium default** — escalate to **high** only if medium fails or is unsatisfactory (Phase 3+ design, pre-merge sign-off, Step 0).

## References
- `cursor-agents-communication/phase-3-grok-design.md`
- `docs/cursor-implementation-guide.md`
- `docs/master-plan-merged.md`