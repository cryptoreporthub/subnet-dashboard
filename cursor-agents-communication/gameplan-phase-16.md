# Phase §16 — Close the trust gap (outcomes + hybrid_score)

**Status:** DRAFT 2026-07-15 · awaiting Ditto/human final sign-off · **do not implement until approved**  
**After:** Phase N/O (#227 + #228) · Phase P (#232 + #237)  
**Binding prior:** `phase-n-o-step0-spec.md` · `phase-n-design.md` §6 · `n1-oracle-tuning-design.md` · `gameplan-phase-p.md`

## Why §16

N2 partially wired scenario outcomes; P3 left `grading.hybrid_score()` as a stub that always returns `None`. The trust gap is residual blanks + a placeholder score. §16 finishes the history, calibrates a real score **only when data supports it**, and re-measures win rate. Nothing else.

**One-liner:** Close the trust gap — fill blanks, calibrate honestly, report the real number.

## Explicitly out of scope

- New product features, alert channels, or Signal Hub work
- UI redesigns / cockpit layout changes (honest-empty string only if an existing surface already shows the score)
- Extra signals, new judges, threshold gaming, or reopening N1 grader redesign
- Custom domain DNS (still P4 / human)
- Changing Fly machine size or adding dependencies

## Slices (3, sequential)

| Slice | Owner | Scope | AC |
|-------|-------|-------|-----|
| **16.1** | A | Fill remaining outcome gaps in scenario-memory from resolved predictions | `outcomes_pending == 0` **or** every leftover row is listed as unresolvable with reason; idempotent backfill; one small test |
| **16.2** | A | Replace `hybrid_score()` stub with data-backed SciWeave Phase-2 formula, gated on sample size | Returns `float` only when `n ≥ min_sample`; else `None` + honest `"not enough data yet"` on status/API; no fake numbers |
| **16.3** | A | Re-run backtest / prod verify; record post-calibration win rate | Snapshot doc + `./scripts/verify_prod.sh`; compare to Phase P baseline (53.5% council/oracle) |

**Order is fixed:** 16.1 → 16.2 → 16.3. Do not calibrate on incomplete history.

## Agent assignment

| Agent | Role |
|-------|------|
| **A** (`-843d`) | Owns all three slices (`internal/learning/*`, `internal/council/grading.py`, analytics consume, docs) |
| **B** (`-e78a`) | Idle unless 16.3 surfaces a backtest UI empty-state string that needs a one-line template tweak |
| **Human / Ditto** | Final approve this gameplan; merge gate |

## Models

| Step | Model |
|------|-------|
| Approve / tighten formula edge cases | Grok slow + **medium** (escalate **high** only if medium unsatisfactory) |
| Implement 16.1–16.3 | Composer 2.5 |
| Pre-merge review of `hybrid_score` behavior | Grok slow + medium read-only |

---

## 16.1 — Fill the outcome gaps

**Intent:** Finish what N2 started. Every past pick that *can* be graded gets a right/wrong outcome stamped; nothing silently blank.

**Already on `main`:** `internal/learning/scenario_outcomes.py` (`backfill_scenario_outcomes_from_predictions`, `scenario_outcome_stats`), resolver `_record_scenario_outcome`, learning routes that trigger backfill.

**Remaining work (audit → fix → prove):**

1. **Inventory** — Call / inspect `scenario_outcome_stats()` on prod + local. Count `outcomes_pending`. Sample blank rows: missing `scenario_id`? missing `correct`/`outcome` on prediction? name/regime mismatch?
2. **Close link gaps** — Ensure new predictions still attach `scenario_id` on create (N2 AC). If historical rows lack ids, extend backfill matching (name + netuid + time window) **once** — no new store format.
3. **One-shot backfill** — Re-run idempotent backfill; document unresolvable leftovers (e.g. expired/ungradeable) rather than inventing outcomes.
4. **Guard** — `GET /api/learning/stats` (or existing scenario stats path) reports `outcomes_pending` and optionally `unresolvable_count`.

**Files (expected):**
- `internal/learning/scenario_outcomes.py` (extend match / unresolvable reporting)
- `tests/test_scenario_memory.py` (assert zero pending after fixture backfill; unresolvable path)
- Touch `internal/council/scenario_memory.py` / `prediction_loop.py` **only** if create-path still drops `scenario_id`

**Done when:** Pending blanks that have a resolvable prediction are filled; leftovers are explicit, not silent `—`.

---

## 16.2 — Real `hybrid_score` (data-gated)

**Intent:** Replace the Phase P stub with a calibrated score. If history is too thin, return honest empty — never a decorative float.

**Current stub:** `internal/council/grading.py` → `hybrid_score(...) -> None` always.

**Formula (SciWeave Phase 2, already named in `phase-n-design.md` §6):**

```
hybrid = 0.4 × direction_score + 0.6 × magnitude_calibration
```

| Term | Definition |
|------|------------|
| `direction_score` | `1.0` if `direction_correct(prediction, actual_pct)` else `0.0` |
| `magnitude_calibration` | Error vs predicted move, mapped to `[0, 1]` (e.g. `1 - min(1, abs(predicted_pct - actual_pct) / scale)`). Lock exact `scale` in implementation notes; prefer existing backtest binning constants if present. |
| **Gate** | Require `n ≥ min_sample` **resolved, gradeable** rows usable for magnitude (reuse `MIN_RESOLVED_SAMPLE = 30` from `internal/calibration/pipeline.py` unless Grok medium kickoff picks another constant and records it here). Below gate → return `None`. |

**Honest-empty contract:**
- Function returns `Optional[float]` — `None` means “not enough data yet” (or magnitude still not usable), **not** zero.
- Any API/status field that exposes the score must pair `hybrid_score: null` with a stable reason string, e.g. `"not_enough_data"` / human text `"not enough data yet"`.
- Do **not** invent magnitude from confidence alone in a way that pretends signal-derived precision. If a row’s `predicted_pct` is still the confidence-proxy path (`_predicted_pct_from_pick`), either exclude it from the magnitude sample or document that §16 calibrates only direction + coarse magnitude error on stored `predicted_pct`/`actual_pct` pairs — pick one in the Grok medium note before coding, default: **use stored pairs but gate on n; do not add new magnitude sources** (out of scope).

**Wire points (minimal):**
- Implement body of `hybrid_score()` in `grading.py`
- Optional thin helper for sample-size / reason (same module or `internal/learning/`)
- Consumers: prefer existing calibration/backtest/learning status JSON — **no new routes** unless an existing endpoint already promises a score field
- UI: only if a current template already renders hybrid/magnitude; then show the honest string. No redesign.

**Files (expected):**
- `internal/council/grading.py`
- `tests/test_phase_j_*` or new small `tests/test_hybrid_score.py` (enough data → float in range; below gate → `None`)
- Docs: one paragraph in this gameplan “Implementation notes” after merge

**Done when:** Stub gone; gated behavior covered by one runnable test; no fake scores below threshold.

---

## 16.3 — Re-measure performance

**Intent:** After 16.1–16.2, report the **real** win rate — same harness as Phase P, not a new dashboard.

**Steps:**
1. Run existing `GET /api/backtest` (and/or local backtest helper) on prod after deploy.
2. Run `./scripts/verify_prod.sh`.
3. Write/update snapshot under `docs/` (e.g. `docs/phase-16-trust-gap-snapshot.md`) with:
   - council / oracle / echo / pulse win-rates
   - sample size
   - whether `hybrid_score` is live or still gated (`not enough data yet`)
   - delta vs Phase P baseline (`docs/phase-p-prod-snapshot.md`: council/oracle **53.5%**)
4. Board/STATUS one-line: §16 COMPLETE + key metric (or “hybrid gated — not enough data”).

**No new analytics engine.** Reuse N4 backtest.

**Done when:** Snapshot committed; board/STATUS reflect measured reality (including honest gate).

---

## Non-negotiables

- Honest-empty > decorative summaries > 500s
- No threshold gaming / no cherry-picked windows for the win-rate report
- No `data/*.json` churn in commits
- No revert of #221/#223/#224/#225/#226/#227/#228/#232/#234/#237 or Step 0 spec
- Single foundation: `server:app` only

## Acceptance (phase-level)

| # | Check |
|---|--------|
| 1 | 16.1: pending resolvable outcomes cleared or explicitly unresolvable |
| 2 | 16.2: `hybrid_score` returns float iff gate met; else `None` + honest reason |
| 3 | 16.3: prod/backtest snapshot recorded vs P baseline |
| 4 | `pytest` green for touched tests; contract test unchanged unless a field was already contracted |
| 5 | Diff stays inside learning/council grading + thin docs — no UI redesign PR |

## After §16

Agents idle / monitor (`./scripts/verify_prod.sh`). Next roadmap slice only if Ditto defines one — §16 is **not** a platform for new features.
