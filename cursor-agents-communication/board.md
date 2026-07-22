# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-22T22:25:00Z  
**main:** `9c75415` (#419 Slice R+M merged)

## Next slice queue

1. ~~Slice A–B~~ — attribution + pump desk (#414–#418)
2. ~~Slice R~~ — historical weight rebalance + soft reset (`POST /api/learning/rebalance-weights`)
3. ~~Slice M~~ — α pump overlay at score time (`PUMP_SCORE_OVERLAY_ALPHA`, default 0.10)
4. **Phone QA** — council votes + Yanez names + post-rebalance weights
5. Optional — publish gate 45% → 40% experiment
6. Wave 4 — YAGNI

## Slice R + M (this PR)

| Slice | What | soul_map writes? |
|-------|------|------------------|
| **R** | Replay council ledger with `expert_for_replay_row`, 70/30 soft blend vs defaults | Yes, via rebalance endpoint or `COUNCIL_WEIGHT_REBALANCE_ON_BOOT=on` |
| **M** | `apply_pump_score_overlay` in hour/day scoring | **No** — score-time only |

Pump desk learning stays in `pump_calibration.json`; resolver still skips `pump_lead` for council nudges.

## Gameplan

**Canonical:** `cursor-agents-communication/gameplan-pump-site-undeniable.md`  
**Fix plan:** `cursor-agents-communication/quant-pump-desk-fix-plan.md`

## Human follow-up

- After deploy: `POST /api/learning/rebalance-weights?dry_run=true` then `dry_run=false`
- Phone QA 390px
- Env: `CONVICTION_ALERTS_ENABLED` / Telegram
