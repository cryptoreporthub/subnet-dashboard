# Learning-stack architect verdicts (2026-10-17)

**Commit:** `803e8370` (2026-10-17). **Owner:** unconfirmed. **Last updated:** 2026-10-18. **Supersedes:** none. **Batch review:** [REVIEW-BATCH.md](REVIEW-BATCH.md).

Base: `e620ee4` (the merge-base of `803e8370` and `origin/main`). **Not on `origin/main`:** `origin/main` is now `3a65d34a`, and `803e8370` is not an ancestor of it. This commit changes docs and `scripts/prototypes/` only. No app path is in its file list (`server.py`, `internal/`, `message_intel/`, templates, static files, `tests/`). Deliverables: this file and `scripts/prototypes/`. Source reports: `docs/learning-loop/ROOT-CAUSE-REPORT-2026-10-17.md` (F1-F51, RC1-RC11, FX1-FX11) and `docs/learning-loop-audit-2026-10-17.md`.

## 0. Method and limits (read first)

- **Clean ledger**: prod `/api/predictions/resolved` pulled earlier (1,640 rows); filter outcome hit/miss, `actual_pct` present, `|actual_pct|<=50`, created outside 2026-08-07..18 -> **1,037 rows**. Council 1h pooled (published up + shadow mostly down) = **380 rows on 59 days**; published 289 (264 at 1h); pump 592 (35 reach +2%).
- **Walk-forward protocol** (`scripts/prototypes/_wf.py`, identical in every script): expanding window, >=20 training days, horizon embargo, every candidate scored against the constant training base rate, uncertainty = bootstrap over **test days** (2000). Out-of-sample = 246 rows / 39 days for council scripts. Pooled target `y = actual_pct > 0` (shadow rows are direction=down counterfactuals, so `hit` is not comparable).
- **Off-policy limit**: the ledger grades only chosen names. No alternative selection, universe or weighting policy can be evaluated from it; it only answers "does a stored score predict the outcome on rows that exist".
- **Multiplicity**: about 140 interval estimates across the 8 statistical scripts, none corrected. Only the falsifiers in section 5 are confirmatory. Everything else (including the two positive findings, STIRRING and the signed ridge) is exploratory.
- Interpreters: prototypes run on system `/usr/bin/python3` (pandas+numpy); the two that import product code (`proto_scoring_cost.py`, `make_fixtures.py`) need `/home/user/subnet-dashboard/.venv/bin/python` (the venv has no pandas). Baseline `tests/test_endpoint_contract.py`: 149 passed; `data/` restored with `git checkout -- data/`.

## 1. Headline results

