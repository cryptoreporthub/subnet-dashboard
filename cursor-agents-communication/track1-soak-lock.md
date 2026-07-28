# LOCK — Track 1 soak criteria (Phase 2)

**Status:** ACTIVE — monitor only (no product code)  
**Plan:** `full-roadmap-master-plan.md` Phase 2  
**Baseline main:** `3ddc7e9` (#554 Phase 0, #560 SN23, #551 calibration)

## Purpose

Define pass/fail for **Track 1 publish gate** + ops evidence loop while Council Health stays in **WATCH** (~33% directional accuracy). Outcome harness **reports**; soak **does not** fix accuracy (Phase 4).

## Scope

| In | Out |
|----|-----|
| Publish rate stability under #551 calibration | Scoring / weight experiments |
| Pick audit PASS/MISS streak | LLM trade grader |
| Artifact freshness (audit, pump, outcomes) | Ditto automation code |
| Integrity gates (no wedge, worker alive) | Accuracy lift (Phase 4) |

## Checkpoints

| Checkpoint | When | Pass |
|------------|------|------|
| Pick audit | Nightly **23:45 UTC** | `verdict: PASS` or single MISS with fix deployed within 24h |
| Outcome snapshot | Every **6h** + **04:50 UTC** | `data/learning_outcomes/latest.json` `captured_at` &lt; 12h |
| Pump desk snapshot | Worker ~15m | `data/pump_desk/latest.json` fresh; Ditto fetch **disabled** |
| Council Health | Wed / Sun **05:00 UTC** | Ditto auto-run OK (artifact mode) or manual dry-run logged |
| Publish rate | **Day 7** | LONG vs HOLD stable; no integrity gate flap &gt; 1h |
| Publish rate | **Day 14** | Human sign-off or gate-adjustment PR |

**Soak start:** 2026-07-28 (Phase 0 deploy)  
**Day 7 review:** 2026-08-04 UTC  
**Day 14 review:** 2026-08-11 UTC

## Queries (copy-paste)

```bash
BASE=https://subnet-dashboard.fly.dev

# Ops evidence bundle
curl -fsS "$BASE/api/ops/evidence" | jq '{status, alerts, paths, checked_at}'

# Learning loop + daily pick action
curl -fsS "$BASE/api/learning/health" | jq '{
  status,
  daily_pick: .daily_pick.action,
  resolver: .resolver.running,
  worker: .worker_peer.alive
}'

# Council health from outcomes artifact (via evidence API paths on volume)
curl -fsS "$BASE/api/ops/evidence" | jq '.artifacts.learning_outcomes.council_health // .outcomes // empty'

# Nightly audit (after 23:45 UTC)
# On volume: data/pick_audits/YYYY-MM-DD.json → verdict PASS|MISS
```

Local / CI audit:

```bash
./scripts/nightly_pick_audit.sh
# exit 0 = PASS, exit 2 = MISS
```

## Pass criteria (Track 1)

### Must pass (all 14 days)

1. **Worker alive** — `worker_peer.alive: true` on sustained probes (3× `/api/learning/health`).
2. **No audit MISS streak** — ≤1 consecutive MISS; fix deployed before second MISS.
3. **Artifacts fresh** — outcomes + pump desk `captured_at` within SLA (12h outcomes, 30m pump when ladder active).
4. **No deploy wedge** — `/health` 200 on 3 spaced probes after each merge.
5. **Pick audit runs** — `data/pick_audits/` file for each UTC day after 23:45 job.

### WATCH allowed (not soak-fail)

- Council Health `escalation: WATCH` (~67 score, ~33% accuracy) — **expected** until Phase 4.
- `status: degraded` when resolver tick stale &lt; 2× refresh interval — recovers on tick.
- Single pump `alert_level: warn` on ladder — evidence only.

### Soak-fail (escalate)

- `integrity_gate` failure or homepage wedge &gt; 5 min
- Audit MISS **2+ nights** without fix
- Outcomes artifact missing &gt; 24h
- Ditto pump fetch still running (duplicate worker)
- `escalation: ALERT` without documented cause + fix plan

## Recording

After each weekly checkpoint, Ditto `save_memory` (source: `cursor-agents-communication`):

```text
Track 1 soak day N — publish: LONG|HOLD mix, audit: PASS|MISS, evidence: ok|warn|alert, integrity: ok. main=<sha>. Next: day 7|14 review.
```

## AC (Phase 2 doc)

- [x] `track1-soak-lock.md` merged
- [ ] Day 7 human sign-off (2026-08-04)
- [ ] Day 14 human sign-off (2026-08-11)

## Review Gate 2 (before Phase 3 SS-TG W1)

- [ ] ≥7 days soak data in Ditto
- [ ] No integrity gate failures
- [ ] Pick audit MISS streak ≤1
- [ ] This lock merged + checkpoints recorded
