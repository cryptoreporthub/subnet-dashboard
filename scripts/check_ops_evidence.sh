#!/usr/bin/env bash
# Prod ops evidence probe — curls /api/ops/evidence (exit 2 on alert).
set -euo pipefail
BASE="${BASE_URL:-https://subnet-dashboard.fly.dev}"
json="$(curl -fsS --max-time 20 "${BASE}/api/ops/evidence")"
echo "$json" | python3 -m json.tool
status="$(echo "$json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','ok'))")"
if [[ "$status" == "alert" ]]; then
  exit 2
fi
