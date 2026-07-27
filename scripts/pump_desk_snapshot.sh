#!/usr/bin/env bash
# Pump desk intelligence snapshot — ops probe (exit 2 on alert_level=alert).
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

from internal.pump.desk_snapshot import run_snapshot, exit_code_for_level

payload = run_snapshot(save=True)
print(
    json.dumps(
        {
            "path": payload.get("path"),
            "alert_level": payload.get("alert_level"),
            "alert_reasons": payload.get("alert_reasons"),
        },
        indent=2,
    )
)
sys.exit(exit_code_for_level(str(payload.get("alert_level") or "ok")))
PY
