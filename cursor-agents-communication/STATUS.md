# STATUS — subnet-dashboard (Ditto boot card)

**Updated:** 2026-07-15T05:31:00Z  
**main:** Phase N/O + **P** complete (#227 #228 #232)

## One-line

**Phase P merged (#232). Prod flags on; monitor Fly deploy + `/api/backtest`.**

## Done (do not re-queue)

| Track | PRs |
|-------|-----|
| Phase A–B audit | #167–#185 |
| Phase C experience | #190–#192 |
| G7+G12 / council-first | #195 · #198 |
| Council picks + learning | **#200–#213** |
| Lazy OHLCV + badge polish | **#212** |
| Canvas radar (Chart.js removed) | **#215** |
| Social sentiment (message_intel) | **#217** |
| Fly keep-warm / 1GB + health gate | **#218** |
| N/O gameplan | **#221** |
| Step 0 lock | **#223** |
| Grok slow+medium policy | **#225** |
| Agent B N4/N1/O2/O3 | **#228** |
| Agent A N2/N3/O1/O4/O5 | **#227** |
| Phase P prod + N1 snapshot | **#232** |
| A2 `smoke` on `main` | verified |
| Stale open PRs closed | #101 · #110 · #112 · #129–#130 · #134 · #139 · #153 · #165–#166 · #184 |

## Ditto

- **Do:** read `board.md`, watch CI/Fly health
- **Do not:** re-open completed July 14 queue items; do not rebuild `signal_hub`

## Cursor

- **Idle** — Phase N/O complete; no queued N/O slices
- Git only; Ponytail minimal diff
- Grok: slow + medium default; high only if medium fails / unsatisfactory

## Phase N/O — COMPLETE
- **Step 0 LOCKED** — `phase-n-o-step0-spec.md`
- **B** (`-e78a`): N4 → N1 → O2 → O3 ✅ **#228**
- **A** (`-843d`): N2 → N3 → O1 → O4 → O5 ✅ **#227**
- **Prod flags:** `CALIBRATION_AUTO_RETRAIN=on`, `CONVICTION_ALERTS_ENABLED=on` in `fly.toml` (Phase P #TBD)
- **Human-only:** O4 custom domain DNS at registrar (steps in `DEPLOY.md`)

## Phase P — COMPLETE (#232)
- Prod flags on in `fly.toml`
- `subnet_snapshot` + judge scores persisted on new predictions
- **P4** Human: custom domain DNS (`DEPLOY.md`)
- **P5** Monitor: `/api/backtest` after prod picks accumulate