1. **The day-path ~1.3 s/subnet is explained and removable** (prototype, synthetic 3,000-message table; scope: `score_subnet_for_day`, the snapshot's `day_scoring_seconds` 51.7 s for 40 names). The telegram call exists only in the day path (`state_vector.py:1897`); `score_subnet_for_hour` does not call it. `score_subnet_for_day` -> `calibration_for_subnet(conviction_rows=None)` re-runs `rollup._conviction_rows()` (5-way LEFT JOIN, LIMIT 3000, then `classify_call` x2 per row) for every subnet, **before** the `enabled` flag is read (prod: `enabled:false`). Only `daily_pick.py:118` hoists it; `score_snapshots.build_full_universe_snapshot` does not. `message_analysis.message_id` and `price_snapshots.message_id` have no index (`EXPLAIN`: `SCAN a`; 0.713 s vs 0.009 s with an index). 165-subnet cycle: **A old 805 ms/subnet = 132.9 s; B index only 120 ms; C hoisted rows 63 ms; D hoisted + health once + per-netuid index 0.2 ms/subnet = 0.04 s**, output identical on 165/165 subnets, total_score identical. Prod has 5,671 telegram messages (> LIMIT 3000) on the same volume. Prod measured 1.31-1.45 s vs my 0.8-0.94 s: same order, **not confirmed on prod**.
2. **Grading target measures drift.** Published (signal bullish) vs shadow (signal bearish) 1h up-rate spread **+0.003 [-0.120,+0.130]**; mean-return spread +0.27% [-0.54,+1.27]. 15% of 1h rows have |r|<0.05% (graded by a tick sign). Needed: 183 days at today's pick rate to detect +5pt; a universe-wide excess label would need ~3 (assumes ~10 effective names/hour; unverified).
3. **Nothing in the stored scores beats the constant out of sample except weakly signed batch models.** confidence/score/pred Platt: log-loss gain -0.0013..-0.0089, AUC 0.50-0.52; isotonic **-0.054 [-0.113,-0.003]** (overfit). Live-weight composite IC **-0.156 [-0.260,-0.057]** with 1h return (higher council technical composite -> lower next-hour return). Signed ridge: +0.0152 [+0.0001,+0.0336], AUC 0.585 (sensitivity: +0.0099 [+0.0027,+0.0187] at l2=100; published-only CIs include 0).
4. **The 0.40 confidence gate almost never binds; the directional guard does the gating, and it has no demonstrated skill.** Stored `pick_confidence` is the pre-audit value (`hourly_pick.py:156`), the gate uses post-audit `final_confidence` (audit cuts at most 12%); pre-audit confidence < 0.4545 (the only rows the 0.40 gate could block) is **7 of 445** council rows (1 published, 6 shadow). Directional guard fails open: `directional_publish_guard({})` returns `approved: True` (verified; 0 ledger rows lacked evidence).
5. **Circularity is larger than reported**: `_resolver_hit_rate()` counts every row with `correct != None` (pump, shadow, phantom-VWAP): **0.400 on n=1,476** vs 0.500 for published only -> every confidence is 7.7% lower because pump-desk outcomes feed council confidence.
6. **Judges**: oracle/echo endorse 100%, pulse 81%; judge grade == council grade on 100%/100%/84.8% of published rows. AUC for P(up): oracle 0.498 [0.449,0.548], **echo 0.412 [0.346,0.474]**, pulse 0.530 [0.461,0.604]. No judge or consensus (live weights, equal, echo=0, nudge replay) beats the constant OOS (gains -0.0036..+0.0044, all CIs include 0). Replaying the live nudge rule from defaults gives oracle .34 / echo .19 / pulse .47, not prod's .086/.638/.276 (F28 stands).
7. **Pump desk**: realised +2%/1h rate 5.1% (combined, n=487), 11.1% early, 7.1% just-started, vs **14.4%** for council-published names; desk `composite_score` OOS AUC 0.515 (label >=+2%) and 0.434 for any up-move (log-loss gain -0.0051 [-0.0089,-0.0015]); top- minus bottom-tertile hit rate -0.013 [-0.108,+0.070]. 97.1% of the 105 frozen feature vectors have `buy_ratio == 0.5` (the no-data default) and `taostats_wired` is never true. The **live, ungated** `pump_calibration._online_update_blend_weights` replayed on the 105 snapshot rows moves momentum .25->.06, price .20->.02 (floor), flow .10->.29, chatter .10->.28. `/api/learning/pump-lead/train-status` (prod): n=133, 18 hits, holdout learned 0.154 vs baseline 0.423, `adaptation_gate.passed:false` (the offline gate works).
8. **A/B ledger is the best evaluation asset and has a settlement bug**: 23.4% of settled entries have `exit_price == entry_price` exactly (100% of entries on Oct 3-5, 68% Oct 6, 0% after), graded "miss"; published scorecard hit 0.301 (daily) / 0.342 (judge) is depressed. On the 63 clean slots (11 days) the two top-5 lists overlap 0.17 (Jaccard); judge-council top-5 beat daily-model top-5 by **+1.43% per 24h [+0.17,+2.45]**; the spread does not scale with market return (slope -0.23 [-0.58,+0.31], intercept -1.69%) and held names differ little in size (current mkt-cap rank 53 vs 44). Exploratory, 11 days. Market was not uniformly down: 65% of slots had a negative union return and ex-ante `tao_change_24h` averaged +0.05%. Also corr(spread, ex-ante `tao_change_24h`) = **-0.325 [-0.679,-0.047]**: the daily model underperforms more after TAO run-ups (momentum-chasing, not beta), exploratory but CI-significant.
9. **Universe**: 27 of 165 names ever published (effective N 11.6, top-3 share 0.42). Prod's 20-name pick universe in 90 snapshots: 64 distinct sets, **union 52 of 165 names in 14 days**, consecutive overlap 0.79. Source says the snapshot-rank slice is absorbing (unscored names sort at -1, snapshot replaced wholesale); simulation confirms it, **prod churns more than the model** (leak path not isolated).
10. **Expert mass sits on never-graded experts**: with live weights (quant 2.0, hype 0.14, dark_horse 1.0, technical 1.014) and the day-lens multipliers the expert mix is quant 0.48 / dark_horse 0.247 / technical 0.244 / hype 0.029; the system's own `expert_graded_counts` is quant 0, dark_horse 0. Live vs default weights change 2-3 of the top-5 on the 165-name cross-section (fixture technicals partly stale).
11. **Learned dials drift without skill**: `impact_strength` 1.0 -> 1.72 (prod `/api/calibration/status`), 1.77 mean at creation, cap 2.0; asymmetric expert step drifts to the 0.1 floor at true hit rates below ~0.55 (simulation, 250 resolves: median weight 0.13 at hit 0.477, 0.40 at 0.55, 1.00 at 0.60). Expert weight at creation is **negatively** related to hit: hype -0.219 [-0.357,-0.070] (n=199), technical -0.227 [-0.472,+0.019]; expert-specific trailing hit adds nothing beyond market trailing hit (+0.009 [-0.117,+0.127]).
12. **Exploratory positive**: council picks made while the pump ladder phase was `STIRRING` (n=165): up-rate spread **+0.165 [+0.046,+0.281]** (published only +0.212 [+0.091,+0.330]; netuid-cluster [0.049,0.246]; logit coefficient +0.70 [+0.25,+1.14] after controlling 24h/7d momentum). **Not confirmed walk-forward** (gain +0.0108 [-0.0082,+0.0320], AUC 0.563). Hypothesis to pre-register, not a basis for the overlay.

## 2. Corrections and additions to the root-cause report

| # | Item | Status |
|---|---|---|
| C1 | F48/F51 cause: loop-invariant telegram query + missing indexes (headline 1) | measured on synthetic data; prod DB not inspected |
| C2 | F44 adds `selector_scheduler.py` (`ranked[:24]`) and the 20-name A/B universe | verified in source |
| C3 | F45 absorbing set confirmed in source/sim, but prod churns (union 52, overlap 0.79) | measured |
| C4 | F9: confidence also reads pump/shadow/phantom rows (0.400 vs 0.500) | measured |
| C5 | F8/F14 wording: 0.40 gate can bind on <=7/445 rows; guard fails open on missing evidence | measured + code |
| C6 | F21 mechanism: composite IC -0.156; weights are positive-only [0.1,2.0] and cannot express an anti-predictive signal; stochastic/bollinger/keltner equal 0.5 on 98/90/92% of rows, yet carry learned weights | measured |
| C7 | F28 stands: nudge replay does not reproduce prod judge weights | measured |
| C8 | New: A/B stale-exit artifact (headline 8) | measured |
| C9 | New: `pump_calibration._online_update_blend_weights` runs on **every** pump/shadow resolve (`resolver.py:856,984`), before the n>=30 gate; also re-reads the whole ledger via `build_pump_desk_trust()` each call | code + replay; prod calibration file not read |
| C10 | New: `impact_strength` dial is a market-up accumulator (small/mid correct -> +0.02) | measured (1.72 prod) |
| C11 | New: each weight nudge rewrites the whole soul-map: 158 ms mean (20 nudges, 863 KB copy), ~8.9 rewrites per published resolution (~1.4 s); weights are ~1 KB of that blob | measured locally |
| C12 | New: duplicate constants `resolver.py:109-112` (-0.02, floor 0.3) vs `weights.py:28-31` (-0.03, floor 0.1) | code |
| C13 | New: learned regime layer is vestigial: 0/289 published `subnet_snapshot`s carry any `detect_regime` input, so `_expert_hits_by_regime` puts every row in "chop" | ledger + code |
| C14 | New: `datastore/pump_tracker.py` (1,027 lines) has no importers outside tests; `internal/pump_tracker/core.py` supersedes it | grep |
| C15 | New: 4 of 42 `pump_just_started` rows carry an old-rule stored `correct` (live rule `act>=pred` gives 3 hits of 42, stored says 7) | ledger |
| C16 | `REFUSE_DERIVED_FOR_GRADING` is unset in `fly.toml`, so derived TMC candles remain a grading source. In the committed (Aug) candle cache one common series explains **99.95%** of hourly variance, hourly sd 0.50% vs 3.14% in live_oracle rows | file-specific; clean-ledger exposure is small (11 vwap rows) |
| C17 | Coordinator item 1: `state_vector.py:1469` (not 1475) `mom = min(0.20, abs(chg24)/20 + abs(chg7)/60)` is symmetric. **Ledger effect is nil**: only 12.4% of rows had falling 24h price, 1 row below -5%; IC(abs mom) -0.051 [-0.151,+0.053] vs IC(signed mom) +0.002 [-0.106,+0.118], both n.s. Real code flaw, unobservable in this sample because picks are already risers | verified |
| C18 | Coordinator item 3, MFE vs terminal: the ledger stores terminal price only (`actual_pct`), so MFE cannot be computed historically; capture `high_max/low_min/mfe/mae` over the horizon (section 7). Note the pump rule is itself a terminal rule (`act>=2`), not an excursion rule | verified |
| C19 | Coordinator item 7: the day-path 1.3 s/subnet is explained (C1). The **hour path** (`score_subnet_for_hour`) is separate and unmeasured: it calls `_compute_technical_indicators(sn)` / `_get_price_history(...)` with default `allow_hydration=True` (`state_vector.py:569-578, 1687-1693`), i.e. a possible network `fetch_ohlcv` per cold subnet | day path measured; hour path unmeasured |
| C20 | Retracted per coordinator: UI gate label disagreement. Not used | - |

## 3. Census (binary verdict; nuance in notes)

Status: L = live, D = dormant/never started, E = env-gated off. Evidence keys: P-conf, P-w, P-j, P-adj, P-pump, P-tgt, P-uni, P-cost, P-ab = `scripts/prototypes/proto_*` (section 9).

### Council
| Component | Learns from | Writes | Status | Verdict | Evidence |
|---|---|---|---|---|---|
| `weights.py` expert/signal nudges, replay, rebalance, regime | resolved published rows (single-credit expert, active signals) | soul-map `council_weights`, `signal_weights`, `impact_strength` | L (boot rebalance E) | REPLACE | P-w: no OOS gain (AUC .543), stored-weight composite IC -0.156, weight vs hit -0.22, 158 ms per nudge, dup constants, vestigial regime (C13) |
| `weights.py` `nudge_impact_strength` | direction hit by tier | `impact_strength` | L | REPLACE (delete learner, pin tilt) | dial 1.0->1.72; tilt itself shows IC (P-adj) |
| `resolver.py` | prices, ledger | outcome rows + 6 learning stores | L | REPLACE (learning side effects); lifecycle (due/expire/dedupe/atomic finalize) is reused as the labeler | C9, C11, `except: pass` around nudges |
| `grading.py` sign rule / pump rule / quarantine heuristics | actual_pct | `correct/outcome` | L | REPLACE | P-tgt, C15 |
| `capture.py` (REV6 band/capture) | actual, predicted | `band`, `capture_*` | E (off in prod) | REPLACE (idea folded into deadband + continuous excess) | noise-first deadband is right; still absolute-return |
| `formula_evolution/lineage/versions.py` | trail, ledger | none (versions write on fire) | L (read) / E | KEEP | derived narrative; re-point to labels |
| `ab_benchmark.py` | top-5 of two rankers, 24h settle | `council_ab_benchmark.json` | L (321 snapshots) | KEEP | best paired design; fix stale exit, add universe prices (P-ab) |
| `conviction_bands.py` | hit rates, judge calibration | none (UI) | L | REPLACE | third hit-rate number; derive from calibrated P |
| `confidence_calibration.py` + `_compute_confidence` | `_resolver_hit_rate` over all rows | confidence | L | REPLACE | P-conf, headline 5 |
| `publish_gate.py` | confidence, signal direction | HOLD/long | L | REPLACE | guard fails open; gate rarely binds; no skill (headline 2, 4). Audit-aware gate already built on the coordinator branch: adopt it, then add fail-closed on missing direction evidence |
| `pick_selection_audit.py` | replay of picks | audits dir | L but `pick_audit: null` in `/api/ops/evidence` | REPLACE | becomes a SQL query once all scored names are stored |
| `memory_scoring.py` (disposition ±3, scenario ±2) | scenario outcomes, dispositions | score | L | REPLACE | scenario spread +0.137 [-0.047,+0.293] (netuid-cluster [-0.098,+0.243]), active on 73% of rows; regime memory 124/125 "neutral" |
| `scenario_memory.py`, `learning/scenario_outcomes.py` | outcomes | `scenario_memory.json` | L | REPLACE | lossy copy of ledger (125 scenarios) |
| `signal_expert.py`, `expert_attribution.py` | signal->expert map | `expert` field | L | REPLACE | single credit; `rogue` 206 rows hit 7.3% (ops evidence) |
| `state_vector.py` indicators | candles, snapshot | features | L | KEEP | feature math stays as hypotheses; record raw |
| `state_vector.py` expert aggregation, hype/quant/dark_horse formulas | - | score | L | REPLACE | symmetric hype momentum (C17); mass on ungraded experts (headline 10); 3 of 8 signals constant |
| `score_snapshots.py` | all-name scores | `score_snapshots.json` | L | REPLACE | cost bug, closed-set slice (P-cost, P-uni) |
| `snapshot_coverage.py` | cycle outcomes | coverage block | L | KEEP | honesty telemetry; becomes per-name state |
| `pick_score_cache.py` | - | cache file | L | REPLACE (delete) | unnecessary at 0.2 ms/subnet |
| `pump_overlay.py` | pump ladder phase | score blend (alpha .10) | L | REPLACE (record, do not apply) | desk score AUC .515; STIRRING vs ACCUMULATING (n=16, up .31) treated alike |
| `red_team.py` | candidate fields | multiplier/approved | L | REPLACE | string-typed, floor re-raises 0.0 (F11). Typed concerns already built on the coordinator branch: adopt it, then add fail-closed on missing direction evidence |
| `recovery_context.py` haircut | candles | score x(1-h) | L | REPLACE (record, do not apply) | no per-row field; unobservable |
| `price_reference.py` | candles/oracle | exit price | L | KEEP until typed prices | C16; becomes the labeler's price source |
| `daily_pick_engine.py`, `daily_pick.py`, `hourly_pick.py`, `pick_scheduler.py`, `selector*.py`, `rotation_*` | scores | daily_picks, pick_history | L | KEEP (skeleton) | read obs table instead of slicing |
| `alignment_nudge.py` | selector agreement | none (diagnostic only) | L | REPLACE (delete) | `applied:false`; still loads weights each tick; `ranked[:24]` cap |
| `replay.py` (council) | ledger | judge portfolios | dev | KEEP | offline harness |
| `mindmap_bridge.py` | - | soul-map trail | L | KEEP | infra |

### Judges
| Component | Learns from | Writes | Status | Verdict | Evidence |
|---|---|---|---|---|---|
| `oracle/echo/pulse_judge.py`, `judges.py`, `subnet_judges.py` | signal impact, snapshot | judge scores | L | REPLACE | P-j; echo AUC .41; `predicted_pct = price_change_24h` (F6); judge ranker paired result keeps scoring code alive (P-ab) |
| `judges/grading.py`, `weights.py`, `tracker.py` nudges | council outcome | `judge_weights` | L | REPLACE | grade == council grade; conviction scaling; replay != prod |
| `portfolios.py` | resolved picks | `data/portfolios` | L | REPLACE | duplicates A/B; derive from labels |
| `postmortems.py` | wrong picks | `data/postmortems` | L | REPLACE (delete writer) | display-only consumers; no decision consumer |
| `judges/replay.py` | ledger | none | dev | REPLACE (delete after FX4) | dev tool |
| `analytics/backtest.py` | ledger | report | L | KEEP | read-only |

### Learning
| Component | Learns from | Writes | Status | Verdict | Evidence |
|---|---|---|---|---|---|
| `prediction_loop.py` | picks | prediction rows (~60 copied fields), shadow rows | L | REPLACE | rows should reference `(cycle_id, netuid)` |
| `predictions_store.py` | - | 5.3 MB whole-file JSON, file lock | L | REPLACE | whole-file rewrite per row; thin decision log + labels |
| `weight_deltas.py`, `weight_audit.py` | trail | none | L | REPLACE | rogue stats vanish with FX3 |
| `outcome_snapshot*.py`, `loop_health.py`, `trust_stats.py`, `streaks.py`, `council_health_score.py`, `panel_summaries.py`, `story_path.py`, `dashboard_context.py`, `mindmap_aggregator.py`, `trail_*` | ledger | artifacts | L | KEEP | reporting; headline accuracy is sign-only, re-base on labels |
| `pump_lead_train.py` | frozen vectors | evaluation file | L offline | KEEP | chronological split + Wilson gate correctly reports `regression`; template for all promotions |
| `pump_calibration.py` | pump outcomes | `pump_calibration.json` | L | REPLACE | C9, P-pump replay |
| `pump_alert.py`, `pump/engine.py`, `pump/combined.py`, `pump_lead_ledger.py` claim logic | price/volume/phase | claims | L | REPLACE | P-pump; flow inputs absent |
| `pump_lead_features.py` frozen claim-time vectors | - | feature rows | L | KEEP | the right pattern (point-in-time, append-only) |
| `pump_lead_stats.py`, `pump_lead_recover.py`, `pump/combined_ledger.py` | outcomes | stats | L | KEEP | re-base label; recover is a price-outage band-aid |
| `ledger_heal.py`, `expired_recovery.py`, `expert_backfill.py` | ledger | rows | L | REPLACE | data-repair band-aids for missing inputs (FX9) |
| `evidence.py` populations | - | `evidence_population` | L | KEEP | typed lineage; `accuracy_lift/populations.py` duplicates it (unify) |
| `dpick_*.py` | picks | display copy | L | KEEP | presentation, not learners |

### Calibration, accuracy, message intel, other
| Component | Learns from | Writes | Status | Verdict | Evidence |
|---|---|---|---|---|---|
| `calibration/pipeline.py` (+scheduler, routes) | attributed expert accuracy | `council_weights` (fire) | E (`auto_retrain_enabled:false`, `last_retrain_at:null`) | REPLACE (inner); KEEP retrain->cert->fire state machine | estimator is Laplace-smoothed accuracy, ratio-compressed (right shape) but `certify_weights` holdout is the last 50 of the **same** rows used to propose (leakage) and credit is single-expert |
| `accuracy_lift/*` | ledger | snapshot | L | KEEP | headline `mixed_all_resolved` 0.286 vs published 0.515 (ops evidence) shows why populations matter |
| `message_intel/self_learning.py` | outcomes | author reliability, patterns | D | REPLACE (delete) | never started; parallel to `rollup` reliability |
| `internal/message_intel/calibration.py` | Telegram receipts | score ±<=5 pts | E (prod `enabled:false`, 14 fresh samples, hit 0.214) | REPLACE | cost bug runs while disabled |
| `message_intel/rollup.py`, `proof.py`, `conviction_index`, `signals_bridge` | receipts | UI rollups | L | KEEP | descriptive; Beta(2,2) smoothing is fine |
| `datastore/learning_engine.py` | client feedback | weights/scenarios | L (FX6 deletes) | REPLACE | headline FX6 |
| `analytics/market_drivers.py` `_effective_yield_trap_thresholds` | medians of feature values of resolved rows | thresholds | L | REPLACE (constants) | no outcome signal enters |
| `datastore/pump_tracker.py` | - | - | dead | REPLACE (delete) | C14 |
| `pump_tracker/core.py` | price/volume | cycles | L | KEEP | detector, not an outcome learner |
| `portfolio/engine.py`, `signals/alerts.py`, `conviction_alerts`, `conviction_decay.py`, `letter/*`, `bots/*`, `ops/*`, `simivision/graded_context.py` | ledger stats | display/alerts | L | KEEP | consumers; re-base on labels |
| `fly.toml` env: `CALIBRATION_AUTO_RETRAIN=off`, `DAILY_PICK_PUBLISH_GATE=0.40`, `SCORE_SNAPSHOT_MAX_SUBNETS=40` | - | - | - | - | recorded |

## 4. REPLACE -> prototype -> walk-forward result

| REPLACE | Script | Result |
|---|---|---|
| Grading target | `proto_target_audit.py`, `proto_ab_paired.py` | baseline-free test spread +0.003 [-0.120,+0.130]; ledger cannot supply excess return (no universe prices; only 1/29 pick_history rows keep one). Needs capture |
| Weight estimator | `proto_weights_wf.py` | OOS: live_stored +0.0047 [-0.0012,+0.0112]; online asym +0.0011; sym +0.0016; equal +0.0027; shrunk IC +0.0060 [-0.0013,+0.0138]; **signed ridge +0.0152 [+0.0001,+0.0336]** |
| Judges | `proto_judges_wf.py` | no model beats constant (section 1.6) |
| Confidence / probability | `proto_confidence_wf.py` | nothing beats constant; isotonic significantly worse |
| Adjusters | `proto_adjusters.py` | value tilt inert (apy null on 95.5% of rows); size_tilt IC +0.230 [+0.100,+0.368] raw, +0.103 [+0.006,+0.198] day-demeaned; walk-forward gain +0.0035 [-0.0037,+0.0112]; flow_boost +0.0068 [-0.0073,+0.0232]; score ex-tilts -0.0006; paired ablation +0.118 [-0.013,+0.262]; memory rule involves no fit so its correlation +0.062 [-0.101,+0.210] is already out of sample |
| Universe selection / cost | `proto_scoring_cost.py`, `proto_universe_selection.py` | 805 -> 0.2 ms/subnet (3,669x); absorbing set 40/165 in model, 52/165 in prod over 14 days |
| Pump desk | `proto_pump_wf.py` | desk score has no OOS discrimination; model not estimable (35 positives) |
| Deletion/structural (no walk-forward possible): `datastore/learning_engine`, `self_learning`, `datastore/pump_tracker`, `postmortems` writer, `market_drivers` thresholds, `alignment_nudge`, `ledger_heal`, `expired_recovery`, `scenario_memory`, `pick_score_cache`, `portfolios`, `red_team` strings, `recovery_context`, `predictions_store`, `pick_selection_audit` | - | no decision consumer or no per-row field; justified by code reading (section 3) and by the capture spec in section 7 |

## 5. Best architecture per area (alternatives, falsifier)

**A. Grading target.** Best: forward return of a **single-unit price (alpha-per-TAO, typed)** at horizons 1h/4h/24h, labelled both as terminal return and as **excess vs the same-cycle median of liquidity-floored scored names**, with intra-horizon `mfe/mae` captured, a measurement-noise deadband (rows inside it are ungraded, not misses), and no sign-only hit as a headline. Alternatives rejected: (1) status quo absolute sign: measures drift (spread +0.003), 15% decided by a sub-0.05% tick, 183 days to resolve a 5pt edge; (2) REV6 capture/deadband on absolute return: fixes noise, not drift; (3) benchmark vs holding TAO only: alpha-per-TAO already is that, it does not remove the alpha-market factor. MFE vs terminal: capture both, grade terminal as primary (MFE is optimistic and unrealisable without a stop model). Falsifier: after >=100 labelled days the day-clustered excess-IC CI of every score contains 0 (no edge: stop gating publication), or split-half reliability of the excess label < 0.3 (target unusable).

**B. Weight estimator (experts + signals).** Best: a pure function of the label table: signed, shrunk (ridge/empirical-Bayes) coefficients on **raw features including expert scores**, estimated on universe-wide excess labels, `n_eff` gate and walk-forward certification; below the gate the weight **is the prior**, stated as such in the UI. This is the root-cause report's FX2 estimator, not a freeze: today every learner is in the gated branch. Alternatives: (1) online asymmetric nudge: AUC .543, floor-drift below hit ~.55, negative weight/hit relation; (2) symmetric nudge (judges' fix): no better (+0.0016); (3) calibration pipeline's smoothed accuracy: right shape, but single credit and leaked certification; (4) equal weights: the correct fallback. Falsifier: fitted-vs-equal OOS gain CI contains 0 on universe labels over >=N days -> delete the learner. The signed ridge's CI lower bound (0.0001) is a multiplicity-sized hint, not evidence.

