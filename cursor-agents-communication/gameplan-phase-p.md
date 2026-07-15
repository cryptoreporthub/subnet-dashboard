# Phase P — Production activation & N1 follow-through

**Status:** COMPLETE 2026-07-15 · code **#232** merged · **#233 closed unmerged** (duplicate) · verify **#237**  
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

**P5 verified 2026-07-15** on `subnet-dashboard.fly.dev`:

| Metric | Value | vs baseline (~45.5%) |
|--------|-------|----------------------|
| Council win-rate | **53.5%** | ✅ lift |
| Oracle win-rate | **53.5%** | ✅ lift |
| Oracle score ≥0.55 hit-rate | **69.8%** (n=116) | ✅ strong separation |

**Verdict:** No N1 council grader reopen needed. Run `./scripts/verify_prod.sh` after each deploy.

**P4:** DNS + `flyctl certs add dashboard.cryptoreporthub.com` — blocked on registrar + Fly auth (see `DEPLOY.md`).

Agents idle / monitor until Ditto defines next roadmap slice.
