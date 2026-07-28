#!/usr/bin/env bash
# Point web → worker HTTP at worker 6PN (literal IPv6 + worker-only port).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
PORT="${WORKER_HTTP_PORT:-8081}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! "$SCRIPT_DIR/fly_worker_split_v2_guard.sh"; then
  echo "fly_set_worker_internal_url: split_v2 not enabled — unset legacy WORKER_INTERNAL_URL"
  flyctl secrets unset WORKER_INTERNAL_URL --app "$APP" 2>/dev/null || true
  exit 0
fi

WORKER_URL="$(
  flyctl machines list -a "$APP" --json | python3 -c "
import json, os, sys

app = sys.argv[1]
port = os.environ.get('WORKER_HTTP_PORT', '8081')
machines = json.load(sys.stdin)

def process_group(m):
    meta = (m.get('config') or {}).get('metadata') or {}
    return (
        meta.get('fly_process_group')
        or meta.get('process_group')
        or m.get('process_group')
        or 'web'
    ).lower()

workers = [m for m in machines if process_group(m) == 'worker']
if not workers:
    raise SystemExit(0)
m = workers[0]
ip = (m.get('private_ip') or '').strip()
if ip:
    print(f'http://[{ip}]:{port}')
else:
    mid = m.get('id') or ''
    if mid:
        print(f'http://{mid}.vm.{app}.internal:{port}')
" "$APP"
)"

if [ -z "$WORKER_URL" ]; then
  echo "fly_set_worker_internal_url: no worker machine — skip"
  exit 0
fi

echo "fly_set_worker_internal_url: WORKER_INTERNAL_URL=$WORKER_URL"
flyctl secrets set "WORKER_INTERNAL_URL=$WORKER_URL" --app "$APP"