**C. Judges.** Best: remove endorsement thresholds, conviction-scaled nudges and council-relative grading; each judge becomes an independent forecaster of P(excess>0) from its own input slice, scored by Brier skill vs the base rate, weight 0 until BSS CI lower bound > 0; apply the approved **Echo = 0** now (AUC 0.41, 64% of consensus today). Alternatives: (1) keep and fix step sizes: grade identical to council on 100%; (2) merge into experts: oracle/pulse corr 0.72 suggests shared inputs; (3) Jev/LLM as shadow judge (FX4): same grading. Counter-evidence kept: judge-council top-5 beat daily-model top-5 by +1.43%/24h (P-ab, exploratory), so keep scoring code running in A/B. Falsifier: a judge with BSS CI lower bound > 0 over >=100 labelled days.

**D. Confidence / probability.** Best: publish only a **calibrated P(excess>0)** from a walk-forward-certified model; while none beats the constant, show the base rate and "no demonstrated edge" and let the publish policy be explicit (typed, fail-closed). Heuristic confidence stays as a labelled "data completeness x agreement" publishability score, never a hit chance, and never reads outcomes. Alternatives: (1) Platt on score/confidence: no gain; (2) isotonic: -0.054 [-0.113,-0.003]; (3) status quo. Falsifier: OOS reliability slope <= 0 or top-bin hit below base (conf >= 0.60: up-rate 0.176, n=17; published >= 0.60: 0.154 [0,0.286], n=13 — post-hoc).

