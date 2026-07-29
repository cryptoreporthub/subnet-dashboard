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
  exit 0
fi

echo "fly_probe_worker_from_web: web=$WEB_ID port=$PORT"
flyctl machine exec -a "$APP" "$WEB_ID" python scripts/probe_worker_peer_once.py || echo "WARN: exec probe failed"
