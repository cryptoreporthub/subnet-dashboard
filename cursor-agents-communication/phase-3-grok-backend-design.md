# Phase 3 backend — Grok design (G9–G11)

**Model:** `grok-4.5-xhigh` (read-only) via Composer subagent  
**Date:** 2026-07-13  
**Scope:** G9 confidence calibration · G10 effective weights · G11 round-robin resolver

## Grok workflow

| Step | Model | Verdict |
|------|-------|---------|
| Design | Grok xhigh | PASS (all three) |
| Implementation | Composer | This PR |
| Pre-merge sign-off | Grok xhigh | Pending |

## G9 — Confidence calibration (`state_vector.py`)

- Add `_resolver_hit_rate(min_n=30)` reading `resolver.PREDICTIONS_PATH`
- Replace additive heuristic; remove bogus `price_change_24h is not None` boost
- Formula: `confidence = prior × completeness × (0.75 + 0.25 × agreement)`
- Cold-start prior = 0.5 when graded count < 30

## G10 — Expert weights (`weights.py`)

- Add `effective_weights(market_data)` → `load_weights` + `detect_regime` + `apply_regime_adjustment`
- No persist, no L1 normalize
- Wire: `server._market_context_with_weights`, `hourly_pick`, `daily_pick`, `signals.pipeline._market_context`

## G11 — Round-robin resolver (`resolver_scheduler.py`)

- `RESOLVER_BATCH_SIZE` env (default 32)
- `_round_robin_batch(subnets, cursor, batch_size)` — sort by netuid, wrap slice
- Persist `round_robin_cursor` in soul_map `prediction_resolver_scheduler`
- Pass batch (not full list) to `resolve_due_predictions`
