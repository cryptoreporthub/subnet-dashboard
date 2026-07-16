# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-16T09:38:00Z — **§21 complete · §22 S22-1/2 merged (#298)**  
**main:** `9b814ae`

## Ditto boot (read first)

**`cursor-agents-communication/STATUS.md`** — one-page truth card.  
**Product plan:** **`cursor-agents-communication/s21-living-brain-plan.md`** — §21 Living Brain (done).

## Repo
- `cryptoreporthub/subnet-dashboard`

## Execution mode (active 2026-07-16)

**One primary Cloud Agent** + **Grok subagent** for DESIGN locks only.

| | Notes |
|--|--------|
| **Branches** | `cursor/<slug>-9ce0` off latest `main` |
| **Models** | **Composer 2.5-fast** build; Grok slow + low/med for DESIGN |
| **Grok** | Subagent only — short LOCK; Composer writes |

Specs: `token-budget-rules.md` · `model-guide.md` · `s21-living-brain-plan.md`.

## Read order (agents + Ditto)

1. **STATUS card** — `cursor-agents-communication/STATUS.md`
2. **§21 plan** — `cursor-agents-communication/s21-living-brain-plan.md`
3. **This file** — `cursor-agents-communication/board.md`
4. **Model guide** — `cursor-agents-communication/model-guide.md`
5. **Master plan** — `master-plan-merged.md` (phase history)
6. **Token budget** — `cursor-agents-communication/token-budget-rules.md`

## Gate Status

| Phase | Status |
|-------|--------|
| **§17–§20** | ✅ complete |
| **§21 Living Brain** | ✅ **complete** (#288–#296) |
| **RF-3 gate** | ✅ code fix #296 — unlocks on resolver tick |

## §21 merged (reference)

#288 market drivers · #289 S0 · #290 L1–L3/L9 · #291 L6 · #292 L10 · #293 L4/L5/L7/L13 · #294 L8/L12/L14-lite · #295 L11 · #296 RF-3 fix

## Ready for next work

| Item | Owner | State |
|------|-------|-------|
| **L14 full** | Agent | Visual share card (OG-style) |
| **Fly deploy** | Human/CI | Picks up #296; resolver tick unlocks trust UI |
| **§22** | Human | Not drafted yet |

**Skip:** F7 DNS · A1b bot · S5 Discord/X

## Agent posture

| Role | Status | Notes |
|------|--------|-------|
| **Single agent** | **Active** | Post-§21 polish / L14 full |
| **A (`-843d`)** | **Retired** | Do not spawn |
| **Grok** | **Subagent** | DESIGN only |
| **Human** | **QB** | merge when green · F7 DNS · billing |

**Conflict surface:** `server.py` + `tests/test_endpoint_contract.py` when adding routes.

## Rules

- Board + STATUS override stale memory artifacts.
- Honest-empty > fake data (RF-2).
- Trust banner / brain letter accuracy from `trust_banner` only.
- **One Cloud Agent** — no parallel agents unless human says otherwise.
- **Token budget:** no `data/*.json` in context or commits.

## References

- `cursor-agents-communication/s21-living-brain-plan.md`
- `cursor-agents-communication/s20-automated-build-plan.md` (historical)
- `master-plan-merged.md`
