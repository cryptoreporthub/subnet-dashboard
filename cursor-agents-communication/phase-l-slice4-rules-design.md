# Phase L Slice 4 — Rules engine design (Grok-xhigh → Composer spec)

**Date:** 2026-07-12  
**Model:** grok-4.5-xhigh (design) → Composer build  
**Module:** `internal/signals/rules.py` + `internal/signals/correlation.py`  
**Does NOT depend on WS** — rules evaluate on signal write and alert refresh (event + lazy)

## Alert precedence hierarchy

```
SELL ALERT (active)  >  HOT (active)  >  score-derived buy/sell/neutral
```

| Rule | Function | Effect |
|------|----------|--------|
| R1 | `apply_hot_sell_precedence(hot, sell)` | When sell.active, hot.active → false, `suppressed_by: "SELL ALERT"` |
| R2 | `derive_signal_type(score, hot, sell)` | sell.active → `"sell"`; else hot+score≥50 or score≥60 → `"buy"`; score≤40 → `"sell"` |
| R3 | `dominant_label(hot, sell)` | UI tag: SELL ALERT > HOT > None |

## Dedup (slice 2 idempotency interaction)

| Layer | Key | Window | Behavior |
|-------|-----|--------|----------|
| **Signal log** | `subnet_id` + unchanged `(signal_type, source_expert, confidence)` | N/A | Skip append (`signals_unchanged`) |
| **Alert active** | `dedupe_key` + `alert_type` while `active=true` | N/A | Skip duplicate POST / system alert |
| **Alert time window** | `subnet_id` + `alert_type` | **5 min** | Skip repeat row (false-positive mitigation) |
| **Subnet hourly cap** | `subnet_id` | **1 hour** | Max 10 alerts/subnet/hour (env override) |

Slice 2 POST idempotency: same `dedupe_key` + `alert_type` returns existing row (HTTP 200), not a new row. New row → HTTP 201.

## Correlation — minimum viable rules (5)

Evaluated in `correlation.evaluate_composites(signals, recent_alerts)` on signal refresh:

| ID | Name | Trigger | Composite severity |
|----|------|---------|-------------------|
| C1 | `sell_crash` | sell signal + `price_change_24h` ≤ −15% | `critical` |
| C2 | `hot_surge` | HOT active + buy signal + `price_change_24h` ≥ +10% | `warning` |
| C3 | `system_stress` | active `weight_divergence` + active `accuracy_drop` alerts | `critical` |
| C4 | `signal_flip` | signal type changed buy↔sell within 5 min for same netuid | `warning` |
| C5 | `expert_consensus_buy` | ≥2 distinct `source_expert` with buy on same netuid in latest snapshot | `info` |

Composite alerts use `alert_type: "composite_<id>"` and dedupe_key `composite_<id>_<netuid>`.

## False-positive mitigation

- `ALERT_DEDUP_WINDOW_MINUTES` (default 5)
- `ALERT_MAX_PER_SUBNET_HOUR` (default 10)
- `ALERT_COOLDOWN_MINUTES` (alias of dedup window for system alerts)
- Confidence gate: composite C5 requires `confidence ≥ 0.6`

## Evaluation trigger

| When | What runs |
|------|-----------|
| **Event** | `generate_signals(persist=True)` → `append_many` → `record_signal_changes` + `evaluate_composites` |
| **Lazy** | `GET /api/alerts?refresh_checks=true` → `check_system_alerts` + composites from latest signals |
| **Not used** | Background timer (no Celery/cron in stack) |

## Composer file list

| File | Changes |
|------|---------|
| `internal/signals/rules.py` | Time-window dedup, hourly cap helpers |
| `internal/signals/correlation.py` | **new** — 5 composite rules |
| `internal/signals/alerts.py` | Wire composites + cap checks in `_append_alert` |
| `internal/signals/pipeline.py` | Call correlation after signal generation |
| `tests/test_phase_l_signals.py` | Precedence, dedup window, correlation, 201/400 |

## Slice 3 dependency

**None.** Rules engine reads `signals.json` and alert store; WS is optional fan-out only.
