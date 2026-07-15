# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-15T05:32:00Z  
**main:** `7e1f0b3` — **Phase N/O + Phase P COMPLETE**

## One-line

**N/O (#227+#228) and Phase P (#232) merged. Prod flags on. Monitor backtest lift.**

## Done (do not re-queue)

| Track | PRs |
|-------|-----|
| Phase N/O (A+B) | **#227** · **#228** |
| Phase P prod + N1 hardening | **#232** |
| Board hygiene | **#229** · **#230** |
| N/O gameplan + Step 0 | **#221** · **#223** · **#225** |

## Cursor

- **Idle** — monitor `/api/backtest`, Fly health
- Grok: slow + medium default

## Phase N/O — COMPLETE
- **B** (`-e78a`): N4 → N1 → O2 → O3 ✅ **#228**
- **A** (`-843d`): N2 → N3 → O1 → O4 → O5 ✅ **#227**

## Phase P — COMPLETE
- **#232** — prod flags on (`CALIBRATION_AUTO_RETRAIN`, `CONVICTION_ALERTS_ENABLED`)
- N1 `subnet_snapshot` + judge score persistence + `hybrid_score()` stub

## Human-only (optional)
- Custom domain DNS — `DEPLOY.md` §O4
- Close stale PR **#231** / **#233** if still open (duplicates)

## Next
- Ditto defines next roadmap slice (`master-plan-merged.md` §16)
- Re-open N1 council grader only if `/api/backtest` shows insufficient Oracle lift
