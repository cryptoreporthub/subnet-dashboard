# Accuracy lift — measure-only PREP (LOCK B)

**Status:** PREP (read-only)  
**Branch:** `cursor/accuracy-lift-prep-ece3`  
**Gate:** Track 1 soak day 7 — **2026-08-04** (H2)

## NOW (this branch)

- Read-only **7d / 30d** direction accuracy from graded resolved rows
- `accuracy_lift` block on `GET /api/ops/evidence`
- Shared helper: `internal/accuracy_lift/measure.py` (script + evidence)
- `scripts/soak_review_snapshot.sh` prints jq-friendly `accuracy_lift` snippet

**NON-GOALS (this branch):** weight writes, Combined tune, Acc-2 knobs, dashboard redesign.

## DEFER → Aug 4 light revisit

| Item | Slice | Notes |
|------|-------|-------|
| Weight audit (online path only) | 7b | Confirm soul_map path; no archive replay in prod |
| Combined **0.70 / 0.30** tune | PR12 | Only if soak **GO** and `graded_n ≥ 20` |
| Capped scoring experiments | 7c | One hypothesis per PR; pytest proof |
| Acc-2 knob picks | post-Acc-1 | Human reads `acc1-report.md` recommendations |

Do **not** change Combined weights or mutate `soul_map` expert weights before H2 GO unless human says “tune now” with `graded_n ≥ 20`.

## AUG4_REVISIT checklist

- [ ] `./scripts/soak_review_snapshot.sh | jq .checks` — all auto checks pass or documented HOLD reasons
- [ ] `GET /api/ops/evidence` → `accuracy_lift.data_available` and `graded_30d` reviewed
- [ ] `graded_30d ≥ 20` before any Combined weight experiment
- [ ] Council health escalation not **ALERT** (or explicit waiver)
- [ ] Pick audit PASS streak documented
- [ ] 30d trend + `by_expert` snapshot saved to Ditto before Slice 7b/7c
- [ ] Human sign-off: **GO** / **HOLD** / **Tune Combined** (see `pre-aug4-polish-plan.md` Wave 3)

## Verify

```bash
curl -fsS "$BASE/api/ops/evidence" | jq '.accuracy_lift'
./scripts/soak_review_snapshot.sh | jq '.checks.accuracy_lift'
pytest -q tests/test_accuracy_lift_measure.py tests/test_endpoint_contract.py -k evidence
```
