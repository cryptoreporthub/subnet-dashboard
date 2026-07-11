# SciWeave Answers — Phase J Implementation Spec

> **Source:** SciWeave synthesis (Jul 11 2026) + user research brief.  
> **Binding for:** Agent A Phase J only.  
> **Order:** This doc → `docs/master-plan-merged.md` §6 J1–J7 → R1–R6.

---

## 1. Summary

Peer-reviewed forecasting literature supports:

- **Expire** or **horizon-end price** resolution — never grade stale horizons against a single late snapshot (validates R1).
- **Atomic dual-ledger** resolution (validates R5 / J3).
- **Direction-first** grading; Brier/hybrid when magnitude is signal-derived (J4).
- **Symmetric** ensemble weight updates (J5).
- **Dedupe** non-independent forecasts (J2).
- **VWAP/median** or **ungradeable** for illiquid assets at `resolve_at`.
- **Trace schema** with full provenance (J6).

---

## 2. Implementation constants

| Constant | Value | Maps to |
|----------|-------|---------|
| Grace after `resolve_at` | `horizon_hours × 2` (existing) then **expire** if still unresolved | J1 |
| Late resolve rule | If `now > resolve_at + grace` → **`expired`**, not resolve at current price | J1 |
| Candle lookup window | ±15 minutes around `resolve_at` | J1, J2 replay |
| Price metadata fields | `price_source`, `price_lag_seconds`, `resolved_price` | J1 |
| Watchdog | `pending_count > 10` **OR** `oldest_pending_age > 2 × horizon_hours` | J1 |
| Dedupe window | Same `netuid` + same `predicted_pct` + `created_at` within **5 min** → keep one | J2 |
| Direction-only `correct` | `(direction=="up" and actual_pct>0) or (direction=="down" and actual_pct<0)` | J4 phase 1 |
| Weight delta (post-replay) | **+0.02 / −0.02** symmetric (or Bayesian); **pause** nudges during replay | J5 |
| Weight floor (post-replay) | **0.3** minimum (or dynamic by sample size) | J5 |
| TA minimum candles | **≥30 real** before RSI/MACD affect scoring; suppress synthetic fill | `state_vector` |
| Regime split minimum | **n ≥ 30** resolved per regime before regime-specific weights | J5 / regime |
| Illiquid | **VWAP or median** in window at `resolve_at`; **<3 candles** or zero volume → **`ungradeable`** | J1 |
| Trace fields (minimum) | `prediction_id`, `signals`, `expert`, `weights_at_creation`, `regime`, `reference_price`, `resolved_price`, `horizon_hours`, `created_at`, `resolved_at`, `actual_pct`, `outcome` | J6 |

---

## 3. SciWeave Q&A (condensed)

### Q1 — Late / batch resolution

Late resolution against stale or out-of-horizon prices **materially harms** forecast accuracy. When horizon-end data is unavailable: **expire** the forecast or resolve at **nearest historical price** with **documented lag**. Backfill from time-stamped candles requires guarding against stale-data bias.

### Q2 — Replay / label correction

When historical labels are corrupted (wrong time window), **re-label at each row’s `resolve_at`** from historical prices; **expire** rows with no valid candle. Report post-fix accuracy on a **forward-only holdout**; do not apply weight nudges during replay.

### Q3 — Dual ledger

Ensemble systems with multiple ledgers need **one atomic resolution event** writing the same `actual_pct`, `outcome`, and timestamp to predictions and portfolio ledgers. Portfolio win should align with **directional hit** and signed P&L from the **same** resolution.

### Q4 — Direction vs magnitude

When predicted magnitude is a **confidence proxy** (not model output), grade **direction-first**. Introduce **Brier score** and hybrid (e.g. 0.4 direction + 0.6 calibration) only after magnitude is signal-derived.

### Q5 — Weight decay

Asymmetric reward/penalty (e.g. +0.02 / −0.03) causes **weight collapse** to floor. Prefer **symmetric**, **Bayesian**, or **volatility-normalized** updates in non-stationary ensembles.

### Q6 — Technical indicators / synthetic data

Require **substantial real observations** before RSI/MACD are valid; **suppress or degrade** when data is sparse. Avoid scoring on synthetic/extrapolated candles.

### Q7 — Audit trail

Decision provenance should include signal inputs, expert weights, confidence proxies, regime, timestamps, and prices for post-hoc reconstruction and user-facing explainability.

### Q8 — Scheduler watchdog

Use **backlog size** and **max pending age** (not count alone) before treating accuracy metrics as valid.

### Q9 — Duplicate forecasts

**Deduplicate** near-identical predictions before computing accuracy to avoid inflated significance.

### Q10 — Cadence-specific metrics

Short-horizon (1h) may use **tighter watchdogs**; direction-only applies to all cadences in phase 1; Brier optional for 4h/24h in phase 2.

### Q11 — Regime-conditional calibration

Regime-specific weights/thresholds only when **per-regime sample size** supports it (≥30 resolved).

### Q12 — Illiquid reference price

Prefer **VWAP or median** in the resolve window; mark **`ungradeable`** when data insufficient.

---

## 4. Phase J task map (R1–R6)

| Root cause | J task |
|------------|--------|
| R1 Stale batch / wrong window | J1, J2 |
| R2 Duplicates | J2 |
| R3 Fictional `predicted_pct` | J4 (phase 1 direction-only; phase 2 signal magnitude) |
| R4 Asymmetric decay | J5 |
| R5 Ledger divergence + open positions | J3 |
| R6 Empty trace | J6 |

---

## 5. Tests (Agent A)

Required before J merge:

- `tests/test_phase_j_resolver_horizon.py`
- `tests/test_phase_j_ledger_unify.py`
- `tests/test_phase_j_dedupe.py`
- `tests/test_endpoint_contract.py` (J routes if added)

Optional: `mypy --strict` on touched modules.

**Do not** lower thresholds or use synthetic data to pass tests.

---

## 6. References

- `docs/master-plan-merged.md` §6
- `cursor-agents-communication/concurrent-protocol.md`
- SciWeave research brief (Jul 11 2026)
