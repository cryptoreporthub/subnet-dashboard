# Ditto Council Health Monitor — artifact mode

After PR outcome snapshot deploy, Council Health Monitor (`9a3bbd01-e330-4f26-8bc8-eef919db009f`) should prefer volume JSON:

## Primary read

`data/learning_outcomes/latest.json` on Fly volume (`/app/data/learning_outcomes/latest.json`)

```json
{
  "captured_at": "...",
  "alert_level": "ok|warn|alert",
  "council_health": {
    "health_score": 67,
    "escalation": "WATCH",
    "escalation_reasons": [...],
    "directional_accuracy": 0.33,
    "graded": 468,
    "correct": 154,
    "wrong": 314
  },
  "expert_weights": { "quant": 1.29, ... },
  "resolver_stats": { ... },
  "artifact_refs": { "pick_audit": ..., "pump_desk": ... }
}
```

## Fallback (if artifact stale > 12h)

`GET https://subnet-dashboard.fly.dev/api/ops/evidence` — single bundle, no 3-endpoint storm.

## Do not

- Re-score daily picks
- Call `/api/council` + `/api/learning/stats` + `/api/subnets` in parallel unless artifact missing

## save_memory triggers

- `escalation: ALERT` or `alert_level: alert`
- `artifact_refs.pick_audit.verdict: MISS`
