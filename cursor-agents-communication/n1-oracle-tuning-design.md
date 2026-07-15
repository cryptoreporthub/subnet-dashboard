# N1 Oracle tuning — design note for Agent A (council allowlist)

**Agent B (`-e78a`) · 2026-07-15 · Step 0 spec binding**

## Shipped in B PR (no council edits)

- `internal/judges/oracle_judge.py` — stronger `signal_source` alignment, volume completeness, rebalanced weights.
- `internal/oracle/routes.py` — `/api/oracle` now includes `backtest` summary block from N4 harness.

## Proposed for Agent A (allowlist only)

These are **not** committed by B. A may land in a follow-up PR if backtest lift is insufficient.

### `internal/council/grading.py`

- Optional `hybrid_score()` stub returning `None` until magnitude is signal-derived (Phase O deferral per phase-n-design.md).

### `internal/council/resolver.py`

- When persisting new predictions, store `subnet_snapshot` on the row (`price_change_24h`, `volume`, `apy`, `emission`) so N4 replay does not rely on reconstruction.
- Ensure `judge_scores_at_creation` is always written (already via `on_prediction_created` — verify all create paths call it).

### Acceptance

- Re-run `GET /api/backtest` after A lands snapshot fields; oracle calibration bins should separate hits vs misses more cleanly.
- Target: oracle filtered win-rate (score ≥ 0.55) above council baseline without lowering confidence thresholds.
