# Phase §16 — Trust-gap snapshot (2026-07-15)

**URL:** https://subnet-dashboard.fly.dev  
**Code on main:** §16.1 (#244) · §16.2 (#245) · this snapshot (§16.3)  
**Baseline:** `docs/phase-p-prod-snapshot.md` (council/oracle **53.5%**)

## verify_prod.sh

| Check | Result |
|-------|--------|
| `/health` | OK |
| auto_retrain | **true** (resolved_sample **251**) |
| conviction alerts | **true** |
| Backtest sample | 200 |
| Council win-rate | **53.5%** (107/93) |
| Oracle / Echo / Pulse | **53.5%** each |
| Oracle score ≥0.55 hit-rate | **69.8%** (n=116) |

**Delta vs Phase P:** win-rate **unchanged** at 53.5% — expected; §16 closes ledger/score honesty, does not retune oracle thresholds.

## hybrid_score (§16.2)

| Item | Value |
|------|-------|
| Formula | `0.4×direction + 0.6×magnitude_calibration` |
| Magnitude scale | 10 absolute % points |
| Gate | `n ≥ 30` gradeable resolved |
| API | `GET /api/calibration/status` → `hybrid_score` |
| Below gate | `ready: false`, `reason: not_enough_data`, message **not enough data yet** |

Prod sample (**251** resolved / **200** backtest gradeable) is **above** the gate once the §16.2 deploy is live — score is real floats, not a stub.

## Outcomes (§16.1)

Backfill stamps existing pending scenarios by `scenario_id` / name+netuid; leftovers listed as `unresolvable_*` on learning scenario stats — no silent blanks, no duplicate minting.

## Gate

**`GATE_S16` = COMPLETE.** Agent B may start B1 (S4). Agent A continues to A4 (S1 bands API).

Re-run: `./scripts/verify_prod.sh`