**E. Score adjusters.** Best: each adjuster is a **recorded delta** (your `score_breakdown` branch already persists base/memory/telegram/pump/recovery/final) and is applied only after ablation lift on universe labels with CI lower bound > 0 and a recorded total budget. Base = the coordinator branch's `score_breakdown` (base/memory/telegram/pump/recovery/final); new fields needed are only `value_boost`/`flow_boost`/`size_tilt`/disposition and the expert scores. Initial state: apply none except the liquidity/size feature, which is the only term with a consistent sign (size_tilt IC +0.23 raw, +0.10 demeaned) and is fixed, not learned. Delete the `impact_strength` learner. Alternatives: keep all (unmeasured, dial at 1.72); delete all (loses the one candidate); ledger ablation (impossible: MDE ~0.1 IC at 380 rows). Falsifier: ablation lift CI contains 0 -> delete.

**F. Universe selection.** Best: score **every tradable name every cycle** (0.2 ms/subnet after the hoist: 165 names in 0.04 s plus a one-time 63 ms), explicit per-name state (`scored/stale/failed/unscored`), a typed liquidity floor instead of a count, pick = argmax over fresh rows. Alternatives: (1) raise caps: forbidden by the handoff and pointless; (2) FX11's incremental score store: unnecessary, cost was a loop invariant; (3) rotating sample: reaches 165 names but 4x slower label accumulation; (4) status quo snapshot slice (sticky). Falsifier: prod full-universe cycle exceeds budget/RSS after the hoist (then reconsider), or full-universe picks show no better excess IC than capped picks (cap irrelevant).

