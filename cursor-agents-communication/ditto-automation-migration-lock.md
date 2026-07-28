# LOCK — Ditto automation migration (Phase 1)

**Status:** DONE (2026-07-28 — human confirmed Ditto playbook executed)  
**Plan:** `full-roadmap-master-plan.md` Phase 1  
**Branch:** `cursor/ditto-automation-playbook-4988` (docs only)

## Problem

- **Pump Desk Intelligence Snapshot** automation still HTTP-fetches pump data every ~15m — duplicates Fly worker (#547) and creates stale WARN memories.
- **Council Health Monitor** may still call `/api/council` + `/api/learning/stats` + `/api/subnets` in parallel → timeouts / wedge risk.
- Jul 27 `pump-desk-automation` WARN chain in Ditto is **obsolete** after worker-owned snapshots.

## DECISIONS

1. **DISABLE** Pump Desk fetch automation — worker owns `data/pump_desk/latest.json`.
2. **KEEP** three separate Ditto jobs: Daily Brief · Weekly Learning · Council Health Monitor.
3. Health Monitor reads **artifact first**: `learning_outcomes/latest.json` → fallback `GET /api/ops/evidence` (single bundle).
4. Ditto `save_memory` on: council `ALERT`, pick audit `MISS`, outcome `alert_level: alert`, WATCH escalation (optional weekly digest).
5. **Do not** merge automations into one mega-job.

## Automations (IDs for Ditto Settings)

| Job | UUID (prefix) | Action |
|-----|---------------|--------|
| Pump Desk Intelligence Snapshot | `8afd9502…` | **DISABLE** |
| Council Health Monitor | `9a3bbd01-e330-4f26-8bc8-eef919db009f` | **UPDATE** → artifact mode (see below) |
| Daily council brief | KEEP | unchanged |
| Weekly learning | KEEP | unchanged |

Canon detail: `docs/ditto-council-health-artifacts.md`

## Human runbook (Ditto Settings → Automations)

### Step 1 — Disable pump fetch (5 min)

1. Open Ditto → Automations → **Pump Desk Intelligence Snapshot** (`8afd9502…`).
2. Toggle **OFF** / disable schedule.
3. Confirm last run note: “superseded by Fly worker `pump_desk_snapshot` (#547)”.
4. `save_memory` (source: `ditto-handoff`):

   ```text
   Pump Desk Ditto fetch DISABLED 2026-07-28. Snapshots owned by Fly worker → data/pump_desk/latest.json. LOCK: ditto-automation-migration-lock.md
   ```

### Step 2 — Health Monitor → artifact mode (10 min)

Replace parallel API storm with:

**Primary (Fly volume or artifact URL if exposed):**

`data/learning_outcomes/latest.json` → fields: `council_health`, `alert_level`, `expert_weights`, `artifact_refs`

**Fallback (if `captured_at` older than 12h or file missing):**

```bash
curl -fsS --max-time 25 https://subnet-dashboard.fly.dev/api/ops/evidence
```

**Do not** call `/api/council`, `/api/learning/stats`, `/api/subnets` in parallel unless artifact missing.

**save_memory triggers** (append to automation prompt):

- `escalation: ALERT` or `alert_level: alert`
- `artifact_refs.pick_audit.verdict: MISS` (or `pick_audit` verdict MISS in evidence bundle)
- Optional: `escalation: WATCH` with `health_score < 70` once per day max

### Step 3 — Supersede stale memories

Mark superseded or reply with pointer to worker + lock (IDs from Jul 27 pump-desk-automation WARN chain):

- `7168a6c0`, `ebb292b8`, `a666d868`, `9ac990c8`, `e0738824`

New canonical STATUS memory should cite `main=3ddc7e9`, Phase 0 names done, Phase 1 playbook executed.

### Step 4 — Verify (same day)

```bash
# Evidence bundle (fallback path Health Monitor uses)
curl -fsS https://subnet-dashboard.fly.dev/api/ops/evidence | jq '{status, alerts, paths}'

# Learning health (spot-check, not Health Monitor primary)
curl -fsS https://subnet-dashboard.fly.dev/api/learning/health | jq '{status, daily_pick: .daily_pick.action}'

# Pump desk worker artifact path exists on volume (from ops evidence paths)
curl -fsS https://subnet-dashboard.fly.dev/api/ops/evidence | jq '.paths'
```

- [ ] Ditto automation history: **no** pump HTTP fetch after disable date
- [ ] Manual Health Monitor dry-run succeeds reading artifact or `/api/ops/evidence`
- [ ] Wed / Sun scheduled Health Monitor run succeeds (or documented skip)

## AC (Phase 1)

- [x] Pump Desk Ditto automation **disabled** (human 2026-07-28)
- [x] Health Monitor prompt updated to artifact-first
- [x] Stale pump-automation WARN memories superseded
- [x] Docs PR merged (#561)

## NON-GOALS

- Ditto implementing Python Fly workers
- Merging all automations into one job
- Changing app scoring or council logic

## Review Gate 1 — CLEARED (2026-07-28)

- [x] Ditto confirms playbook executed
- [x] Docs PR merged
- [x] No duplicate 15m pump fetches (human verified)
