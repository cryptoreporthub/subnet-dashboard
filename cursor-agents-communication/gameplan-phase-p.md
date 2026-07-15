# Phase P — Production activation & N1 follow-through

**Status:** COMPLETE 2026-07-15 · **#232 merged** @ `7e1f0b3`  
**Precedes:** Ditto-defined roadmap slice (master plan §16)  
**Binding prior:** `phase-n-o-step0-spec.md` · `n1-oracle-tuning-design.md`

## Why Phase P

N/O shipped code on `main` (#227 + #228) but prod flags were off and N1 council allowlist items from B's design note were not landed. Phase P closes that gap before new roadmap work.

## Slices

| Slice | Owner | Scope | AC |
|-------|-------|-------|-----|
| **P1** | A | Enable `CALIBRATION_AUTO_RETRAIN` + `CONVICTION_ALERTS_ENABLED` in `fly.toml` | Next Fly deploy picks up flags |
| **P2** | A | `subnet_snapshot` on new predictions; persist `judge_scores_at_creation` + `weights_at_creation` (append order fix) | `test_prediction_loop_closure` asserts snapshot + scores in store |
| **P3** | A | `grading.hybrid_score()` stub (returns None until magnitude calibration) | Import-safe; no behavior change |
| **P4** | Human | Custom domain DNS per `DEPLOY.md` | Optional |
| **P5** | Monitor | `GET /api/backtest` after prod picks accumulate | Oracle filtered win-rate vs baseline |

## Agent assignment

| Agent | Builds |
|-------|--------|
| **A** (`-843d`) | P1–P3 |
| **B** | Idle unless backtest UI needs polish after P5 numbers |
| **Human** | P4 DNS only |

## Non-negotiables

- No threshold gaming
- No `data/*.json` churn in commits
- Honest-empty preserved

## After Phase P

Agents idle / monitor. Re-open N1 council grader work only if P5 shows insufficient lift.
