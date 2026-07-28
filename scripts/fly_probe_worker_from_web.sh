#!/usr/bin/env bash
# Best-effort: curl worker peer from web machine via fly machine exec (GHA diagnostics).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
WORKER_URL="${WORKER_INTERNAL_URL:-}"

if [ -z "$WORKER_URL" ]; then
  WORKER_URL="$(flyctl secrets list -a "$APP" 2>/dev/null | awk '/WORKER_INTERNAL_URL/{print $1}' || true)"
fi

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

TARGET="${WORKER_URL:-http://worker.process.${APP}.internal:8080}/api/ops/worker-peer"
echo "fly_probe_worker_from_web: web=$WEB_ID target=$TARGET"
flyctl machine exec "$WEB_ID" -a "$APP" -- curl -sfS -m 8 -H "X-Worker-Proxy: 1" "$TARGET" || echo "WARN: exec curl failed"
