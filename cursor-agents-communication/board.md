# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-15T15:05:00Z — **`GATE_HABIT` CLEAR · A:F3 · B:U2**  
**main:** `a451bcc`

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

## Ready for next work

**`GATE_HABIT` CLEAR** (F1 #254 + F2 #256 + U1 #255). **`GATE_S_CORE` / `GATE_S16` CLEAR.**  
**Agent A:** F3 paper portfolio (this PR). **Agent B:** U2 story strip.

| PR | Role | State |
|----|------|-------|
| **#256** | §17.F2 alert delivery | ✅ **merged** |
| **#255** | §17.U1 single-job home | ✅ **merged** |
| **#254** | §17.F1 watchlist | ✅ **merged** |
| **#253** | Grok lock HARD RULE | ✅ **merged** |
| **#252** | §17.S3 whale badge | ✅ **merged** |
| **#250** | §17.S2 magnitude | ✅ **merged** |
| **#248** | §17.S4 honest depth | ✅ **merged** |
| **#247** | §17.S1 conviction bands | ✅ **merged** |
| **#244–#246** | §16 | ✅ **merged** |

**Health:** `GET /health` · `GET /api/data-freshness` · `GET /api/portfolio/status` · `GET /api/watchlist` → 200 OK  
**Fly:** machine `shared-cpu-1x:1024MB`, checks passing.

## Gate Status

| Phase | Status |
|-------|--------|
| **UI Phase 1** | ✅ merged #154 + #155 |
| **UI Phase 2** | ✅ merged #157 |
| **J–M** | ✅ merged |
| **N/O** | ✅ **COMPLETE** — #227 (A) + #228 (B) |
| **P** | ✅ **COMPLETE** — #232 + #237 |
| **§16** | ✅ **`GATE_S16` CLEAR** — #244 · #245 · #246 |
| **§17** | 🟡 **IN PROGRESS** — habit spine done; A→F3; B→U2 |

## §16 / §17 execution
| Agent | Queue | Status |
|-------|--------|--------|
| **A** (`-843d`) | F1+F2 ✅ · **F3 paper portfolio** → wait `GATE_ACCOUNT` → F4 | building |
| **B** (`-e78a`) | U1 ✅ · **U2 story strip** → F1/F2 UI → U3 | next |
| **Human** | F7 DNS | anytime |

Specs: `s16-s17-automated-build-plan.md`. **GATE_HABIT** = F1+F2+U1. **GATE_ACCOUNT** = F3 on main.

## Agent posture

| Agent | Status | Notes |
|-------|--------|-------|
| **A** | **Building F3** | Paper portfolio engine; then wait GATE_ACCOUNT for F4 |
| **B** | **Build U2** | Story strip |
| **Ditto** | **Gate/spot-check** | Not day-to-day QB |

**Conflict surface:** `server.py` router includes + `tests/test_endpoint_contract.py`

## Rules
- Board + master plan override memory.
- Honest-empty > fake data.
- **Grok slow + medium default** — escalate to **high** only if medium fails or is unsatisfactory.
- **HARD RULE — Grok lock → Composer write:** short LOCK only; Composer writes plan + builds. Skip Grok when auto plan already locks the slice.
- **Build caching** — read binding specs once per session; scope reads to owned paths (`model-guide.md`).

## References
- `cursor-agents-communication/phase-3-grok-design.md`
- `docs/cursor-implementation-guide.md`
- `cursor-agents-communication/s16-s17-automated-build-plan.md`
- `cursor-agents-communication/grok-lock-composer-write-rule.md`
