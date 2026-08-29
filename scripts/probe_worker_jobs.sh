#!/usr/bin/env bash
# FP7: read worker-side APScheduler job inventory (GET /jobs on WORKER_HTTP_PORT).
# Requires #1116 deployed (worker listens on 8081). Read-only.
# v2: robust against flyctl non-JSON status output; tolerates machine state noise.
set -uo pipefail
APP="${FLY_APP:-subnet-dashboard}"
PORT="${WORKER_HTTP_PORT:-8081}"

echo "== resolving probe machine (worker when split v2, else web) =="
WORKER_ID="$(flyctl machines list -a "$APP" --json 2>/dev/null | jq -r '[.[] | select(((.process_group // .config.process_group // "") | ascii_downcase) == "worker" and (.state == "running" or .state == "started"))][0].id // empty' 2>/dev/null || true)"
if [ -n "${WORKER_ID:-}" ] && [ "$WORKER_ID" != "null" ]; then
  TARGET_ID="$WORKER_ID"
  echo "split v2 - probing worker machine"
else
  TARGET_ID="$(flyctl machines list -a "$APP" --json 2>/dev/null | jq -r '[.[] | select(((.process_group // .config.process_group // "web") == "web") and (.state == "running" or .state == "started"))][0].id // empty' 2>/dev/null || true)"
  if [ -z "${TARGET_ID:-}" ] || [ "$TARGET_ID" = "null" ]; then
    TARGET_ID="$(flyctl machines list -a "$APP" --json 2>/dev/null | jq -r '.[0].id // empty' 2>/dev/null || true)"
  fi
  echo "v1 inline - probing web machine"
fi
if [ -z "${TARGET_ID:-}" ] || [ "$TARGET_ID" = "null" ]; then
  echo "FAILED: could not resolve probe machine"
  exit 1
fi
echo "probe machine=$TARGET_ID port=$PORT"

# Machine state check is best-effort only (flyctl status output may be non-JSON).
STATE="$(flyctl machine status "$TARGET_ID" -a "$APP" --json 2>/dev/null | jq -r '.state // empty' 2>/dev/null || true)"
echo "machine state=${STATE:-unknown}"

echo "== /jobs inventory =="
OUT="$(flyctl machine exec "$TARGET_ID" "curl -sS --max-time 20 -w '\nHTTP_CODE=%{http_code}' http://127.0.0.1:${PORT}/jobs" --app "$APP" --timeout 60 2>&1 || true)"
echo "$OUT" | head -c 12000
echo ""