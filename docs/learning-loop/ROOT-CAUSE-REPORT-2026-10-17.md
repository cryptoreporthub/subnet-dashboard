# Judges, council and learning loop: root-cause report and fix design

Date: 2026-10-17. Scope: judges, council, learning loop, `server.py`, storage, security, Jev. Status: **findings and design only; no product code changed.**
Evidence appendix (raw tables, earlier corrections): `docs/learning-loop-audit-2026-10-17.md`.

Rule applied to every fix below: **root cause or nothing.** A fix that detects, filters, clamps, freezes or retries a symptom is listed as an existing band-aid (section 5), not as a fix.

---

## 1. Executive summary

1. The loop grades the **sign of the next move for names it already likes**. Published council picks are 100% long, so the hit rate is the market's up-rate for those names. Nothing in the data shows skill: 1h published hit rate 0.477, 95% day-clustered CI [0.41, 0.54], 53 days.
2. **Confidence is not a probability.** Hit rate when confidence >= 0.55 is 0.375 (n=64) against 0.510 below it (n=200). Suggestive, not significance-tested.
3. **The weights are not a function of the ledger.** They are an accumulator of +/- nudges with an asymmetric step (+0.02 / -0.03, break-even hit rate 60%, measured 44-47%), two of four experts receive no learning at all, and replay and live use different row filters.
4. **The judges are not independent.** Oracle and echo endorse 100% of rows, so their grade equals the council's grade by construction. Oracle/pulse scores correlate at 0.64.
5. **There is a public, unauthenticated weight writer** (`POST /api/feedback`). The repo is public, so this is documented to the internet. Fix first.
6. **Architecture:** keep FastAPI and the slice routers. The defects are in the measurement and learning layers, in swallowed router imports, in `server.py` acting as a shared kernel (21 reverse imports), and in runtime state living in git.

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
| F8 | Confidence has no discriminating power | bins 0.4-0.5: 0.48 (62), 0.5-0.6: 0.48 (212), 0.6-0.7: 0.20 (15); conf>=0.55: 0.375 (64) vs 0.510 (200); corr -0.07 | M |
| F9 | Loop is circular: confidence blends the resolver hit rate; confidence gates publication; published picks update weights | `state_vector.py:1642` (`_resolver_hit_rate`), `daily_pick_engine.py:349` | V |
| F10 | Publish gate never reads `audit["approved"]` | `daily_pick_engine.py:349` checks confidence and directional guard only | V |
| F11 | Red-team floor resurrects a blocked candidate: multiplier 0.0 then `_apply_multiplier` returns `max(0.88, m*f)`. Latent today because `tradable_subnets()` filters first | `red_team.py`, `daily_pick.py:~124`, `hourly_pick.py:60` | V |
| F12 | `approved` and the missing-field gate depend on string prefixes | `red_team.py` (`startswith`), `daily_pick_engine.py:185` | V |
| F13 | Score adjustments are each capped (memory +/-5 pts, telegram <=5, pump blend <=25%, recovery haircut, value/flow/size tilts) but have no total budget; the calibration they were fitted on was n~60 | `memory_scoring.py:7-8`, `message_intel/calibration.py:166`, `pump_overlay.py:18`, `state_vector.py`, `red_team.py` docstring | V |
| F14 | Prod publish gate is 0.40 (fly.toml), `AGENTS.md` documents 0.50 | `fly.toml:104` | V |

