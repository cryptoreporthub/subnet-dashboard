# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-15T20:10:00Z — **§18 H3–B1 merged**  
**main:** `ce6d046`

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

Specs: `token-budget-rules.md` · `model-guide.md` · `s18-automated-build-plan.md`.

## N/O (approved 2026-07-15)
- **APPROVED** + **Step 0 LOCKED**
- Models: **Composer 2.5-fast** build; **Grok slow + low/medium** subagent (escalate **high** only if medium fails).
- **§17** ✅ **COMPLETE** (#267–#271, #274). **§18** H3–B1 ✅ — C1 wait creds.

## Read order (agents + Ditto)
1. **STATUS card** — `cursor-agents-communication/STATUS.md`
2. **This file** — `cursor-agents-communication/board.md`
3. **Token budget** — `cursor-agents-communication/token-budget-rules.md`
4. **Model guide** — `cursor-agents-communication/model-guide.md`
5. **Build queue** — `cursor-agents-communication/s18-automated-build-plan.md`
6. **Grok lock rule** — `cursor-agents-communication/grok-lock-composer-write-rule.md`

## Ready for next work

**§18 (one agent):** H3–B1 ✅ (#276–#277). **Human:** Fly alert secrets (A1) · F7 DNS · Telegram API creds for C1.

| PR | Role | State |
|----|------|-------|
| **#277** | §18.B1 O3 subnet report UI | ✅ **merged** |
| **#276** | §18 H3+A1+A2 docs/verify | ✅ **merged** |
| **#274** | §17.U4 home progressive enhance | ✅ **merged** |

**Health:** `GET /health` · `GET /api/message-intel/status` → 200 OK

## Gate Status

| Phase | Status |
|-------|--------|
| **N/O · P · §16** | ✅ complete |
| **§17 product** | ✅ **complete** (#267–#271, #274) |
| **§18** | 🟡 H3–B1 ✅ · **C1 wait creds** |

## Agent posture

| Role | Status | Notes |
|------|--------|-------|
| **Single agent** | **Active** | §18 H1→B1; `composer-2.5-fast` |
| **A (`-843d`)** | **Retired** | Do not spawn — saves Pro+ pool |
| **Grok** | **Subagent** | DESIGN / sign-off only; short LOCK |
| **Human** | **QB** | merge when green · F7 DNS · watch billing |

**Conflict surface:** `server.py` + `tests/test_endpoint_contract.py` only if routes change (unlikely for pure UI slices).

## Rules
- Board + STATUS override memory.
- Honest-empty > fake data.
- **One Cloud Agent** — no parallel agents.
- **Grok slow + low/medium** — escalate **high** only if medium fails. Prefer **Composer 2.5-fast** for mechanical builds.
- **HARD RULE — Grok lock → Composer write:** short LOCK only; Composer writes + builds.
- **Token budget:** `.cursorignore` + `token-budget-rules.md` — no `data/*.json` in context.
- **On-demand billing:** tell human if usage dashboard shows **On-Demand $** beyond included Pro+ pool.

## References
- `cursor-agents-communication/s18-automated-build-plan.md`
- `cursor-agents-communication/token-budget-rules.md`
- `cursor-agents-communication/grok-lock-composer-write-rule.md`
- `cursor-agents-communication/model-guide.md`
