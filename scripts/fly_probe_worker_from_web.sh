#!/usr/bin/env bash
# Probe worker peer from web machine via fly machine exec (GHA diagnostic).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
PORT="${WORKER_HTTP_PORT:-8081}"

WEB_ID="$(flyctl machines list -a "$APP" --json | python3 -c "
import json, sys
for m in json.load(sys.stdin):
    meta = (m.get('config') or {}).get('metadata') or {}
    pg = (meta.get('fly_process_group') or m.get('process_group') or 'web').lower()
    if pg == 'web' and m.get('id'):
        print(m['id'])
        break
")"

if [ -z "$WEB_ID" ]; then
  echo "fly_probe_worker_from_web: no web machine"
  exit 1
fi

echo "fly_probe_worker_from_web: web=$WEB_ID port=$PORT"

probe_out="$(mktemp)"
trap 'rm -f "$probe_out"' EXIT

set +e
flyctl machine exec -a "$APP" "$WEB_ID" --timeout 30 \
  "python /app/scripts/probe_worker_peer_once.py" > "$probe_out" 2>&1
exec_rc=$?
set -e
cat "$probe_out"

if [ "$exec_rc" -ne 0 ]; then
  if grep -qi 'lease currently held' "$probe_out"; then
    echo "fly_probe_worker_from_web: machine lease conflict (concurrent flyctl)"
  else
    echo "fly_probe_worker_from_web: flyctl machine exec failed (rc=$exec_rc)"
  fi
  exit 1
fi

# Stage 2 gate: flycast is the proven hop — require both health + worker-peer OK.
if ! grep -qE "OK 200 http://${APP}\\.flycast:${PORT}/health" "$probe_out"; then
  echo "fly_probe_worker_from_web: flycast /health not OK 200"
  exit 1
fi
if ! grep -qE "OK 200 http://${APP}\\.flycast:${PORT}/api/ops/worker-peer" "$probe_out"; then
  echo "fly_probe_worker_from_web: flycast /api/ops/worker-peer not OK 200"
  exit 1
fi
