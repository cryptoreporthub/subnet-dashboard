#!/usr/bin/env bash
# Best-effort: probe worker peer from web machine via fly machine exec (GHA diagnostics).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"

WEB_ID="$(flyctl machines list -a "$APP" --json | python3 -c "
import json, sys
for m in json.load(sys.stdin):
    meta = (m.get('config') or {}).get('metadata') or {}
    pg = (meta.get('fly_process_group') or m.get('process_group') or 'web').lower()
    if pg == 'web' and m.get('id'):
        print(m['id'])
        break
")"

WORKER_ID="$(flyctl machines list -a "$APP" --json | python3 -c "
import json, sys
for m in json.load(sys.stdin):
    meta = (m.get('config') or {}).get('metadata') or {}
    pg = (meta.get('fly_process_group') or m.get('process_group') or 'web').lower()
    if pg == 'worker' and m.get('id'):
        print(m['id'])
        break
")"

WORKER_IP="$(flyctl machines list -a "$APP" --json | python3 -c "
import json, sys
for m in json.load(sys.stdin):
    meta = (m.get('config') or {}).get('metadata') or {}
    pg = (meta.get('fly_process_group') or m.get('process_group') or 'web').lower()
    if pg == 'worker':
        ip = (m.get('private_ip') or '').strip()
        if ip:
            print(ip)
        break
")"

if [ -z "$WEB_ID" ] || [ -z "$WORKER_ID" ]; then
  echo "fly_probe_worker_from_web: missing web=$WEB_ID worker=$WORKER_ID"
  exit 0
fi

if [ -n "$WORKER_IP" ]; then
  TARGET="http://[${WORKER_IP}]:8080/api/ops/worker-peer"
else
  TARGET="http://${WORKER_ID}.vm.${APP}.internal:8080/api/ops/worker-peer"
fi
echo "fly_probe_worker_from_web: web=$WEB_ID worker=$WORKER_ID target=$TARGET"
flyctl machine exec "$WEB_ID" -a "$APP" -- sh -c "python -c \"import requests; r=requests.get('$TARGET', headers={'X-Worker-Proxy':'1'}, timeout=8); print(r.status_code, r.text[:300])\"" || echo "WARN: exec probe failed"
