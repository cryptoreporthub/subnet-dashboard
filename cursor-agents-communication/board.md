# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-15T17:45:00Z — **ONE AGENT · B9 in flight**  
**main:** `58925a7`

## Ditto boot (read first)

**`cursor-agents-communication/STATUS.md`** — one-page truth card.  
**Step 0 spec:** `cursor-agents-communication/phase-n-o-step0-spec.md` (binding).

## Repo
- `cryptoreporthub/subnet-dashboard`

## Execution mode (active 2026-07-15)

**Human upgraded to Cursor Pro+.** Run **one primary Cloud Agent** + **Grok subagent** for DESIGN locks only.

| | Old (dual agent) | Now |
|--|------------------|-----|
| **Agents** | A (`-843d`) + B (`-e78a`) parallel | **One agent** owns B UI tail |
| **A** | Learning/council F1–F6 | **Retired / idle** — do not spawn |
| **B scope** | templates/static UI | **Same** — absorbed by single agent |
| **Branches** | `cursor/<slug>-e78a` or `-6f98` | `cursor/<slug>-6f98` off latest `main` |
| **Grok** | Whole-agent switch | **Subagent only** — slow + low/med |

Specs: `token-budget-rules.md` · `model-guide.md` · `s16-s17-automated-build-plan.md` (B9→B11).

## N/O (approved 2026-07-15)
- **APPROVED** + **Step 0 LOCKED**
- Models: **Composer 2.5-fast** build; **Grok slow + low/medium** subagent (escalate **high** only if medium fails).
- **A:** N/O + §17 F1–F6 ✅ **DONE**. **B:** §17 UI tail in progress.

## Read order (agents + Ditto)
1. **STATUS card** — `cursor-agents-communication/STATUS.md`
2. **This file** — `cursor-agents-communication/board.md`
3. **Token budget** — `cursor-agents-communication/token-budget-rules.md`
4. **Model guide** — `cursor-agents-communication/model-guide.md`
5. **Build queue** — `cursor-agents-communication/s16-s17-automated-build-plan.md` (B9–B11)
6. **Grok lock rule** — `cursor-agents-communication/grok-lock-composer-write-rule.md`

## Ready for next work

**§17 UI (one agent):** B8 ✅ · **B9 weekly letter (#268)** → B10 chat UI → **B11 daily recap**. **Human:** F7 DNS.

| PR | Role | State |
|----|------|-------|
| **#268** | §17.F4 weekly letter UI (B9) | 🟡 **open** |
| **#267** | §17.F3 paper portfolio UI (B8) | ✅ **merged** |

**Health:** `GET /health` · `GET /api/message-intel/status` → 200 OK

## Gate Status

| Phase | Status |
|-------|--------|
| **N/O · P · §16** | ✅ complete |
| **§17 backends (A)** | ✅ F1–F6 on main |
| **§17 UI (B)** | 🟡 B9 #268 · B10–B11 queued |

## Agent posture

| Role | Status | Notes |
|------|--------|-------|
| **Single agent** | **Active** | B9→B11; `composer-2.5-fast`; one slice per turn |
| **A (`-843d`)** | **Retired** | Do not spawn — saves Pro+ pool |
| **Grok** | **Subagent** | DESIGN / sign-off only; short LOCK |
| **Human** | **QB** | merge when green · F7 DNS · watch billing |

**Conflict surface:** `server.py` + `tests/test_endpoint_contract.py` only if routes change (unlikely for pure UI slices).

## Rules
- Board + STATUS override memory.
- Honest-empty > fake data.
- **One Cloud Agent** — no parallel A+B for rest of cycle.
- **Grok slow + low/medium** — escalate **high** only if medium fails.
- **HARD RULE — Grok lock → Composer write:** short LOCK only; Composer writes + builds.
- **On-demand billing:** tell human if usage dashboard shows **On-Demand $** charges stacking beyond included Pro+ pool.
- Obey `token-budget-rules.md` and `.cursorignore` when present.

## References
- `cursor-agents-communication/token-budget-rules.md`
- `cursor-agents-communication/grok-lock-composer-write-rule.md`
- `cursor-agents-communication/s16-s17-automated-build-plan.md`
- `cursor-agents-communication/model-guide.md`
