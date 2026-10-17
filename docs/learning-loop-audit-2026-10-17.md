# Judges / council / learning loop: empirical audit (2026-10-17)

Method: public read-only GETs against the prod app (`/api/predictions/resolved`, `/api/learning/stats`, `/api/weights`), then code reads at `claude/port-cursor-config` (= main `e620ee4` + docs). Raw pulls are not committed. Reproduce with the same endpoints.

## Measured (1,476 graded rows; 558 council rows; 316 `council_published`)

| Finding | Evidence |
|---|---|
| Confidence carries no information | `council_published` hit rate by `pick_confidence`: 0.4-0.5 → 0.50 (n=68), 0.5-0.6 → 0.50 (n=225), 0.6-0.7 → 0.48 (n=23). corr(conf, hit) = 0.029. corr(pick_score, hit) = -0.019. |
| Published council picks are always long | direction = up on 100% of 1h and 93% of 24h published picks. Grading is sign-only (`council/grading.py:direction_correct`), so the hit rate is the market's up-rate for those names. |
| Hit rate is ~coin flip, and has not improved | 1h published: n=288, hit 0.51; first half 0.51, second half 0.51. 24h published: n=28, hit 0.36 (small n). |
| Judge scores are near-constant and uninformative | oracle mean 0.87 sd 0.08; echo mean 0.64 sd 0.03; pulse mean 0.70 sd 0.19 (n=558). corr(score, hit): oracle -0.03, echo -0.12, pulse -0.01. corr(score, signed clipped return): oracle +0.07, echo -0.08, pulse +0.13. |
| Judge weights diverged, but not toward skill | live weights oracle 0.086, echo 0.638, pulse 0.276. Echo has the highest weight and the most negative correlation with hits. Mechanism not traced. |
| Expert weights are pinned or chasing noise | `quant` = 2.0 (the cap, `weights.py:31`) in every sampled `weights_at_creation` since Aug 5. `hype` went 0.98 (Sep 9) → 0.14 (Oct 17) on hit rates hype 0.48 (n=228) vs technical 0.55 (n=88); a 7-point gap with SE of about 3-5 points. |
| Sample is not independent | council_published spans 60 days, 34 netuids, up to 10 picks/day; netuid 105 has 52 rows, 61 has 44. |
| Data quality | stats: `cold_cache_alert: true` (14%), 136 ungradeable, 50 `price_data_unavailable`. Some `actual_pct` outliers are in the thousands of percent (pump populations); sign-only grading is unaffected, magnitude stats are. |

## Verified in code
- `judge_correct` (`judges/grading.py:53-58`): returns `council_hit if endorsed else not council_hit`. A judge is graded against the council outcome, not a separate market question.
- `subnet_judges.py:170`: `predicted_pct = price_change_24h`, the same field the judges score.
- `daily_pick_engine.py:349`: publish gate checks `final_confidence < gate` and the directional guard only; `audit["approved"]` is not read there.
- Pump desk claims hit only when `actual >= predicted_pct` (`grading.py:pump_lead_hit`); their hit rates are not comparable to council direction hit rates.

## Not verified / limits
- No market-wide baseline: I cannot say a random long would do better or worse. The ledger holds only picked names. Skill needs a same-window cross-section of all subnets.
- 24h and shadow samples are small (n=28 and 57).
- The mechanism behind the judge-weight divergence, the `hype` drop and the pinned `quant` weight was not traced.
- Items from another session's report not re-checked: stacked adjustment caps, red-team floor ordering, string-matching gates.

## Implication
The loop grades a quantity (sign of the next move for names it already likes) that its own scores do not predict, then moves weights on the result. Weight changes at this sample size are noise. Fix the measurement before adding models: a market-wide baseline, an append-only ledger with the snapshot inputs, Brier/reliability on probabilities, and weight updates gated on a minimum sample and a significance test.
