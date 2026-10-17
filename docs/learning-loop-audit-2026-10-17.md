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
