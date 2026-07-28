# Ditto Council Health Monitor — artifact mode

Council Health Monitor (`9a3bbd01-e330-4f26-8bc8-eef919db009f`) must **not** storm `/api/council` + `/api/learning/stats` + `/api/subnets` in parallel. Use artifacts first.

**Lock:** `cursor-agents-communication/ditto-automation-migration-lock.md`

## Primary read

`data/learning_outcomes/latest.json` on Fly volume (`/app/data/learning_outcomes/latest.json`)

```json
{
  "captured_at": "2026-07-28T04:50:00Z",
  "alert_level": "ok|warn|alert",
  "council_health": {
    "health_score": 67,
    "escalation": "WATCH",
    "escalation_reasons": ["directional_accuracy_below_threshold"],
    "directional_accuracy": 0.33,
    "graded": 468,
    "correct": 154,
    "wrong": 314
  },
  "expert_weights": { "quant": 1.29 },
  "resolver_stats": { },
  "artifact_refs": {
    "pick_audit": { "verdict": "PASS", "path": "data/pick_audits/2026-07-28.json" },
    "pump_desk": { "alert_level": "ok", "path": "data/pump_desk/latest.json" }
  }
}
```

**Stale rule:** if `captured_at` is older than **12 hours**, treat artifact as stale and use fallback.

## Fallback (single HTTP call)

```bash
curl -fsS --max-time 25 https://subnet-dashboard.fly.dev/api/ops/evidence
```

Example fields:

```json
{
  "status": "ok|warn|alert",
  "checked_at": "...",
  "alerts": ["pick_audit MISS category=..."],
  "paths": {
    "pick_audit": "data/pick_audits/2026-07-28.json",
    "pump_desk": "data/pump_desk/latest.json",
    "learning_outcomes": "data/learning_outcomes/latest.json"
  },
  "artifacts": {
    "learning_outcomes": { "council_health": { "escalation": "WATCH" } }
  }
}
```

## Do not

- Re-score daily picks or change council weights from Ditto
- Call `/api/council` + `/api/learning/stats` + `/api/subnets` in parallel unless both artifacts are missing
- Run **Pump Desk Intelligence Snapshot** (`8afd9502…`) — **DISABLED**; Fly worker owns `data/pump_desk/latest.json`

## save_memory triggers

Post short STATUS when automation reads:

| Condition | Action |
|-----------|--------|
| `escalation: ALERT` or `alert_level: alert` | `save_memory` ALERT + link lock |
| `artifact_refs.pick_audit.verdict: MISS` | `save_memory` audit MISS |
| `escalation: WATCH` | optional once/day digest (not every run) |

## Automations to keep (3 jobs)

1. Daily council brief  
2. Weekly learning  
3. Council Health Monitor (this doc)

## Verify after prompt update

```bash
curl -fsS https://subnet-dashboard.fly.dev/api/ops/evidence | jq '{status, alerts, paths}'
```

Manual dry-run in Ditto → confirm run completes without timeout.
