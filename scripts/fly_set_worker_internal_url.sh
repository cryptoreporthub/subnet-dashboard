#!/usr/bin/env bash
# split_v2 web → worker: pin the worker machine's 6PN private IP.
# Flycast :8081 is intermittent after restarts; process DNS returns connection refused.
# Re-run on every deploy so the IP stays fresh when the worker machine is replaced.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
PORT="${WORKER_HTTP_PORT:-8081}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! "$SCRIPT_DIR/fly_worker_split_v2_guard.sh"; then
  echo "fly_set_worker_internal_url: split_v2 not enabled — unset legacy WORKER_INTERNAL_URL"
  flyctl secrets unset WORKER_INTERNAL_URL --app "$APP" 2>/dev/null || true
  exit 0
fi

WORKER_IP="$(flyctl machines list -a "$APP" --json | python3 -c "
import json, sys
for m in json.load(sys.stdin):
    meta = (m.get('config') or {}).get('metadata') or {}
    pg = (meta.get('fly_process_group') or m.get('process_group') or '').lower()
    if pg != 'worker':
        continue
    ip = (m.get('private_ip') or '').strip()
    if ip:
        print(ip)
        break
")"

if [ -z "${WORKER_IP}" ]; then
  echo "fly_set_worker_internal_url: no worker private_ip — fallback flycast :${PORT}"
  TARGET="http://${APP}.flycast:${PORT}"
else
  # IPv6 literal needs brackets in the URL.
  case "$WORKER_IP" in
    *:*) TARGET="http://[${WORKER_IP}]:${PORT}" ;;
    *)   TARGET="http://${WORKER_IP}:${PORT}" ;;
  esac
fi

echo "fly_set_worker_internal_url: set WORKER_INTERNAL_URL=${TARGET}"
flyctl secrets set "WORKER_INTERNAL_URL=${TARGET}" --app "$APP"
