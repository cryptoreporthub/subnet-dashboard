# Gameplan — Phase P (Launch Activation & Signal Hardening)

**Status:** IN PROGRESS 2026-07-15 · Follows Phase N/O complete (#227 + #228)  
**Owner:** Agent B (`-e78a`) with user merge authority  
**Models:** Composer 2.5 build · Grok slow + medium only if design review needed

## Why Phase P

Phase N/O shipped code with **opt-in** prod flags and deferred N1 council grader items (`n1-oracle-tuning-design.md`). Phase P activates launch features and closes the N1 persistence gap so backtests use real subnet snapshots.

## Slices

| Slice | What | AC |
|-------|------|-----|
| **P1** | Prod activation | `fly.toml` sets `CALIBRATION_AUTO_RETRAIN=on`, `CONVICTION_ALERTS_ENABLED=on`; deploy |
| **P2** | N1 council hardening | `subnet_snapshot` on new predictions; `judge_scores_at_creation` persisted; `hybrid_score()` stub in `grading.py` |
| **P3** | Docs | `DEPLOY.md`, `board.md`, `STATUS.md` reflect Phase P complete |

## Out of scope

- Custom domain DNS (human registrar — steps in `DEPLOY.md`)
- Rebuilding `signal_hub` or Cockpit section IDs

## Verify

```bash
pytest tests/test_n1_subnet_snapshot.py tests/test_backtest.py tests/test_calibration_scheduler.py \
       tests/test_conviction_alerts.py tests/test_endpoint_contract.py -q
```

Prod after deploy:

- `GET /api/conviction-alerts/status` → `enabled: true`
- New predictions include `subnet_snapshot` + `judge_scores_at_creation` in `predictions.json`
