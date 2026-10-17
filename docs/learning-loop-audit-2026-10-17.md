# Judges / council / learning loop: empirical audit (2026-10-17)

Method: public read-only GETs against the prod app (`/api/predictions/resolved`, `/api/learning/stats`, `/api/weights`), then code reads on main `e620ee4`. Raw pulls are not committed; reproduce from the same endpoints.

## Data cleaning (first pass was contaminated)
1,476 graded rows were pulled. 300 have |actual_pct| > 50%. All 300 are `price_source = vwap`, created 2026-08-07..17, which is the phantom-VWAP window (#1375) that `grading.py:is_phantom_vwap_quarantine` already excludes from learn/eval. They are mostly pump rows and inflated the first-pass pump hit rates (0.63) and made medians of +18,000%. **All figures below use the 1,058 clean rows** (|actual| <= 50% and outside the window).
Not verified: that every weight-update path calls `is_excluded_from_learning_eval`. I found one call site (`grading.py:223`); the official stats (`graded: 304`) look filtered, but the weight-replay paths were not traced.

## Measured (clean rows)

| Finding | Evidence |
|---|---|
| Confidence does not separate winners from losers | `council_published` hit by `pick_confidence`: 0.4-0.5 → 0.48 (n=62), 0.5-0.6 → 0.48 (n=212), 0.6-0.7 → 0.20 (n=15). corr(conf, hit) = -0.072 (n=289). |
| Published picks are always long, so hit rate = market up-rate | direction=up on 100% of 1h published picks. 1h: n=264, hit 0.48, up-rate 0.48 (the same number by construction). 24h: n=25, hit 0.36, median raw return -1.09%. |
| Selection adds nothing over the names it passed on | 1h: published names rose 48%, `council_shadow` names rose 49% (n=136). |
| No clear learning trend | 1h published hit rate: first half 0.42, second half 0.53 (n=132 each, about 1.8 SE; not conclusive). The earlier 0.51/0.51 was contaminated. |
| Pump claims rarely reach their +2% target at 1h | clean hit rates: combined_exp 0.05 (n=487), early 0.11 (n=63), just_started 0.17 (n=42). Base rate for a +2% 1h move is unknown. |
| Judge scores are near-constant | oracle mean 0.87 sd 0.08, echo 0.64 sd 0.03, pulse 0.70 sd 0.19 (all 558 council rows, uncleaned). |
| Judge weights run opposite to usefulness | corr(score, raw clipped return) on published (n=289): oracle -0.01, echo **-0.24**, pulse +0.11. Shadow (n=177): oracle +0.10, echo -0.06, pulse +0.14. Live weights: echo 0.638, pulse 0.276, oracle 0.086. Echo has the highest weight and the worst correlation; pulse is the only judge positive in both populations. Mechanism not traced. |
| Expert weights random-walk | `hype` weight by `weights_at_creation`: 0.10 (Sep 25) → 0.68 (Oct 5) → 0.10 (Oct 13) → 0.14 (Oct 17), with hit rates hype 0.48 vs technical 0.55 (uncleaned; SE 3-5 points). `quant` sits at the 2.0 cap and is the attributed expert on only 28 of 558 council rows. |
| Independence | council_published: 60 days, 34 netuids, netuid 105 has 52 rows. |

## Verified in code
- `judges/grading.py:53-58`: a judge is correct when `council_hit if endorsed else not council_hit`; it is graded against the council outcome.
- `subnet_judges.py:170`: `predicted_pct = price_change_24h`, the field the judges score.
- `daily_pick_engine.py:349`: the publish gate checks confidence and the directional guard only; `audit["approved"]` is not read there.
- Council grading is sign-only (`grading.py:direction_correct`); pump claims need `actual >= predicted_pct`, so their hit rates are not comparable.
- Shadow = `row.shadow` / `counterfactual` / `pick_source == council_shadow` (`learning/evidence.py`). I did not confirm these are rejected candidates versus another formula lane, so the published-vs-shadow comparison is suggestive, not proof.

## Not verified / limits
- No market-wide same-window baseline for a random long.
- 24h and shadow-24h samples are small (n=25, n=41).
- Mechanisms behind judge-weight divergence, the `hype` oscillation and the pinned `quant` weight were not traced.
- Items from another session's report not re-checked: stacked adjustment caps, red-team floor ordering, string-matching gates.
- The Sep 26 Ditto plan says judge weights "structurally cannot diverge". They have diverged; its conclusion (grades do not track skill) still holds, its mechanism does not.

## Implication
The loop grades the sign of the next move for names it already likes, using scores that do not predict that move, then adjusts weights on the result at a sample size where the adjustments are noise. Fix the measurement before adding models: grade return relative to the same-window median subnet, score probabilities with Brier, make weight updates sample-gated and shrunk, and keep an append-only ledger with point-in-time inputs.

---

# Verification round (follow-up)

## 1. Quarantine coverage of weight-update paths
`is_excluded_from_learning_eval` = phantom-VWAP window **or** `is_price_unit_mismatch` (price ratio ceiling), not just the window.
- **Filtered (offline / replay / eval):** `weights.py` replay (`_replay_rows_from_blob`, `_expert_hits_by_regime`), `weight_deltas`, `formula_evolution`, `calibration/pipeline`, `conviction_bands`, `judges/replay`, `portfolio/engine`, backtests, pump stats (about 18 call sites).
- **Live resolve-time nudges** (expert, signal, impact, scenario, judge): no explicit call, but both resolve paths (`resolver.py:828` and `:955`) reject unit-mismatch rows as `ungradeable` before grading. The VWAP window itself is in the past, so no live row can fall in it.
- **Not covered:** `POST /api/feedback` (`LearningEngine.record_feedback` → `nudge_expert`) applies no filter at all; see root cause 5.
- **Caveat:** replaying the 304 clean council rows from defaults does not reproduce the live weights (see root cause 2), so I cannot prove the current live values contain no phantom influence from earlier epochs.

## 2. Why the weights move (root causes)
1. **Asymmetric expert step.** `nudge_expert` / replay use +0.02 correct, -0.03 wrong (`weights.py:28-29`). Expected drift per resolve = 0.05·p − 0.03, break-even hit rate 60%. Measured expert hit rates are 0.44-0.47 (hype 0.444, technical 0.474, n=248/270), so every expert drifts toward the 0.1 floor regardless of skill. The judge module already documents and fixed this exact bug (`judges/weights.py:14-19`: "asymmetric +0.02/-0.03 required ~60% win rate just to stay flat and collapsed all three judges to the floor"); experts and signals still use the asymmetric step.
2. **Live weights are not a function of the ledger.** Replay from defaults over the clean ledger (via `replay_weights_from_predictions`) gives quant 1.06, hype 0.19, technical 0.10 (including shadow rows) or quant 1.0, hype 0.23, technical 0.74 (excluding them). Live is quant 2.0, hype 0.14, technical 1.044. Two defects behind this: (a) replay/rebalance includes `council_shadow` rows while the live nudge skips them (`_skip_council_learning`), so one row class swings technical from 0.74 to 0.10; (b) quant's 2.0 matches the legacy-misattribution artifact described in `signal_expert.py:115-123`, and the one-shot boot rebalance only runs when weights are near-flat (`maybe_rebalance_council_weights_on_boot`), so a non-flat stale value is never repaired.
3. **Judge weights reward hedging, and two judges are the same signal.** Judge nudge = ±0.02 × move_scale × conviction, conviction = |score − threshold| × 2, floored at 0.25 (`judges/grading.py`). Oracle and echo always score above threshold, so both are "correct" exactly when the council hits (both 148 correct / 156 wrong). Mean nudge scale over the 304 graded council rows: oracle 0.615, echo 0.263, pulse 0.521. With a below-50% council hit rate, the judge with the highest conviction takes the largest penalties; echo (score sd 0.03, always near its threshold) takes the smallest and ends highest. Hits are scaled by realised move (can be <1) while misses are floored at 1, a further asymmetry. Simulating the update over the ledger from defaults reproduces the direction (echo moves least) but not live values (oracle 0.086 / echo 0.638 / pulse 0.276), so earlier-epoch history is also in the live state.
4. **Target is the base rate** (always-long, sign-only grading); see Measured above.
5. **`/api/feedback` is a public, unauthenticated weight writer.** It is on the public-write allowlist (`write_auth.py:22-27`), takes a client-supplied `correct_prediction`, and calls `nudge_expert`. No frontend code calls it (only tests). The last 100 trail events show no `reason=feedback` weight changes, but that window is too short to say it was never used.

## 3. Other-session claims, re-checked in code
| Claim | Result |
|---|---|
| Red-team floor re-raises a 0.0 multiplier | **Confirmed.** `red_team.py` sets `confidence_multiplier = 0.0` for non-tradable, then `_apply_multiplier` returns `max(0.88, m*factor)`, so any later flag lifts it to 0.88. Latent: `tradable_subnets()` filters the universe before scoring in `daily_pick.py` and `hourly_pick.py`, and `approved` still turns False. |
| Audit verdict ignored by publish gate | **Confirmed.** `daily_pick_engine.py:349` checks confidence and the directional guard only. |
| Stacked adjustments have no shared cap | **Confirmed, with nuance.** Each is individually bounded: memory ±3 and ±2 pts (`memory_scoring.py:7-8`), telegram ≤5 pts (`message_intel/calibration.py:166`), pump overlay alpha ≤0.25 blend (`pump_overlay.py:18`), recovery haircut fraction, plus value/flow/size tilts (±10 / +8,-5 / ±6 pts) and a final [0,100] clamp. There is no cap on the total. |
| String matching decides outcomes | **Confirmed.** `red_team.py` derives `approved` from `c.startswith("Missing critical")` / `"Not a tradable"`; `daily_pick_engine.py:185` matches `"Missing critical field" in str(c)`. The directional guard compares `net_direction == "bearish"` but also has a numeric backstop (`predicted_pct < 0`). |
| Circular loop | **Confirmed.** `_compute_confidence` blends `_resolver_hit_rate()` into confidence (`state_vector.py:1642`); confidence gates publication; published picks are graded and nudge the weights. |
