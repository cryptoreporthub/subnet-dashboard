# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-15T13:45:00Z  
**main:** `efe8027` (+ §16.3 pending this PR)

## One-line

**`GATE_S16` COMPLETE — §16.1/#244 · §16.2/#245 · snapshot docs. Agent B may start B1. A continues A4 (S1 bands).**

## PR truth (avoid board drift)

| PR | What | State |
|----|------|-------|
| **#243** | Auto plan + start prompts | ✅ **merged** |
| **#244** | §16.1 outcome backfill | ✅ **merged** |
| **#245** | §16.2 gated hybrid_score | ✅ **merged** |
| **#232** | Phase P implementation | ✅ **merged** |
| **#233** | Duplicate of #232 | ❌ **closed unmerged** |

## Done (do not re-queue)

| Track | PRs |
|-------|-----|
| N/O | **#227** · **#228** |
| Phase P | **#232** · **#237** |
| §16 | **#244** · **#245** · (§16.3 snapshot) |

## Phase §16 — COMPLETE

- Outcomes: no duplicate mint; unresolvable reported
- `hybrid_score`: gated n≥30; honest “not enough data yet”
- Prod backtest still **53.5%** (vs P baseline) — see `docs/phase-16-trust-gap-snapshot.md`

## Next

- **Agent B:** `GATE_S16` clear → Build **B1** (S4)
- **Agent A:** A4 S1 conviction bands API → A5 S2 magnitude …
- Monitor `./scripts/verify_prod.sh` after deploys
