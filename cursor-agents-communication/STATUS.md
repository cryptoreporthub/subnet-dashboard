# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-15T05:35:00Z  
**main:** `e489852` — **Phase N/O + Phase P COMPLETE**

## One-line

**N/O (#227+#228) and Phase P (#232) merged. Prod flags on. Monitor backtest lift.**

## Done (do not re-queue)

| Track | PRs |
|-------|-----|
| Phase A–B audit | #167–#185 |
| Phase C experience | #190–#192 |
| Council picks + learning | **#200–#213** |
| N/O gameplan + Step 0 | **#221** · **#223** · **#225** |
| Agent B N4/N1/O2/O3 | **#228** |
| Agent A N2/N3/O1/O4/O5 | **#227** |
| Phase P prod + N1 snapshot | **#232** |
| Board hygiene | **#229** · **#230** · **#234** |

## Cursor

- **Idle** — monitor `/api/backtest`, Fly health
- Grok: slow + medium default

## Phase N/O — COMPLETE
- **B** (`-e78a`): N4 → N1 → O2 → O3 ✅ **#228**
- **A** (`-843d`): N2 → N3 → O1 → O4 → O5 ✅ **#227**

## Phase P — COMPLETE (#232)
- Prod flags on in `fly.toml` (`CALIBRATION_AUTO_RETRAIN`, `CONVICTION_ALERTS_ENABLED`)
- `subnet_snapshot` + judge scores persisted on new predictions
- **P4** Human: custom domain DNS (`DEPLOY.md`)
- **P5** Monitor: `/api/backtest` after prod picks accumulate

## Next
- Ditto defines next roadmap slice (`master-plan-merged.md` §16)
- Re-open N1 council grader only if `/api/backtest` shows insufficient Oracle lift