**G. Pump desk claim logic.** Best: replace the point claim "+2% in 1h" with a **base-rate-shrunk probability P(>=+2% within 1h)** conditioned on the name's own realised volatility, graded by Brier and decile lift; delete the ungated online blend update; wire flow data or drop "flow before price"; keep frozen claim-time vectors and the chronological promotion gate. Alternatives: (1) tune gates adaptively (the current ratchet): no signal to adapt on; (2) XGBoost: 35 positives, <=3 parameters supportable; (3) delete the desk and feed the phase to the council as a feature (STIRRING hypothesis). Falsifier: top-tertile minus bottom-tertile lift CI contains 0 after >=100 positives -> delete desk claims.

## 6. Target architecture

**Data plane (SQLite via `internal/store/db.py`, WAL, one connection helper).**
- `cycle(id, started_at, finished_at, membership_hash, n_expected, n_scored, status)`
- `obs(cycle_id, netuid, ts, price_value, price_unit='tao_per_alpha', price_source, state, fail_reason, liquidity_tao_24h, features_json[8 signal scores, 4 expert scores, mentions, apy, chg24/7, relative_flow, sensitivity, phase, pump composite], score_breakdown_json[base, value, flow, size, memory, telegram, pump, recovery, final], confidence_inputs_json, judge_json, input_hash)` PK (cycle_id, netuid)
- `label(cycle_id, netuid, horizon_h, exit_ts, exit_price_value/unit/source, ret_pct, excess_pct, mfe_pct, mae_pct, usable, unusable_reason)`; `usable=0` when exit==entry, lag > tolerance, or unit mismatch
- `weight_state(model_version, kind, key, weight, n_eff, prior, ledger_hash, computed_at)` derived only.
- **Pick-level decisions stay JSON** (`predictions.json` becomes a thin log `{id, cycle_id, netuid, kind, horizon, direction, gate_json, p, model_version}` with **no stored grade**; grade = join to `label`). This is a concrete proposal for the open Ditto question: universe-level observations in SQLite (as decided 2026-10-12), pick-level stays table-free. Owner decision.

