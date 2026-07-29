# LOCK — Phase H: Track 1 soak review (monitor gate)

**Status:** MONITOR — checkpoint doc only (no product code)  
**Plan:** `post-audit-sprint-plan.md` Phase H  
**Baseline:** #551 calibration in prod; soak day 0 = 2026-07-28  
**Companion:** `track1-soak-lock.md` (ongoing criteria + queries)

## Purpose

Define **GO / HOLD / adjust** at the **day 7** (2026-08-04) and **day 14** (2026-08-11) review checkpoints for Track 1 publish gate, pick audit, council health, and telegram proof. Not a single deploy PR — human sign-off + Ditto + `board.md`.

## Review windows

| Checkpoint | When (UTC) | Action |
|------------|------------|--------|
| Day 7 | 2026-08-04 | First GO/HOLD decision |
| Day 14 | 2026-08-11 | Final sign-off or gate-adjustment PR |

## Checks (from plan)

| Check | Source | What to read |
|-------|--------|--------------|
| Daily pick publish rate | `data/daily_picks.json`, `GET /api/daily-pick` | LONG vs HOLD mix stable under #551 calibration; no integrity gate flap >1h |
| Pick audit PASS rate | `data/pick_audits/`, `./scripts/nightly_pick_audit.sh` | `verdict: PASS`; ≤1 consecutive MISS with fix before second |
| Council health trend | `data/learning_outcomes/latest.json`, Ditto Health Monitor | `council_health` / escalation stable or improving; WATCH allowed |
| Telegram proof trend | `meta.telegram_proof` in outcomes artifact | Improving or stable; no regressions vs soak start |

## Queries (copy-paste)

**One-shot snapshot (Slice 3):**

```bash
./scripts/soak_review_snapshot.sh | jq .
```

Manual queries:

```bash
BASE=https://subnet-dashboard.fly.dev

# Daily pick action + learning loop
curl -fsS "$BASE/api/learning/health" | jq '{
  status,
  daily_pick: .daily_pick.action,
  resolver: .resolver.running,
  worker: .worker_peer.alive
}'

curl -fsS "$BASE/api/daily-pick" | jq '{action, netuid, conviction, captured_at}'

# Ops evidence + council health + telegram proof
curl -fsS "$BASE/api/ops/evidence" | jq '{
  status,
  council_health: .artifacts.learning_outcomes.council_health,
  telegram_proof: .artifacts.learning_outcomes.meta.telegram_proof
}'

# Local audit (exit 0 = PASS, exit 2 = MISS)
./scripts/nightly_pick_audit.sh
```

## GO criteria (all must pass)

1. **Worker + integrity** — `worker_peer.alive: true`; `/health` 200 on 3 spaced probes; no deploy wedge >5 min in review window.
2. **Publish rate stable** — LONG vs HOLD mix consistent with #551 calibration; no unexplained flip-flop day-over-day.
3. **Pick audit** — PASS on ≥6 of last 7 nights; no MISS streak >1 without fix deployed within 24h.
4. **Artifacts fresh** — outcomes `captured_at` <12h; pump desk <30m when ladder active; pick audit file for each UTC day.
5. **Council health** — `escalation` not `ALERT`; WATCH (~33% accuracy) is **expected** and not a soak-fail.
6. **Telegram proof** — `meta.telegram_proof` trend flat or improving vs day 0 baseline.

**GO outcome:** Record in Ditto + update `board.md` Phase H row → proceed to Phase 3 SS-TG W1 (Review Gate 2) or continue parallel tracks per board queue.

## HOLD criteria (any triggers HOLD)

1. **Integrity gate failure** or homepage wedge >5 min without recovery.
2. **Audit MISS streak ≥2** without deployed fix.
3. **Outcomes artifact missing >24h** or pump desk stale >2h when worker alive.
4. **Publish rate unstable** — integrity gate flapping >1h/day or daily pick action oscillates without calibration change.
5. **Council health `escalation: ALERT`** without documented cause + fix plan.
6. **Telegram proof regressing** — material drop in proof coverage with no known infra cause.

**HOLD outcome:** Stop downstream phase queue items gated on soak; open fix slice or ops ticket; re-review in 48–72h. Document HOLD reason in Ditto + `board.md`.

## Adjust calibration gates (optional third outcome)

When checks are **borderline** (e.g. stable infra but LONG rate too low/high vs intent):

- Propose gate tweak PR referencing #551 calibration knobs.
- Do **not** merge accuracy/scoring experiments (Phase 4) under this checkpoint.
- Record: `adjust` + PR link in Ditto + `board.md`.

## Recording (required after each checkpoint)

Ditto `save_memory` (source: `cursor-agents-communication`):

```text
Phase H soak review day N — decision: GO|HOLD|adjust. publish: LONG|HOLD mix, audit: PASS rate X/7, council: WATCH|ok, telegram: stable|improving|regressing. main=<sha>. Next: day 14|gate PR|fix slice.
```

Update `board.md` Phase H row status + link this lock.

## AC (Phase H doc)

- [x] `track-1-soak-review-lock.md` merged
- [ ] Day 7 decision recorded (2026-08-04)
- [ ] Day 14 decision recorded (2026-08-11)

## Non-goals

- Product code changes in this phase
- Accuracy lift / scoring experiments (Phase 4 / P4)
- LLM nightly trade grader
