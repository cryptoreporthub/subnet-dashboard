#!/usr/bin/env bash
# Track 1 soak day 7/14 review snapshot — one command for human GO/HOLD checklist.
# See cursor-agents-communication/track-1-soak-review-lock.md
set -euo pipefail
cd "$(dirname "$0")/.."

BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

health_ok=0
health_codes=""
for i in 1 2 3; do
  code=$(curl -sS -m 8 -o /dev/null -w "%{http_code}" "$BASE/health" 2>/dev/null || echo "000")
  health_codes="${health_codes}${code} "
  if [[ "$code" == "200" ]]; then
    health_ok=$((health_ok + 1))
  fi
  sleep 2
done

learning_json=$(curl -fsS -m 12 "$BASE/api/learning/health" 2>/dev/null || echo '{}')
daily_pick_json=$(curl -fsS -m 12 "$BASE/api/daily-pick" 2>/dev/null || echo '{}')
evidence_json=$(curl -fsS -m 12 "$BASE/api/ops/evidence" 2>/dev/null || echo '{}')

audit_exit=0
audit_json='{}'
if audit_out=$(./scripts/nightly_pick_audit.sh 2>/dev/null); then
  audit_json="$audit_out"
else
  audit_exit=$?
  audit_json=$(echo "$audit_out" | tail -1 || echo '{"verdict":"ERROR"}')
fi

export BASE TS health_ok health_codes learning_json daily_pick_json evidence_json audit_exit audit_json
python3 - <<'PY'
import json
import os

def loads(s):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}

learning = loads(os.environ.get("learning_json"))
daily = loads(os.environ.get("daily_pick_json"))
evidence = loads(os.environ.get("evidence_json"))
audit = loads(os.environ.get("audit_json"))
health_ok = int(os.environ.get("health_ok", "0"))
audit_exit = int(os.environ.get("audit_exit", "0"))

worker_alive = bool((learning.get("worker_peer") or {}).get("alive"))
resolver_on = bool((learning.get("resolver") or {}).get("running"))
learning_status = learning.get("status")

outcomes = (evidence.get("artifacts") or {}).get("learning_outcomes") or {}
council = outcomes.get("council_health") or {}
telegram = (outcomes.get("meta") or {}).get("telegram_proof")
outcomes_captured = outcomes.get("captured_at")

checks = {
    "worker_integrity": {
        "pass": worker_alive and health_ok >= 2,
        "worker_peer_alive": worker_alive,
        "health_probes_ok": health_ok,
        "health_probe_codes": os.environ.get("health_codes", "").strip(),
    },
    "learning_loop": {
        "pass": learning_status in ("ok", "degraded") and worker_alive,
        "status": learning_status,
        "resolver_running": resolver_on,
        "daily_pick_action": (learning.get("daily_pick") or {}).get("action")
            or daily.get("action"),
    },
    "pick_audit": {
        "pass": audit_exit == 0 and audit.get("verdict") == "PASS",
        "exit_code": audit_exit,
        "verdict": audit.get("verdict"),
        "category": audit.get("category"),
        "path": audit.get("path"),
    },
    "council_health": {
        "pass": council.get("escalation") != "ALERT",
        "escalation": council.get("escalation"),
        "accuracy_watch_expected": council.get("escalation") == "WATCH",
    },
    "artifacts": {
        "pass": bool(outcomes_captured),
        "outcomes_captured_at": outcomes_captured,
        "evidence_status": evidence.get("status"),
    },
    "telegram_proof": {
        "present": telegram is not None,
        "value": telegram,
    },
    "combined_angles": {
        "pass": True,
        "present": bool(evidence.get("combined_angles")),
        "graded_predictions": (evidence.get("combined_angles") or {}).get("gates", {}).get(
            "graded_predictions"
        ),
        "ledger_calls": ((evidence.get("combined_angles") or {}).get("ledger") or {}).get("calls"),
    },
}

all_auto = all(
    checks[k]["pass"]
    for k in ("worker_integrity", "learning_loop", "pick_audit", "council_health", "artifacts")
)
suggested = "GO" if all_auto else "HOLD"

print(
    json.dumps(
        {
            "snapshot_at": os.environ.get("TS"),
            "base": os.environ.get("BASE"),
            "suggested_decision": suggested,
            "note": "suggested_decision is automated hint only — human signs GO/HOLD per lock",
            "checks": checks,
            "raw": {
                "learning_health": learning,
                "daily_pick": daily,
                "ops_evidence_summary": {
                    "status": evidence.get("status"),
                    "council_health": council,
                    "telegram_proof": telegram,
                },
            },
        },
        indent=2,
    )
)
PY