**Who may write:** `cycle_scorer` (worker) -> `cycle`,`obs`; `labeler` (the reused resolver lifecycle) -> `label`; `pick_publisher` -> decision log; `weight_fitter` (scheduled, walk-forward certified) -> `weight_state`; nobody else (extend the fx6 allowlist test with the new tables). Routes read-only except token-protected admin.

**Promotion rule**: model_version promoted only if train <= t0 / test > t0 (embargo = horizon) beats constant/prior on Brier or log-loss with day-cluster CI lower bound > 0 over a minimum test-day count; `pump_lead_train` is the template.

### Units (each independently verifiable; build on your fx6 / score_breakdown / typed-red-team / timings branches)
| Unit | Change | Blast radius (readers/writers) | Verification | Rollback |
|---|---|---|---|---|
| U0 | Hoist telegram invariants: skip `calibration_for_subnet` when disabled, compute health once per cycle, pass `telegram_conviction_rows` in snapshot context, add 2 indexes in `message_intel/models.py` | writers: `score_snapshots`, `state_vector`, `calibration.py`, `models.py` schema; readers: telegram calibration endpoints | `proto_scoring_cost.py` D-equivalence 165/165; 165-subnet cycle < 1 s with 5k rows; per-stage timings on prod; contract test | revert commit; indexes idempotent |
| U1 | A/B: reject `exit==entry`/stale exit, settle at horizon price, store `universe_prices` | `ab_benchmark.py`, `/api/council-ab`, `council_ab.html` | new unit test + rerun `proto_ab_paired.py` | revert |
| U2 | Stop learner drift: `_resolver_hit_rate` council_published only; delete `pump_calibration` online update; remove dead dup constants; apply Echo=0 | `state_vector`, `pump_calibration`, `resolver`, `judges/weights` | `proto_confidence_wf` hit-rate section; writer-allowlist test | revert |
| U3 | Shadow-write `cycle`/`obs` for all 165 names every cycle (no behaviour change) | worker only; new tables | every active netuid has a row with state; coverage cannot read full when any failed | disable flag |
| U4 | `labeler` writes `label` (1h/4h/24h, excess, mfe/mae); clock for FX1 starts | resolver lifecycle, price_reference | label reproducible from stored inputs; synthetic always-long on flat-relative universe scores 0.5 | stop job |
| U5 | Delete count caps (FX11 revised) after U0 cost proof; explicit liquidity floor | `server.py`, `pick_scheduler`, `daily_pick_engine`, `scoring_cap`, `score_snapshots`, `selector_scheduler`, `pick_selection_audit`, `fly*.toml` | deletion test: no subnet-count default; prod RSS/cycle time measured under web+worker load | restore env/caps |
| U6 | `weight_fitter` + walk-forward harness (promote prototypes to tests); shadow beside live weights | `weights.py` readers (`daily_pick`, `hourly_pick`, `expert_display`, `server`, `signals/pipeline`) | fitted == replay exactly; below gate returns prior | keep live weights |
| U7 | Adopt the coordinator branch's typed concerns + audit-aware gate, then add fail-closed on missing direction evidence and the calibrated P (display base rate until a model beats the constant) | `publish_gate`, `hourly_pick`, `daily_pick_engine`, UI pill | reliability OOS; missing-direction candidate not published | revert |
| U8 | Judges as shadow forecasters; delete nudge/portfolio/postmortem writers | `judges/*`, `tracker`, `council_routes` | BSS reported; no writer left | revert |
| U9 | Pump: probability claims, flow wiring or drop, adopt phase as council feature | `pump/*`, `pump_alert`, `pump_lead_*` | Brier vs base; positives counter | revert |
| U10 | Deletions: `self_learning`, `datastore/pump_tracker`, `datastore/learning_engine`, `alignment_nudge`, `market_drivers` thresholds, `scenario_memory`, `ledger_heal`, `pick_score_cache` | listed modules | grep shows no importers; contract test | git revert |

