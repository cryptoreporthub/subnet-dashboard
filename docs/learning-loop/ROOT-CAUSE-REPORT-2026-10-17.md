# Judges, council and learning loop: root-cause report and fix design

Date: 2026-10-17. Scope: judges, council, learning loop, `server.py`, storage, security, Jev. Status: **findings and design only; no product code changed.**
Evidence appendix (raw tables, earlier corrections): `docs/learning-loop-audit-2026-10-17.md`.

Rule applied to every fix below: **root cause or nothing.** A fix that detects, filters, clamps, freezes or retries a symptom is listed as an existing band-aid (section 5), not as a fix.

---

## 1. Executive summary

1. The loop grades the **sign of the next move for names it already likes**. Published council picks are 100% long, so the hit rate is the market's up-rate for those names. Nothing in the data shows skill: 1h published hit rate 0.477, 95% day-clustered CI [0.41, 0.54], 53 days.
2. **Confidence is not a probability.** It shows no positive relationship with outcomes: 1h published hit rate is 0.48 across the 0.4-0.6 confidence range (all horizons, n=289 clean rows). The apparent drop at confidence >= 0.55 (-0.135, 1h only, n=264) is **not significant** (day-clustered 95% CI [-0.30, +0.05]); I retract the earlier suggestion that higher confidence is worse.
3. **The weights are not a function of the ledger.** They are an accumulator of +/- nudges with an asymmetric step (+0.02 / -0.03, break-even hit rate 60%, measured 44-47%), two of four experts receive no learning at all, and replay and live use different row filters.
4. **The judges are not independent.** Oracle and echo endorse 100% of rows, so their grade equals the council's grade by construction. Oracle/pulse scores correlate at 0.64.
5. **Two public routes (`POST /api/feedback`, `POST /api/mindmap/feedback`) wrote expert weights and scenario memory from client-supplied labels.** Fixed on `claude/fx6-single-weight-writer` (not merged).
6. **Scoring caps (the 20/24/40/75 hard caps):** prod's own snapshot reports `count 40, complete false, capped_out 125` of 165 admitted subnets (24% scored); FX11 deletes the caps rather than raising them. Measured prod cost is about 1.3 s per subnet while the same scoring runs in ~3 ms locally, so the cap is compensating for an unexplained I/O or contention cost, not for compute.
7. **Architecture:** keep FastAPI and the slice routers. The defects are in the measurement and learning layers, in swallowed router imports, in `server.py` acting as a shared kernel (21 reverse imports), and in runtime state living in git.

---

## 2. Findings (with verification status)

Legend: **V** verified in code or live data this session; **M** measured on the live ledger (clean rows); **U** unverified or unexplained (listed in section 7).

### 2.1 Measurement (what is graded)
| # | Finding | Evidence | Status |
|---|---|---|---|
| F1 | Council grading is sign-only; published picks are always long, so hit rate = market up-rate for those names | `council/grading.py:direction_correct`; direction=up on 100% of 1h published picks; `publish_gate.py` blocks bearish longs | V, M |
| F2 | No evidence of skill at 1h | n=264, hit 0.477, day-cluster 95% CI [0.410, 0.542], 53 days | M |
| F3 | Selection adds nothing over what the gate held | shadow rows are HOLD counterfactuals (`prediction_loop.py:204,305`); 1h up-rate published 0.477 vs held 0.493 (n=136) | V, M |
| F4 | The ledger cannot supply a market baseline | only 4 published rows had >=3 same-hour peer rows; a market-wide reference is not recorded | M |
| F5 | Pump claims are graded on a different rule (`actual >= predicted_pct`); their hit rates are not comparable to council rates | `grading.py:pump_lead_hit`; clean 1h hit 0.05 / 0.11 / 0.17 | V, M |
| F6 | Judges predict the same field they score (`predicted_pct = price_change_24h`, dashboard path) | `subnet_judges.py:170` | V |
| F7 | A judge is graded against the council outcome, not the market | `judges/grading.py:53-58` | V |

### 2.2 Confidence and the publish gate
| # | Finding | Evidence | Status |
|---|---|---|---|
| F8 | Confidence has no demonstrated discriminating power | bins (all horizons, n=289): 0.4-0.5: 0.48 (62), 0.5-0.6: 0.48 (212), 0.6-0.7: 0.20 (15, too small to read); corr -0.07. 1h only (n=264): hit(conf>=0.55) - hit(conf<0.55) = -0.135, day-clustered 95% CI [-0.302, +0.047]: not significant | M |
| F9 | Loop is circular: confidence blends the resolver hit rate; confidence gates publication; published picks update weights | `state_vector.py:1642` (`_resolver_hit_rate`), `daily_pick_engine.py:349` | V |
| F10 | Publish gate never reads `audit["approved"]` | `daily_pick_engine.py:349` checks confidence and directional guard only | V |
| F11 | Red-team floor resurrects a blocked candidate: multiplier 0.0 then `_apply_multiplier` returns `max(0.88, m*f)`. Latent today because `tradable_subnets()` filters first | `red_team.py`, `daily_pick.py:~124`, `hourly_pick.py:60` | V |
| F12 | `approved` and the missing-field gate depend on string prefixes | `red_team.py` (`startswith`), `daily_pick_engine.py:185` | V |
| F13 | Score adjustments are each capped (memory +/-5 pts, telegram <=5, pump blend <=25%, recovery haircut, value/flow/size tilts) but have no total budget; the calibration they were fitted on was n~60 | `memory_scoring.py:7-8`, `message_intel/calibration.py:166`, `pump_overlay.py:18`, `state_vector.py`, `red_team.py` docstring | V |
| F14 | Prod publish gate is 0.40 (`fly.toml:104`); the code default is 0.50 (`publish_gate.py`). **Correction (2026-10-17):** I earlier claimed the UI label disagrees with prod. It does not: the label is built from the same effective environment, and prod's homepage renders "40% audit gate". The 50% I saw came from my local environment (no fly env). `AGENTS.md` states no gate value. | `fly.toml:104`, `tribunal_hero.html:63`, prod homepage | V |

