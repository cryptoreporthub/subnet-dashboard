#!/usr/bin/env bash
# FP7: read worker-side APScheduler job inventory (GET /jobs on WORKER_HTTP_PORT).
# Requires #1116 deployed (worker listens on 8081). Read-only.
set -euo pipefail
APP="${FLY_APP:-subnet-dashboard}"
PORT="${WORKER_HTTP_PORT:-8081}"

echo "== resolving probe machine (worker when split v2, else web) =="
WORKER_ID="$(flyctl machines list -a "$APP" --json | jq -r '[.[] | select(((.process_group // .config.process_group // "") | ascii_downcase) == "worker" and (.state == "running" or .state == "started"))][0].id // empty')"
if [ -n "${WORKER_ID:-}" ] && [ "$WORKER_ID" != "null" ]; then
  TARGET_ID="$WORKER_ID"
  echo "split v2 — probing worker machine"
else
  TARGET_ID="$(flyctl machines list -a "$APP" --json | jq -r '[.[] | select(((.process_group // .config.process_group // "web") == "web" and .state == "running"))][0].id // empty')"
  if [ -z "${TARGET_ID:-}" ] || [ "$TARGET_ID" = "null" ]; then
    TARGET_ID="$(flyctl machines list -a "$APP" --json | jq -r '.[0].id')"
  fi
  echo "v1 inline — probing web machine"
fi
echo "probe machine=$TARGET_ID port=$PORT"

STATE="$(flyctl machine status "$TARGET_ID" -a "$APP" --json 2>/dev/null | jq -r '.state // empty')"
echo "machine state=$STATE"
if [ "$STATE" != "running" ] && [ "$STATE" != "started" ] && [ -n "$STATE" ]; then
  echo "machine not running (state=$STATE); starting..."
  flyctl machine start "$TARGET_ID" --app "$APP" || true
  sleep 20
fi

echo "== /jobs inventory =="
flyctl machine exec "$TARGET_ID" "curl -fsS --max-time 20 http://127.0.0.1:${PORT}/jobs | python3 -m json.tool" --app "$APP" --timeout 60 || {
  echo "FAILED: /jobs not reachable on ${PORT} (is #1116 deployed?)"
  exit 1
}
