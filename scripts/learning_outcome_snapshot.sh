#!/usr/bin/env bash
# Learning outcome snapshot — council health + accuracy (exit 2 on alert_level=alert).
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
python - <<'PY'
import json
import sys

from internal.learning.outcome_snapshot import run_snapshot, exit_code_for_level

payload = run_snapshot(save=True)
council = payload.get("council_health") or {}
print(
    json.dumps(
        {
            "path": payload.get("path"),
            "alert_level": payload.get("alert_level"),
            "health_score": council.get("health_score"),
            "escalation": council.get("escalation"),
        },
        indent=2,
    )
)
sys.exit(exit_code_for_level(str(payload.get("alert_level") or "ok")))
PY