### 2.3 Weights
| # | Finding | Evidence | Status |
|---|---|---|---|
| F15 | Expert step is asymmetric: +0.02 / -0.03; break-even hit rate 0.60; measured expert hit rates 0.44-0.47 | `weights.py:28-29`; prod trail shows delta -0.03 | V, M |
| F16 | The judge module documents and fixed this exact bug (symmetric steps, commit 15292648, 2026-08-05); experts and signals still have it | `judges/weights.py:14-19` | V |
| F17 | Expert weights track the market's short-run direction: hype 0.12 -> 0.68 (Sep 29 - Oct 5) because 27 of 30 hype-attributed published picks hit (90% vs 0.44 overall), then reverted | ledger; `weights_at_creation` is raw `load_weights()` (`prediction_loop.py:339-340`) | V, M |
| F18 | Two of four experts get no learning: quant is 2.0 on all 621 rows, dark_horse 1.0 on all 621. Quant is credited on 28 rows, all `council_shadow`, which the live nudge skips; dark_horse is never credited. Expert attribution is single-credit (`expert` field: published = hype 258 / technical 96). Quant carries the highest weight in every score with zero feedback | ledger; `resolver._skip_council_learning` | V, M |
| F19 | Replay is not live: replay includes shadow rows, live skips them. Replay from defaults gives technical 0.10 (with shadow) or 0.74 (without); live is 1.044. Quant 1.0-1.06 vs live 2.0 | `weights.py:_replay_rows_from_blob` vs `resolver.py:133-137` | V |
| F20 | The boot rebalance only runs when weights are near-flat and the env flag is off, so a stale non-flat value is never repaired | `maybe_rebalance_council_weights_on_boot`; `COUNCIL_WEIGHT_REBALANCE_ON_BOOT` absent from fly tomls | V |
| F21 | Learned signal weights are negatively correlated with the next outcome (macd -0.18 n=289, williams_r -0.23 n=151, cci -0.16, mfi -0.08, rsi -0.06): weights chase short streaks that revert. Rows are autocorrelated, so this is suggestive only | ledger | M |
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
| F30 | The exclusion predicate covers every replay/eval path and the live resolver (via unit-mismatch rejection at `resolver.py:828,955`); the one uncovered writer is `/api/feedback` | grep of ~18 call sites | V |
| F31 | The exclusion is a ratio heuristic over a mixed-unit price feed (TAO vs USD per alpha), not a typed price | `grading.py:is_price_unit_mismatch` | V |
| F32 | `cold_cache_alert: true` (14%), 136 ungradeable, 50 `price_data_unavailable` | `/api/learning/stats` | V |

### 2.6 Security and operations
| # | Finding | Evidence | Status |
|---|---|---|---|
| F33 | `POST /api/feedback` is on the public-write allowlist, takes a client-supplied `correct_prediction`, and calls `nudge_expert`; no frontend caller (tests only) | `write_auth.py:22-27`, `learning_engine.py:57-90`, `routes.py:41` | V |
| F34 | `WRITE_API_TOKEN` **is** set in prod: an unauthenticated POST to an unknown path returns 401 `write_api_token_required`. Other write routes (`/api/learning/rebalance-weights`, `/api/learning/trigger`, `/api/scenario-memory`) are therefore token-protected | non-mutating probe | V |
| F35 | `/api/mindmap/feedback` is allowlisted but no route exists | grep | V |
| F36 | `CALIBRATION_AUTO_RETRAIN` is off in both fly tomls; capture grading mode is off in prod (trail `band`/`capture` null) | `fly.toml:87`, prod trail | V |
| F37 | The repo is public (GitHub API 200 unauthenticated), so F33 is publicly documented | API probe | V |
| F38 | Only 2 of 8 SQLite-using modules enable WAL (`fetchers/_sqlite.py`, `message_intel/models.py`); `chain_client.py` (5 sites) and `investigation/service.py` (3) connect directly. Web, inline worker and fetch child share one volume | grep | V |
| F39 | Tests rewrite six committed `data/*.json` files; 57 tracked files under `data/`, including `pump_desk/snapshots/*.json` | git | V |

### 2.7 Architecture
| # | Finding | Evidence | Status |
|---|---|---|---|
| F40 | 16 router imports are wrapped in `try/except`; none pull third-party-only dependencies, so a failure is always a bug and is currently silent | `server.py:35-171`, `requirements.txt` | V |
| F41 | `server.py` is a shared kernel: 3,467 lines, 104 functions, 32 routes, `_lifespan` 265 lines; **21 imports from other modules back into `server`** (8 of them `_get_subnets_with_source`) | grep | V |
| F42 | Prod serves `asgi_entry:app` (gzip + static-cache wrapper), while `AGENTS.md` and the contract test describe `server:app`; whether the contract test also covers the wrapper is unchecked | `scripts/run_web_with_guard.py`, `asgi_entry.py` | V (fact), U (coverage) |
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

### FX6 (RC6): single writer for learning state
- Only the batch estimator (FX2) writes weights. `LearningEngine.record_feedback` stops calling `nudge_expert`; `/api/feedback` becomes an append-only unverified-opinion log that is never an estimator input (or is removed).
- Remove the dead `/api/mindmap/feedback` allowlist entry.
- Acceptance: a test enumerates every callable that writes `soul_map` weights and asserts the set is `{estimator}`; an unauthenticated POST to `/api/feedback` leaves weights unchanged.

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
| Freezing weight updates | noise | **rejected**: it stops the symptom without fixing RC2 |

