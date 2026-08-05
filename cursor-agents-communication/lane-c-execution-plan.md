# Lane C execution plan — post-#823 (Aug 5 2026)

**Status:** ACTIVE  
**main:** `876cbf6` (#823 dual-count trust banner merged)  
**Locks:** `accuracy-lift-lock.md` · `completion-runbook.md` · `model-guide.md`  
**Branch prefix:** `cursor/<slug>-5deb`  
**Cadence:** one PR → merge → babysit → Ditto STATUS → next

---

## Executive summary

| Phase | Work | Gate | Status |
|-------|------|------|--------|
| **0** | H2 soak sign-off + board refresh | Human GO | Snapshot done; sign pending |
| **1** | Dual-count trust banner | — | **DONE** #823 |
| **2** | Expert attribution fix + backfill | Phase 0 GO (soft) | **NEXT** |
| **3** | Slice 7a accuracy dashboard | Phase 2 merged | Queued |
| **4** | Slice 7b weight audit (read-only) | 7a snapshot in Ditto | Queued |
| **5** | Judge learning monitor | P0+P1 on main | Ongoing |
| **6** | Optional experiments | Human only | Parked |

**Product invariant (do not regress):** trust banner = published LONG picks only. Shadows, pump-desk claims, and ledger rows stay out of `trust_banner.ready`.

---

## Phase 0 — H2 GO sign-off (human + hygiene)

### Goal
Clear Lane C gate using **ledger** metrics, not trust `graded: 1`.

### Work (agent)

| Piece | Action |
|-------|--------|
| Soak snapshot | `./scripts/soak_review_snapshot.sh \| jq .` — save output to Ditto |
| Evidence curl | `curl -fsS $BASE/api/ops/evidence \| jq '.accuracy_lift, .combined_angles'` |
| Board | Refresh `board.md` STATUS (`main=876cbf6`, #820/#821/#823, Lane C active) |
| Ditto | `save_memory` STATUS + `update_memory` f93f7202 |

### GO criteria (recommend **GO** if all true)

- `accuracy_lift.graded_30d ≥ 20` (prod ~189)
- `worker_integrity.pass` and `learning_loop.pass` from soak script
- Pick audit PASS or documented waiver
- P0 (#820) + P1 (#821) judge learning merged and prod deltas non-zero

### HOLD criteria (fix before Phase 3+)

- Council health **ALERT** without waiver
- Learning loop worker dead / resolver stuck
- `accuracy_lift.data_available == false` on prod

### Explicit non-blocker

- `outcomes_captured_at` null on artifacts — track as ops follow-up; does **not** block measurement work on live ledger.

### Human deliverable

One Ditto line: `H2 GO Lane C — ledger 189/30d @ ~13.2%; trust published-only; proceed Phase 2–4`

---

## Phase 1 — Dual-count trust banner ✅

**Merged:** PR #823 (`876cbf6`)

- `internal/learning/trust_stats.py` — `ledger_graded_30d`, `ledger_hit_rate_30d`, `ledger_note`
- `internal/learning/routes.py` — inject from `build_accuracy_lift_snapshot()`
- `static/js/trust_banner_ui.js` — subline when published sample thin
- Tests: `tests/test_trust_banner_ledger_context.py`

**No further work** unless regression.

---

## Phase 2 — Expert attribution (P0 for analytics)

### Problem

`accuracy_lift.by_expert` is ~85% `unknown` because:

1. Resolve path uses `_normalize_expert(prediction)` only — fails when `expert` missing or `signal_source` is a desk label (`HOT`, `bullish`).
2. `expert_for_replay_row()` already exists (Slice R rebalance) but is **not** used at grade time or in `_expert()` fallback.
3. Historical resolved rows never backfilled.

### Design (single shared helper)

Add `internal/council/expert_attribution.py`:

```python
def attribute_expert_for_row(row: dict) -> str | None:
    """signal_impact → signal_source → pick expert_contributions → legacy normalize."""
```

Priority order (match `expert_for_replay_row` + `dominant_expert_for_learning`):

1. `expert_for_replay_row(row)` from `signal_expert.py`
2. If pick blob on row: `dominant_expert_for_learning(pick)`
3. `_normalize_expert(row)` last resort
4. Return `None` only when truly unresolvable (count separately)

### Work

| PR slice | Files | Notes |
|----------|-------|-------|
| **2a — forward fix** | `internal/council/expert_attribution.py` (new), `resolver.py` (`resolve_prediction*`), `prediction_loop.py` (stamp `experts_involved`) | Set `prediction["expert"]` + `expert_attribution_source` at resolve |
| **2b — measure fallback** | `internal/accuracy_lift/measure.py` `_expert()` | Call shared helper before `"unknown"` |
| **2c — backfill** | `internal/learning/expert_backfill.py`, `routes.py` `POST /api/learning/backfill-expert-attribution?dry_run=` | Idempotent; dry_run default true; requires `WRITE_API_TOKEN` or local |
| **2d — ops visibility** | `internal/ops/evidence.py` | Add `attribution_quality: {total_30d, unknown_30d, unknown_pct}` |
| **Tests** | `tests/test_expert_attribution.py`, extend `test_accuracy_lift_measure.py` | Fixture rows: HOT signal, signal_impact lead, legacy alpha/beta |

**Branch:** `cursor/expert-attribution-replay-5deb` (one PR if diff < ~250 lines; else 2a+2b then 2c)

### Acceptance criteria

- [ ] New resolves stamp canonical expert (`quant|hype|dark_horse|technical`) when signal_impact or mappable signal_source present
- [ ] `_expert()` fallback matches replay attribution for historical rows
- [ ] Backfill dry_run reports `would_update` / `still_unknown`; live run reduces prod `unknown_pct` below **20%** (target from ~85%)
- [ ] `accuracy_lift.by_expert` has ≥3 experts with `graded ≥ 5` after backfill on prod
- [ ] No change to trust banner graded count or shadow exclusion
- [ ] `pytest tests/test_expert_attribution.py tests/test_accuracy_lift_measure.py tests/test_endpoint_contract.py`

### Grok

**MECHANICAL** — skip new LOCK; build from this plan. Sonnet on diff before push.

### Non-goals

- Reweighting council from backfill (read-only attribution)
- Changing publish gate
- Including shadows in trust

---

## Phase 3 — Slice 7a accuracy measurement dashboard

### Goal
Human-scannable 7d/30d accuracy by expert on the learning desk / proof band — **read-only**, built on fixed attribution.

**Lock:** `accuracy-lift-lock.md` (PREP already on main via `build_accuracy_lift_snapshot`)

### Work

| Piece | Files |
|-------|-------|
| API (optional thin) | Reuse `GET /api/ops/evidence` → `accuracy_lift` OR add `GET /api/learning/accuracy-lift` alias on `learning_router` |
| UI panel | `templates/partials/premium_cockpit.html` or learning desk partial; `static/js/cockpit_hydrate.js` — `syncAccuracyLiftPanel()` |
| Empty state | Reuse `.desk-empty` when `data_available: false` |
| Contract | `tests/test_endpoint_contract.py` if new route |
| Visual tests | `tests/test_accuracy_lift_dashboard.py` — HTML markers + hydrate function |

**Branch:** `cursor/slice-7a-accuracy-dashboard-5deb`

### UI spec (minimal)

```
Accuracy lift (30d)
  Graded: 189 · Hit rate: 13.2%
  By expert: Quant 42 (18%) · Hype 31 (12%) · …
  Note: full ledger; trust uses published LONG only
```

- Show `unknown` bucket honestly if Phase 2 incomplete
- No charts library — text + optional horizontal bars in CSS

### Acceptance criteria

- [ ] Panel visible on homepage proof band or learning section @390px
- [ ] Binds `accuracy_lift` only — no weight writes
- [ ] Honest empty when `graded_30d == 0`
- [ ] Babysit + contract green

### Gate

Phase 2 merged + H2 GO logged in Ditto.

---

## Phase 4 — Slice 7b weight audit (read-only)

### Goal
Confirm online weight path matches ledger replay; document drift before any tune.

**Lock:** `accuracy-lift-lock.md` — no Combined 0.70/0.30 change in this PR.

### Work

| Piece | Files |
|-------|-------|
| Audit report builder | `internal/accuracy_lift/weight_audit.py` — compare `load_weights()` vs `replay_weights_from_predictions()` vs last rebalance trail |
| Ops evidence block | `internal/ops/evidence.py` → `weight_audit` |
| Soak script snippet | `scripts/soak_review_snapshot.sh` — print `weight_audit.ready` |
| Ditto snapshot | Save `by_expert` + `weight_audit` before any tune PR |
| Tests | `tests/test_weight_audit.py` |

**Branch:** `cursor/slice-7b-weight-audit-5deb`

### Acceptance criteria

- [ ] Report shows per-expert: live weight, replayed weight, delta, rows attributed
- [ ] Flags `|delta| > 0.05` as `review_recommended`
- [ ] Read-only — no `save_weights` in this slice
- [ ] Document soul_map path used (`data/soul_map.json` on volume)

### Gate

Phase 3 merged; `accuracy_lift.by_expert` usable (unknown_pct < 20%).

---

## Phase 5 — Judge learning monitor (ongoing)

P0 (#820 selective endorsement) + P1 (#821 magnitude nudges) merged. Close the observability loop.

### Work

| Piece | Files |
|-------|-------|
| Stats endpoint enrich | `GET /api/learning/stats` → `judge_learning: { deltas_7d, last_nudge_scale, replay_available }` |
| UI whisper | `static/js/trust_banner_ui.js` or judges panel — show last magnitude-scaled delta when non-trivial |
| Replay guard | Document `internal/judges/replay.py` usage in ops runbook |
| Tests | Extend `tests/test_judge_weights.py` |

**Branch:** `cursor/judge-learning-monitor-5deb` (after Phase 4 or parallel if no file conflict)

### Acceptance criteria

- [ ] Prod shows variable judge deltas (not always 0.005 flat)
- [ ] No regression to P0 selective grading tests
- [ ] Read-only replay endpoint or script documented

---

## Phase 6 — Optional (human approval only)

| Option | Branch | Gate | Risk |
|--------|--------|------|------|
| Combined weight tune 0.70/0.30 | `cursor/combined-weight-tune-5deb` | H2 GO + `combined_angles.graded ≥ 20` + 7b shows drift | Changes pump scoring |
| Publish gate 50%→40% (2 weeks) | env `DAILY_PICK_PUBLISH_GATE=0.40` | Explicit human "more published picks" | More LONGs, weaker gate story |
| Judge weights reset 0.35/0.30/0.35 | `cursor/judge-weights-reset-5deb` | Cosmetic after monitor stable | Trail noise |
| Shadow vs published hit-rate report | `scripts/shadow_vs_published_report.sh` | Analysis only | None |
| Tribunal #788 live wire | — | **PARKED** until explicit ask | Hero risk |

**Do not schedule Phase 6 items in the same PR as Phase 2–4.**

---

## PR queue (strict order)

```text
✅ PR-LC1  Phase 1 dual-count trust banner     (#823)
→ PR-LC2  Phase 2 expert attribution           (cursor/expert-attribution-replay-5deb)
→ PR-LC3  Phase 3 Slice 7a dashboard           (cursor/slice-7a-accuracy-dashboard-5deb)
→ PR-LC4  Phase 4 Slice 7b weight audit        (cursor/slice-7b-weight-audit-5deb)
→ PR-LC5  Phase 5 judge learning monitor     (cursor/judge-learning-monitor-5deb)
∥ PR-LC0  board.md + Ditto H2 GO               (anytime; human sign)
⏸ PR-LC6+ Optional experiments                 (human only)
```

---

## Verify commands (every merge)

```bash
source .venv/bin/activate
pytest -q tests/test_endpoint_contract.py
pytest -q tests/test_expert_attribution.py tests/test_accuracy_lift_measure.py  # after LC2
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh sprint
BASE=https://subnet-dashboard.fly.dev ./scripts/check_learning_loop.sh
./scripts/soak_review_snapshot.sh | jq '.checks, .accuracy_lift, .suggested_decision'
curl -fsS "$BASE/api/ops/evidence" | jq '.accuracy_lift, .attribution_quality, .weight_audit'
```

---

## Conflict surface

| File | Owner / rule |
|------|----------------|
| `internal/learning/routes.py` | Agent A — serialize PRs |
| `internal/council/resolver.py` | Agent A |
| `server.py` | Rebase if parallel PRs |
| `tests/test_endpoint_contract.py` | Add routes when added |
| `static/js/cockpit_hydrate.js` | Rebase with hero/UI PRs |

---

## Definition of done (Lane C core)

1. H2 GO recorded in Ditto with ledger rationale  
2. Phase 2: `unknown_pct < 20%` on prod `accuracy_lift`  
3. Phase 3: accuracy panel live and honest-empty safe  
4. Phase 4: weight audit in ops evidence + Ditto snapshot  
5. Phase 5: judge monitor visible  
6. `board.md` reflects completion; no shadow-in-trust regression  
7. Trust banner still `graded` = published LONG only at <30 sample

---

## Risks

| Risk | Mitigation |
|------|------------|
| Backfill writes wrong expert | `expert_attribution_source` field + dry_run first; spot-check 10 rows |
| 7a ships before 2 | Gate in plan; UI shows unknown bucket honestly |
| Weight tune temptation | 7b read-only + accuracy-lift-lock; separate PR12 |
| Thin published trust persists | Expected; ledger subline explains; don't "fix" with shadows |