**Revisions to FX1-FX11.** FX1 keep (single alpha-per-TAO unit, universe from `obs`, add mfe/mae and a deadband). FX2 keep with the explicit `n_eff` gate returning the prior (this is not a freeze: it is the estimator's gated branch). FX3 blocked until `expert_contributions` is persisted per row (it is absent from the ledger; your `score_breakdown` covers adjusters only). FX4 narrowed: Echo=0 now, judges as shadow forecasters, keep judge scoring in A/B. FX5 keep. FX6 keep. FX7 keep plus fail-closed on missing direction evidence (also hourly path). FX8 keep and note `REFUSE_DERIVED_FOR_GRADING` is off. FX9 revised: SQLite only for universe observations/labels. FX10 unchanged. FX11 **revised**: cause is a loop-invariant query plus missing indexes; no incremental score store needed; first land U0. New FX12: A/B ledger as evaluation spine. New FX13: remove ungated pump online learner and the impact dial.

## 7. Capture spec (fields the ledger lacks)

Per scored name per cycle (`obs`): typed price (value, unit, source); `liquidity_tao_24h`; all four **expert scores** and 8 signal scores; adjuster deltas = the existing `score_breakdown` **plus only** `value_boost`, `flow_boost`, `size_tilt`, disposition; confidence inputs (completeness, agreement, hit-rate used); judge scores and endorsement; pump phase + composite + raw flow inputs (`buy_ratio`, buys/sells, `taostats_wired`); regime inputs actually used; `input_hash`; per-name state. Per label: exit price (typed), lag, `mfe/mae` over the horizon, `excess` vs same-cycle median, `usable` flag. Per decision: `cycle_id`, gate result fields (pre- and post-audit confidence, guard verdict and its evidence), model_version. For A/B: universe prices at entry and exit.

## 8. Could not verify

- Hour-path (1h) scoring cost on prod: not measured; hydration-on-cache-miss is a candidate (source only).
- Prod root cause of the day-path 1.3 s: shown on a synthetic 3,000-row table (0.8-0.94 s); prod DB size, schema indexes and CPU speed not inspected (no shell/volume access).
- Prod `pump_calibration.json`, `soul_map.json` file size and real calibration state; the replay uses the 105 clean snapshot rows only.
- Why the pick universe churns (union 52) when the source implies a closed set; the stale-snapshot path was not traced.
- A/B covers 90 of 321 snapshots (route cap); earlier settlement quality unknown. Paired result is 11 days / 63 slots (65% of slots negative; spread vs ex-ante TAO change -0.325 [-0.679,-0.047]).
- Candle-cache findings are from the committed Aug file; fixtures (`scores_2026-10-17.json`) use that stale cache for technicals; only structural conclusions rely on them.
- Per-adjuster ablation, per-expert grading, MFE grading, and excess-return skill: not computable (fields missing); power statement for the universe label assumes ~10 effective names/hour.
- Ditto/Jev/Decision Models facts not re-read; the Sep 8 "Learning Safety Batch" body not read.
- Whether `/api/feedback` was ever abused; the 4 stored/live pump rule mismatches' prod impact.
- Production code at `e1cfaf8e` vs `e620ee4`: relied on coordinator statement that learning/council/judges are identical.

## 9. Reproduce

`/usr/bin/python3 scripts/prototypes/proto_{confidence_wf,weights_wf,judges_wf,adjusters,pump_wf,target_audit,universe_selection,ab_paired}.py` (weights/adjusters/pump take 1-3 min). `TMPDIR=<scratch> /home/user/subnet-dashboard/.venv/bin/python scripts/prototypes/proto_scoring_cost.py` (~2.5 min; `--arms B,C,D` skips the slow arm). Shared: `_ledger.py` (set `LEDGER=` to a copy of `/api/predictions/resolved`), `_wf.py`, `_universe.py`. Fixtures (read-only prod GETs, 2026-10-17): `fixtures/subnets_*.json`, `scores_*.json`, `council_ab_*.json`; `make_fixtures.py` regenerates scores.