---

## 6. Jev / decision-model integration

Sources: Ditto memories (2026-09-26 evaluation, 2026-10-15 integration note); `decisionmodels.io` is reachable (HTTP 200) and describes itself as a Jev-compatible host separate from TypeSafe's Jev.
- Prior plan (kept): fix judge independence first; shadow forecaster, no write access; promote only on Brier skill over ~100 graded observations; **"Jev emits, code scores"**; rugger-flagged text never enters the state; route via a gateway that does not depend on one vendor's signup.
- Correction to that plan: it said judge weights "structurally cannot diverge." They have diverged (oracle 0.086 / echo 0.638 / pulse 0.276), though not toward skill.
- Sequencing: Jev enters at FX4, after FX1 (a market-relative target) and FX9 (point-in-time inputs). Before that it would be graded against the council, which reproduces the current defect.
- Unverified: API shape, rate limits, latency and current pricing (only the landing page was read), data-processing region.

---

## 7. Verification ledger

**Verified this session (code or live data):** F1, F3 (shadow definition), F6-F7, F9-F12, F14-F16, F18-F20, F23-F27, F29-F42 (see statuses above); write-auth is active in prod; capture mode off; calibration auto-retrain off; quarantine coverage of weight-update paths; red-team floor mechanics; adjuster caps.

**Measured, with stated limits:** F2, F4, F8, F17, F21, F25 (rows are autocorrelated and clustered: 34 netuids, 60 days, netuid 105 has 52 rows).

**Still unverified or unexplained (must not be treated as fact):**
1. Why live judge weights are oracle 0.086 / echo 0.638 / pulse 0.276. Not reproducible from the current ledger; earlier-epoch history is in the state.
2. Whether `/api/feedback` was ever abused. The last 100 trail events show no `reason=feedback` changes; older history is unavailable.
3. A market-wide baseline for a random long (the ledger does not store it; FX1 creates it).
4. Per-adjuster lift (memory/telegram/pump/recovery/tilts). Needs FX1 data and ablations.
5. Whether the contract test exercises `asgi_entry:app`.
6. Jev API shape, limits, latency, cost.
7. Prod secrets, machine state and logs (no flyctl/token in this environment); anything beyond `fly.toml` and public endpoints.
8. Statistical significance of F8's high-confidence drop (n=64) and F21 (autocorrelated rows).
9. Whether the 2026-08-09 "one-time rebalance" or earlier migrations produced the quant 2.0 value (pre-dates the ledger window).

---

## 8. Order of work (each item is a reviewable PR)

0. **FX6**: remove the weight write from `/api/feedback` and the dead allowlist entry (security; first, independent of the rest).
1. **FX10a**: unconditional router imports; drop the #1437 registry; keep its duplicate-CONTRACT and forbidden-import guards.
2. **FX9**: temp `DATA_DIR` in tests, stop tracking runtime state, one SQLite connection helper (WAL + busy_timeout).
3. **FX1 + FX8**: capture universe reference and typed prices going forward (data collection starts the clock on a clean evaluation window).
4. **FX2 + FX3**: deterministic weight function and per-expert grading, shadow-run beside the current weights.
5. **FX7**: typed audit and gate consumption.
6. **FX4 + FX5**: independent probability judges, calibrated publish probability, ablations.
7. **FX10b**: extract `server.py` kernel, lifespan, routes.
8. Jev as a shadow judge.
9. UI pass from the screenshots, retire `ui-legacy.css`.

Promotion rule for any model or weight change: out-of-time validation on the FX1 ledger; no promotion on in-sample results.

---

## 9. Reproduction

- Public read-only endpoints used: `/api/predictions/resolved`, `/api/learning/stats`, `/api/weights`, `/api/learning-metrics`, `/api/mindmap/trail`, `/api/learning/health`.
- Clean-row filter: `|actual_pct| <= 50` and `created_at` outside 2026-08-07..2026-08-18, population `council_published` / `council_shadow`; weights replay via `internal.council.weights.replay_weights_from_predictions` on a local copy of the ledger.
- No state-changing request was sent to prod; the write-auth probe used a nonexistent path.