### 2.3 Weights
| # | Finding | Evidence | Status |
|---|---|---|---|
| F15 | Expert step is asymmetric: +0.02 / -0.03; break-even hit rate 0.60; measured expert hit rates 0.44-0.47 | `weights.py:28-29`; prod trail shows delta -0.03 | V, M |
| F16 | The judge module documents and fixed this exact bug (symmetric steps, commit 15292648, 2026-08-05); experts and signals still have it | `judges/weights.py:14-19` | V |
| F17 | Expert weights track the market's short-run direction: hype 0.12 -> 0.68 (Sep 29 - Oct 5) because 27 of 30 hype-attributed published picks hit (90% vs 0.44 overall), then reverted | ledger; `weights_at_creation` is raw `load_weights()` (`prediction_loop.py:339-340`) | V, M |
| F18 | Two of four experts get no learning (the system's own 2026-10-06 probe reports `expert_graded_counts` quant 0, dark_horse 0, hype 200, technical 69): quant is 2.0 on all 621 rows, dark_horse 1.0 on all 621. Quant is credited on 28 rows, all `council_shadow`, which the live nudge skips; dark_horse is never credited. Expert attribution is single-credit (`expert` field: published = hype 258 / technical 96). Quant carries the highest weight in every score with zero feedback | ledger; `resolver._skip_council_learning` | V, M |
| F19 | Replay is not live: replay includes shadow rows, live skips them. Replay from defaults gives technical 0.10 (with shadow) or 0.74 (without); live is 1.044. Quant 1.0-1.06 vs live 2.0 | `weights.py:_replay_rows_from_blob` vs `resolver.py:133-137` | V |
| F20 | The boot rebalance only runs when weights are near-flat and the env flag is off, so a stale non-flat value is never repaired | `maybe_rebalance_council_weights_on_boot`; `COUNCIL_WEIGHT_REBALANCE_ON_BOOT` absent from fly tomls | V |
| F21 | Learned signal weights at creation are negatively correlated with the outcome. Day-clustered bootstrap 95% CIs exclude zero: macd_cross -0.18 [-0.29, -0.07] (n=289), williams_r -0.23 [-0.35, -0.11] (n=151), cci_divergence -0.16 [-0.26, -0.05] (n=275); mfi/rsi weaker. Consistent with weights chasing streaks that revert, but time-varying base rates are a confound the clustering does not remove, so this shows the weights are not helping, not the mechanism | ledger | M |
| F22 | Live state includes history not in the current ledger (replay of 304 clean rows from defaults does not reproduce it) | simulation | V |

### 2.4 Judges
| # | Finding | Evidence | Status |
|---|---|---|---|
| F23 | Oracle and echo endorse 100% of rows (pulse 69%): their grade equals the council grade by construction (both 148 correct / 156 wrong) | ledger | M |
| F24 | Judge scores barely vary: oracle sd 0.08, echo sd 0.03, pulse sd 0.19. Oracle-pulse correlation 0.64 | ledger | M |
| F25 | Judge scores do not predict returns: corr with raw clipped return, published: oracle -0.01, echo **-0.24**, pulse +0.11 | ledger | M |
| F26 | Nudge size is scaled by conviction (`|score-threshold|*2`, floor 0.25), so identical outcomes move judges by different amounts: oracle -0.0130, echo -0.0063, pulse -0.0050 on the same miss (live trail) | `judges/grading.py`, prod trail | V |
| F27 | Hits are scaled by realised move (can be <1), misses are floored at 1 | `judge_nudge_magnitude_scale` | V |
| F28 | Why live echo is highest (0.638) is **unexplained**: my simulation over the clean ledger put echo last (0.13). Prior-epoch history must be in the live state | simulation | U |

### 2.5 Data quality
| # | Finding | Evidence | Status |
|---|---|---|---|
| F29 | 300 of 1,476 graded rows are phantom-VWAP contaminated (Aug 7-17, all `price_source=vwap`), mostly pump rows | ledger | M |
| F30 | The exclusion predicate covers every replay/eval path and the live resolver (via unit-mismatch rejection at `resolver.py:828,955`); the uncovered writers were the two feedback routes (F33, F35) | grep of ~18 call sites | V |
| F31 | The exclusion is a ratio heuristic over a mixed-unit price feed (TAO vs USD per alpha), not a typed price | `grading.py:is_price_unit_mismatch` | V |
| F32 | `cold_cache_alert: true` (14%), 136 ungradeable, 50 `price_data_unavailable` | `/api/learning/stats` | V |

### 2.6 Security and operations
| # | Finding | Evidence | Status |
|---|---|---|---|
| F33 | **Two public routes wrote learning state through `LearningEngine.record_feedback`:** `POST /api/feedback` (`datastore/learning_engine.py`, removed in FX6) and `POST /api/mindmap/feedback` (`server.py:2331`, rate-limited). Each took a client-supplied `correct_prediction` and (a) called `nudge_expert` on an expert chosen by substring-matching the `recommendation` string, and (b) wrote a scenario-memory entry (`features.subnet_id`, outcome correct/wrong) that `scenario_outcome_adjustment` reads as a +/-2 point score tilt. Both were on the public-write allowlist (`write_auth.py`). No frontend code calls either (tests only); `docs/file-map-and-scope.md:109` described the route as "stored, not yet applied" while the code applied it. Prod: an empty `{}` POST to `/api/feedback` returned 400 (handler reached, no 401) and to `/api/mindmap/feedback` returned 200; both bodies empty, nothing changed | `write_auth.py`, `learning_engine.py`, `server.py:2331`, `memory_scoring.py:67-99`, prod probes | V |
| F34 | `WRITE_API_TOKEN` is set in prod (unauthenticated POST to an unknown path returns 401). Other write routes (`/api/learning/rebalance-weights`, `/api/learning/trigger`, `/api/scenario-memory`) are token-protected | non-mutating probe | V |
| F35 | **Correction:** I earlier wrote that `/api/mindmap/feedback` was allowlisted with no route. That was wrong (my grep covered `internal/` only); the route exists in `server.py:2331` and is live. It is not a dead allowlist entry | grep, prod probe | V |
| F35b | A dormant third weight writer existed: `SelfLearning.adjust_jury_weights` (`message_intel/self_learning.py`) called `nudge_expert` from substring-matched pattern descriptions. It was only reachable from `start_background_learning`, which no boot path starts (a test asserts that). Removed in FX6 | `self_learning.py`, `tests/test_learning_loop_health.py:760` | V |
| F35c | `MindmapBridge` loads `soul_map_state` at init and `_save_to_disk` blindly replaces whole subtrees (`soul_map_state`, `feedback_logs`) from that copy. A request-scoped bridge (as in `/api/mindmap/feedback`) could drop concurrent writers' updates (pump ladder, last picks, trail rows). Weights live under `adversarial_state.council_weights`, `expert_weights`, `judge_weights`, which this path does not write, so weights were not at risk from this race. Fixed in FX6 by appending inside the soul-map lock against fresh disk state; the regression test fails on the old code | `mindmap_bridge.py`, prod `/api/soul-map` key layout | V |
| F36 | `CALIBRATION_AUTO_RETRAIN` is off in both fly tomls; capture grading mode is off in prod (trail `band`/`capture` null) | `fly.toml:87`, prod trail | V |
| F37 | The repo is public (`private: false`). Recorded as a fact only; it does not influence any decision in this report | API probe | V |
| F38 | Only 2 of 8 SQLite-using modules enable WAL (`fetchers/_sqlite.py`, `message_intel/models.py`); `chain_client.py` (5 sites) and `investigation/service.py` (3) connect directly. Web, inline worker and fetch child share one volume | grep | V |
| F39 | Tests rewrite six committed `data/*.json` files; 57 tracked files under `data/`, including `pump_desk/snapshots/*.json` | git | V |

### 2.7 Scoring-universe caps (the 24 / 40 hard caps)
The council scores a capped slice of the subnets, not every active subnet. Count caps found in source (`@ main e620ee4`) and fly config:

| Cap | Where | Effective on prod web (from source + `fly.toml`; not env-probed) |
|---|---|---|
| `TOP_SCORING_UNIVERSE` default **20** | `server.py:647` (not set in fly.toml) | 20 |
| `PICK_SCHEDULER_UNIVERSE_CAP` default **24** | `pick_scheduler.py:32,157` (`min(24, server TOP)`) | min(24, 20) = 20 |
| `min(24, TOP_SCORING_UNIVERSE)` | `server.py:1066, 3391` | 20 |
| `TOP_SCORING_UNIVERSE` default **40** and `min(40, ...)` | `daily_pick_engine.py:209-210`, `pick_selection_audit.py:58-72`, `score_snapshots.py:53` | engine/audit paths: min(24, 40) = 24; snapshot fallback 40 |
| `SCORE_SNAPSHOT_MAX_SUBNETS` = **40** | `fly.toml:89`, `fly.worker-v2.toml:64`, soak toml `:75` | 40 |
| mid-rank window 11-75, mega ceiling 10 | `scoring_cap.py:111-113`, fly tomls `:91-93` | heuristic pool when no snapshot ranking exists |

| # | Finding | Evidence | Status |
|---|---|---|---|
| F44 | The same intent ("how many subnets to score") has at least four different values (20/24/40/75) in four places; effective values differ by code path | table above | V |
| F45 | `cap_subnets_for_scoring` ranks by the **previous** snapshot and slices (`scoring_cap.py:101-108`), so eligibility depends on a prior capped result: names that were scored stay selected, unscored names stay deprioritised (also the user's own handoff finding 4) | `scoring_cap.py` | V |
| F46 | The published-pick sample is narrow: 34 distinct netuids over 60 days, netuid 105 = 52 rows, 61 = 44 rows (consistent with F44/F45; cause not isolated) | ledger | M |
| F47 | The handoff (pin `9535c3c2`) said snapshot coverage is `len(rows)` and failures are swallowed. Current main already tracks `day_attempted/day_succeeded/hour_attempted/hour_succeeded` per netuid (`score_snapshots.py:305-357`); the handoff finding is partly stale. Whether a snapshot can still be reported complete when some netuids failed was not re-verified | `score_snapshots.py` | V (lists exist), U (completeness semantics) |
| F48 | Prod snapshot cycle (2026-10-17 07:20Z, `/api/learning/health` `score_snapshot`): `count 40`, `complete false`, `capped_out 125`, `selection_policy rank_cap`, membership expected 165 / admitted 165 (taomarketcap), `day_scoring_seconds 51.7`, slowest netuids 1.31-1.45 s, i.e. about 1.3 s per subnet, near-uniform. Locally the same `score_subnet_for_day` takes ~3 ms with a prod-size ledger (first call 1.8 s to load it), so the prod cost is not scoring math. Likely per-subnet I/O or contention (unverified); full-active serial scoring of 165 would be about 215 s | prod health, local profile | V (numbers), U (cause) |
| F49 | `tradable_subnets()` removes root/invalid IDs and dedupes by netuid; it does not establish *active* membership | `internal/subnets/tradable.py:43-51` | V |

| F50 | `price_cache.json` is a 4.3 MB whole-file JSON, read by at least 12 modules and rewritten by several writers; `subnet_judges.py:226-245` does read-modify-write of the whole file with a raw `open(..., "w")` (no lock, no atomic write) once per subnet judged. State-vector scoring memoises it by mtime, so any writer touching the file invalidates the memo. Local test: invalidating the memo each call costs 47 ms per subnet (warm: 2 ms) | `state_vector.py:50-69`, `subnet_judges.py:226-245`, local timing | V |
| F51 | The 47 ms invalidation cost explains at most ~4% of the ~1.3 s/subnet seen on prod; the rest of F48 stays unexplained | local vs prod | V |

### 2.8 Architecture
| # | Finding | Evidence | Status |
|---|---|---|---|
| F40 | 16 router imports are wrapped in `try/except`; none pull third-party-only dependencies, so a failure is always a bug and is currently silent | `server.py:35-171`, `requirements.txt` | V |
| F41 | `server.py` is a shared kernel: 3,467 lines, 104 functions, 32 routes, `_lifespan` 265 lines; **21 imports from other modules back into `server`** (8 of them `_get_subnets_with_source`) | grep | V |
| F42 | Prod serves `asgi_entry:app` (gzip + static-cache wrapper), but the contract test imports `from server import app` (`tests/test_endpoint_contract.py:19`): the prod wrapper is not covered by the contract guard | `scripts/run_web_with_guard.py`, `asgi_entry.py` | V |
| F43 | UI: strong visual identity; at 1440px the content is a ~680px column, the fixed status bar overlaps cards, mobile tab bar and FAB cover content, small text over gradients is low contrast; ~1.2 MB hand-written JS/CSS including `ui-legacy.css` | screenshots | V |

---

## 3. Root causes

| RC | Root cause | Findings it explains |
|---|---|---|
| RC1 | The graded target is not skill-relevant: absolute sign of return on always-long picks, with no market reference captured | F1-F5, F8, F17, F21, F25 |
| RC2 | Weights are a stateful online accumulator with an arbitrary asymmetric step, not a pure function of an eligibility-filtered ledger; two code paths (live nudge, replay) apply different eligibility | F15-F16, F19-F20, F22 |
| RC3 | Learning credit is assigned to one "expert" per row by an attribution heuristic instead of grading each expert's own signed output on every row | F18, `rogue` rows, F17 |
| RC4 | Judges are thresholded endorsers graded against the council, not independent probability forecasters graded against the market | F6-F7, F23-F28 |
| RC5 | Confidence is a heuristic number that feeds on its own outcome statistic, with no out-of-sample calibration | F8-F9, F13 |
| RC6 | Weight-writing is reachable from outside the resolver (public `/api/feedback`) | F33, F35 |
| RC7 | Audit state is encoded in strings and multipliers instead of typed, blocking states, and the gate does not consume it | F10-F12 |
| RC8 | Prices carry no unit, so unit mixing is detected by heuristic after the fact | F29-F32 |
| RC9 | The ledger is not point-in-time or append-only: runtime state is in git, JSON blobs are rewritten, no universe snapshot is stored | F4, F38-F39, F22 |
| RC10 | Router wiring and shared helpers live in the entry point | F40-F42 |
| RC11 | Scoring coverage is bounded by hard-coded counts (20/24/40/75) that stand in for an unmeasured per-run cost problem, and eligibility is decided by slicing a prior capped snapshot | F44-F49 |

---

## 4. Root-cause fixes (design)

Each fix names the structure that makes the defect unrepresentable and the test that proves it.

### FX1 (RC1): grade excess return against a recorded universe reference
- At pick creation and at resolution, record `universe_ref = {netuid: price(value, unit, source)}` for the tradable universe (pick_history already stores `entry_prices_snapshot`; extend the same capture to every prediction and to the resolve time).
- Target = `excess = r_pick - median(r_universe)` over the identical window. A pick is a hit when `excess > 0`. Always-long picks stop being gradable by market drift.
- Acceptance: for any graded row, `excess` is reproducible from stored inputs alone; a synthetic always-long strategy on a flat-relative universe scores 0.50 +/- sampling error.
- Falsifier: if after 100+ clean days excess hit rate has a day-clustered CI containing 0.5, the council has no demonstrated edge and must not gate publication.

### FX2 (RC2): weights as a pure function of the ledger
- One module computes weights: `weights = f(eligible_rows)`; no per-resolve nudges.
- One eligibility predicate (`is_learning_eligible(row)`) used by live and replay: not shadow, not pump, price-typed (FX8), graded on FX1, minimum sample reached. Shadow policy is decided once, in that predicate.
- Estimator: shrunk posterior mean of per-expert (and per-signal) excess-hit rate with a minimum-n gate and shrinkage to the prior; symmetric by construction. No asymmetric step, no cap-pinned artifacts.
- Recompute in batch on a schedule; persist with the ledger hash so the same inputs always give the same weights.
- Acceptance: `live_weights(ledger) == replay_weights(ledger)` exactly; deleting the persisted state and recomputing yields the same value; a 44% hit-rate expert does not drift to the floor.

### FX3 (RC3): grade every expert's own output on every row
- The score payload already carries per-expert contributions (`expert_contributions`, `state_vector.py:1061`). Grade each expert's signed contribution against the FX1 outcome for every eligible row.
- Removes single-credit attribution, `rogue`, and the frozen quant/dark_horse weights (every expert gets feedback on every row).
- Acceptance: every expert has `n_graded == n_eligible_rows`; no expert weight is constant across the ledger.

### FX4 (RC4): independent probability judges graded on the market
- Judges emit `P(excess > 0)` from **independent input slices**; no endorsement threshold, no conviction-scaled step.
- Score with Brier (and reliability curve); weight with the FX2 estimator.
- Judges never see the council score or each other's output.
- Acceptance: judge score correlations are reported and a judge whose out-of-sample Brier skill vs the base rate is not positive gets zero weight; endorse-rate-style degenerate behaviour (100% endorse) is impossible because there is no threshold.
- Jev enters here, as a shadow judge only (section 6).

### FX5 (RC5): calibrated probability, out-of-time validation
- Publish on a calibrated `P(excess > 0)` (isotonic or Platt on a walk-forward split), not on a heuristic confidence that includes the resolver hit rate.
- Remove `_resolver_hit_rate` from the confidence path (breaks the circular edge).
- Every score adjuster (memory, telegram, pump, recovery, tilts) must show out-of-sample lift via ablation on the FX1 ledger or be deleted. Adjusters share one recorded budget on the row.
- Acceptance: reliability curve is monotone out-of-sample; ablation table exists for each adjuster.

### FX6 (RC6): single writer for learning state (implemented on `claude/fx6-single-weight-writer`, commit `aea52cf8`)
Decision rationale (on merit; who can read the repo is irrelevant): a client-supplied label is not a graded outcome; the price-based resolver is the only authoritative grader. A second writer to the same state makes weights irreproducible from the ledger (RC2). Substring-matching a free-text `recommendation` to pick which expert to reward is a string decision (RC7). Nothing in the repo calls either route. So the learning side effects are removed, not gated or authenticated.
- `LearningEngine.record_feedback`, `_normalize_recommendation` and `POST /api/feedback` are deleted (deliberate API removal: the route is in the historical 47-route monolith (`528ba62:server_original.py:1058`) and in the committed OpenAPI spec; `.restless/openapi.json` regenerated, `restless_openapi.py --check` passes). `/api/feedback` leaves the public-write allowlist and the contract list.
- `POST /api/mindmap/feedback` stays as the single feedback sink: user notes and alignment logs only, no weight or scenario-memory writes (matches the documented "stored, not yet applied").
- `SelfLearning.adjust_jury_weights` (dormant) is deleted.
- `MindmapBridge` trail/feedback appends run in-lock on fresh state (F35c).
- `tests/test_single_weight_writer.py` pins the allowed weight writers and the allowed scenario-memory writers by AST call-name scan (negative control verified: adding a writer fails it); aliased imports would evade it (noted in the test).
- Tests updated, not skipped: the feedback-nudge assertions became "feedback never changes weights or scenario memory" and "legacy route is gone".
- Verified: CI-smoke commands (static guards, `py_compile`, OpenAPI check, listed pytest set, hydration smoke) and Deploy Guard tests pass (378 passed). Full suite: 179 failed on the branch vs 178 on main; the five differing failures are order/timing dependent (three pass in isolation on the branch; one fails in isolation on main). The three failures found in the touched test files fail identically on clean main (`test_disposition_adjustment_bullish`, two `test_rogue_attribution`).
- Not changed (still open): quant/dark_horse never receive grades (FX3), echo's consensus share, weights as a pure function (FX2).

### FX7 (RC7): typed audit
- `Concern` becomes a typed value (code, severity, `blocking: bool`); `approved = not any(c.blocking)`; a blocked candidate is a state, not a multiplier of 0.0.
- The publish gate consumes `approved`.
- Acceptance: a non-tradable candidate cannot be published even if later flags fire (regression test for F11).

### FX8 (RC8): typed prices
- Prices are `(value, unit, source)`. Comparing across units raises. `is_price_unit_mismatch` and the VWAP quarantine are retired once all producers emit typed prices; historical contaminated rows are tagged once and excluded by tag.
- Acceptance: no `ratio >= ceiling` heuristic remains in the grading path.

### FX9 (RC9): append-only point-in-time ledger in SQLite
- Tables: `predictions` (inputs at pick time, universe_ref, scores, probabilities), `resolutions` (outcome, excess, price typed), `weight_state` (derived, hash-addressed). WAL + `busy_timeout` set in one connection helper used by every module (including `chain_client.py`, `investigation/service.py`).
- Runtime state leaves git; tests run against a temp `DATA_DIR`.
- Acceptance: running the test suite leaves `git status` clean; any past decision can be recomputed from stored inputs.

### FX10 (RC10): wiring and kernel
- Router imports become unconditional (a broken slice fails boot and CI). The PR #1437 registry is dropped: it duplicates `server.py` wiring.
- Extract the shared helpers (`_get_subnets_with_source`, `load_data`, `_normalize_registry_subnet`, ...) into `internal/subnets/` so no module imports `server`; extract `_lifespan`; move the 32 routes into routers.
- Acceptance: `grep "from server import"` outside `asgi_entry.py` and tests returns nothing; contract test passes against `asgi_entry:app` and `server:app`.

### FX11 (RC11): full-active scoring, no count caps
Contract (from the repo's own `cap-audit/cursor-cap-audit-handoff.md`): score every dynamically established **active non-root** subnet; do not replace 40 with another magic constant; keep concurrency, provider rate limits, pagination, retention, cache-byte bounds and score clamps distinct from count caps; do not "fix" by raising deadlines.
- Root cause to fix, not the symptom: scoring is recomputed per request/run for the whole slice, so a count cap was the only way to stay inside the 90s / 480s budgets. Replace with an **incremental per-subnet score store**: a worker scores each active subnet when its inputs change (input-hash keyed; `pick_score_cache` is the seed), with an explicit per-subnet state `{scored, stale, failed(reason), unscored}` and attempted / succeeded / failed / netuid coverage emitted on every cycle.
- Pick selection = argmax over the full fresh score table. Eligibility comes from authoritative active membership resolved dynamically (unknown or stale membership is an explicit state), never from slicing a prior snapshot. Root is excluded from alpha scoring without being hidden from network displays.
- Delete: `TOP_SCORING_UNIVERSE` (all three defaults), `PICK_SCHEDULER_UNIVERSE_CAP`, `SCORE_SNAPSHOT_MAX_SUBNETS`, the `min(24, ...)` and `min(40, ...)` expressions, `cap_subnets_for_scoring` and the mid-rank heuristic pool, and the matching fly.toml entries. Keep a deletion test: no module may define a subnet-count default.
- Dependencies: FX1 first, so the learning ledger records the universe each pick was chosen from; otherwise widening the universe silently changes the evaluated population. FX9 (SQLite, single connection helper) for the score table.
- Acceptance: every active non-root netuid has a score row with a state after each cycle; a complete cycle cannot report full coverage when any netuid is `failed`/`unscored`; peak memory and cycle time are measured under shared web+worker load before rollout.
- Rollout gate (from the handoff, still binding): measure real per-subnet cost, effective Fly env, RSS headroom and authoritative membership; rollback on missing active IDs, falsely green coverage, memory growth/OOM, overlapping jobs, stale/late overwrites, or daily-pick/audit parity break. No production change without separate approval.

---

## 5. Existing band-aids (do not extend; retire as the root fix lands)

| Band-aid | Symptom it patches | Retired by |
|---|---|---|
| `is_phantom_vwap_quarantine`, `is_price_unit_mismatch` | mixed-unit prices | FX8 |
| `expert_for_replay_row` rogue guard, "rogue" bucket | single-credit attribution | FX3 |
| One-shot boot rebalance, `soft_blend_weights`, `apply_rebase_guards` | weights not a function of the ledger | FX2 |
| Judge symmetric-step patch, conviction scaling | judge weights collapsing | FX4 |
| Weight clamps [0.1, 2.0] | unbounded accumulator | FX2 (posterior is bounded) |
| `_apply_multiplier` floor, `RED_TEAM_MAX_HAIRCUT` | stacked haircuts | FX5, FX7 |
| `tradable_subnets()` pre-filter hiding F11 | blocked candidates | FX7 |
| Cold-cache and `price_data_unavailable` alerts | missing price at horizon | FX9 (store inputs at capture) |
| 20/24/40/75 scoring caps, `min(24, ...)`, snapshot-rank slicing | per-run scoring cost | FX11 |
| Raising timeouts (90s / 480s) to fit more subnets | same | rejected: handoff forbids it; FX11 removes the need |
| Freezing weight updates | noise | **rejected**: it stops the symptom without fixing RC2 |

---

## 6. Jev / decision-model integration

Sources: Ditto memories (2026-09-26 evaluation, 2026-10-15 integration note); `decisionmodels.io` is reachable (HTTP 200) and describes itself as a Jev-compatible host separate from TypeSafe's Jev.
- Prior plan (kept): fix judge independence first; shadow forecaster, no write access; promote only on Brier skill over ~100 graded observations; **"Jev emits, code scores"**; rugger-flagged text never enters the state; route via a gateway that does not depend on one vendor's signup.
- Correction to that plan: it said judge weights "structurally cannot diverge." They have diverged (oracle 0.086 / echo 0.638 / pulse 0.276), though not toward skill.
- Sequencing: Jev enters at FX4, after FX1 (a market-relative target) and FX9 (point-in-time inputs). Before that it would be graded against the council, which reproduces the current defect.
- Verified from the public pages (2026-10-17): Decision Models hosts four open models (s1-pro, s1-fast, s1-vision, quyet-1-large; Apache-2.0), billed per 1M **input** tokens with free output, pay-as-you-go from EUR 1, keys are server-side only. Two tiers: Peer-to-Peer (independent providers on network-enabled keys **may store content**) and EU (gateway and GPU inference in the EU, no payload logs). A launch promo makes `s1-fast-1` / `s1-pro-1` free on the Peer-to-Peer tier until Sun 18 Oct 2026 22:00 UTC (single-question text only). FAQ on the landing page states it is **not** the Jev service itself.
- Still unverified: per-token price figures, rate limits, latency and calibration of the hosted models, the exact request/response schema (the quickstart examples need an API key), and whether answers are comparable to TypeSafe's Jev. Any use with dashboard/Telegram text implies choosing the EU tier or sending only derived numeric features; rugger-flagged text stays out either way.

---

## 7. Verification ledger

**Verified in code or live data:** F1, F3, F6-F7, F9-F12, F14-F16, F18-F20, F23-F27, F29-F42, F44-F45, F49, F37 (repo is public), write-auth active in prod, capture mode off, calibration auto-retrain off, quarantine coverage of weight-update paths, red-team floor mechanics, adjuster caps, contract test imports `server:app` only, decisionmodels.io facts listed in section 6.

**Measured, with stated limits:** F2, F4 (baseline absent), F8 (CI included), F17, F21 (CI included, confounded), F25, F46 (rows clustered: 34 netuids, 60 days).

**Closed this round**
| Item | Result |
|---|---|
| Contract test covers prod wrapper? | **No** (`from server import app`) |
| Is the repo public? | **Yes** (`private: false`) |
| F8 significance | **Not significant** (CI [-0.30, +0.05]); claim retracted |
| F21 significance | **Excludes zero** for macd, williams_r, cci under day-cluster bootstrap; mechanism still unproven |
| `/api/feedback` ever used? | **Cannot be established.** The trail endpoint is capped at 500 events with no paging; the last 500 (about 2 days, 36 weight changes) contain no `reason=feedback` |
| Adjuster lift | **Cannot be measured from the ledger:** rows do not store pump-overlay, telegram, recovery or memory adjustment fields. FX9/FX5 capture comes first |
| Market baseline from existing data | **Not derivable:** only 1 of 29 `pick_history` rows keeps the universe snapshot; the prediction ledger stores none |
| F14 attribution | Corrected: `AGENTS.md` states no gate value |
| Jev / Decision Models facts | Recorded in section 6 |

**Still unverified or unexplained (must not be treated as fact):**
1. Why live judge weights are oracle 0.086 / echo 0.638 / pulse 0.276. Trajectory evidence: 2026-10-06 probe oracle 0.149 / echo 0.551 / pulse 0.301; now oracle 0.086; raw (trail) oracle ~0.14, echo ~1.07, pulse ~0.47. Not reproducible from the current ledger.
2. Origin of quant = 2.0: it pre-dates the earliest ledger row (Aug 5) and is already present on 2026-10-06. The code docstring (`signal_expert.py:115-123`, commit `713a4a50`, 2026-08-09) says legacy misattribution inflated it to the cap; I did not reproduce that, and git history of committed data/docs holds no earlier value.
3. Whether `/api/feedback` was abused before the last ~2 days (no available history).
4. Per-subnet scoring cost, memory headroom and effective env values on prod (no flyctl/token here; `fly.toml` and public endpoints only), and the current authoritative active-subnet count.
5. Whether a snapshot can report complete coverage when some netuids failed (F47). Prod currently reports `complete: false` for a 40-of-165 cycle, which is the honest direction; the failure-case semantics were not tested.
5b. Why scoring costs ~1.3 s per subnet on prod versus ~3 ms locally (F48). Price-cache invalidation accounts for at most 47 ms (F51); no prod profiler access for the rest.
5c. Body of the 2026-09-08 Council Learning Safety Batch and whether it shipped (section 7b).
6. Decision Models: price figures, limits, latency, schema, comparability to Jev.
7. Prod secrets, machine state, logs.

---

## 7b. Prior decisions and evidence found in Ditto (not previously reflected here)

Read 2026-10-17 via Ditto search; saved by earlier sessions. Treated as records of what was decided or found then, not as verified facts now.
- **2026-10-12 "Judge Layer Rebuild Decisions"** (main `64b9c54`): decisions (1) Echo gets **zero** weight in consensus now (reversible), (2) **yes to universe-wide scoring** (worker stores per-cycle features and judge scores for all active subnets; reuse snapshot features, no second heavy pass; snapshot cost issue #1372), (3) label-source facts: price lookback 7d, cache TTL 300s, TMC TTL 60s, hydration capped 30d, TMC gives exactly 720 hourly candles, **TMC candles rescale historical TAO/USD by the current alpha price so their labels are untrustworthy**, prefer native GeckoTerminal OHLCV where a pool is mapped, >30d unavailable.
  Its evidence corroborates this report from an independent export: Echo AUC 0.40 (95% CI 0.34-0.47, p=0.005), Oracle ~0.46, Pulse ~0.51, oracle and echo endorse 100%, council P(actual>0) = 50.3%, and the same 300 phantom-VWAP rows (price ratio ~186-212; pump_lead hit 63.1% -> 13.5% once excluded). It also states those rows **fed expert, signal and judge weight nudges**.
- **Echo-zero decision is not in the code.** `subnet_judges.py` consensus multiplies each judge by `normalized_judge_weights()`; I found no override. On prod Echo holds the largest consensus share (0.638 normalized) while being the judge shown to be below chance. This decision is approved but unimplemented; FX4 supersedes it, but until FX4 lands the consensus display carries it. Decision for the owner: apply the approved Echo=0 as an explicit interim step, or accept FX4 timing.
- **Storage stance recorded 2026-10-12:** "pick-level judge ledger stays table-free; universe-level observations need SQLite via `internal/store/db.py`." FX9 here proposes SQLite for the prediction ledger as well. This conflicts with that stance on the pick-level ledger; the owner stated today that SQLite is missing from places it belongs. Decision needed (flagged in the reply).
- **2026-09-08 "Council Learning Safety Batch"** (execution brief: freezing noisy council learning, fail-closed publication gates, MFE/base-rate measurement, dry-run weight rebase). Only existence and summary seen; body not read. Freezing is rejected here as a band-aid; MFE/base-rate measurement overlaps FX1. Whether any of it shipped is unverified.
- **2026-09-26 Jev evaluation:** plan summarised in section 6; its claim that judge weights "cannot diverge" is wrong (corrected in Ditto).
- **2026-10-15 Decision Models note:** shadow-mode second opinion for the Pump Desk; consistent with section 6.

---

## 8. Order of work (each item is a reviewable PR)

0. **FX6** (done on `claude/fx6-single-weight-writer`, unmerged): unverified inputs cannot write weights or scoring memory; one feedback sink; writer allowlist test.
1. **FX10a**: unconditional router imports; drop the #1437 registry; keep its duplicate-CONTRACT and forbidden-import guards.
2. **FX9**: temp `DATA_DIR` in tests, stop tracking runtime state, one SQLite connection helper (WAL + busy_timeout); move `price_cache.json` (F50) behind an atomic, single-writer store.
3. **FX1 + FX8**: capture universe reference and typed prices going forward (data collection starts the clock on a clean evaluation window).
3b. **FX11**: full-active scoring, delete the 20/24/40/75 caps (after FX1 so the evaluated population change is recorded; gated by the measurements in FX11).
4. **FX2 + FX3**: deterministic weight function and per-expert grading, shadow-run beside the current weights.
5. **FX7**: typed audit and gate consumption.
6. **FX4 + FX5**: independent probability judges, calibrated publish probability, ablations.
7. **FX10b**: extract `server.py` kernel, lifespan, routes.
8. Jev as a shadow judge.
9. UI pass from the screenshots, retire `ui-legacy.css`.

Promotion rule for any model or weight change: out-of-time validation on the FX1 ledger; no promotion on in-sample results.

---

## 9. Deployed revision and reproduction

- Prod `/version`: `fbb13f4c83ec567cb98c3b1490e6ff9e0dc0acd4` (checked 2026-10-17). That commit is main `e620ee4` plus one docs file (`docs/.../2026-10-17-e620ee4b-live-probe-1434.md`); `git diff e620ee4 fbb13f4` touches nothing under `internal/`, `datastore/`, `server.py` or config. **The code I read is the code prod runs.**
- Prod-verified: `/api/feedback` reachable and unauthenticated (400 on `{}`); write-auth active elsewhere (401 on unknown-path POST); snapshot status via `/api/learning/health`.

## 9b. Reproduction

- Public read-only endpoints used: `/api/predictions/resolved`, `/api/learning/stats`, `/api/weights`, `/api/learning-metrics`, `/api/mindmap/trail`, `/api/learning/health`.
- Clean-row filter: `|actual_pct| <= 50` and `created_at` outside 2026-08-07..2026-08-18, population `council_published` / `council_shadow`; weights replay via `internal.council.weights.replay_weights_from_predictions` on a local copy of the ledger.
- No state-changing request was sent to prod; the write-auth probe used a nonexistent path.
