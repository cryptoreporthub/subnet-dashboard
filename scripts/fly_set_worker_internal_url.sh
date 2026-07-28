#!/usr/bin/env bash
# Point web → worker HTTP at a specific worker machine (6PN VM DNS).
# ponytail: process-group DNS can return wrong/stale targets; vm.<id>.internal is stable per machine.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! "$SCRIPT_DIR/fly_worker_split_v2_guard.sh"; then
  echo "fly_set_worker_internal_url: split_v2 not enabled — unset legacy WORKER_INTERNAL_URL"
  flyctl secrets unset WORKER_INTERNAL_URL --app "$APP" 2>/dev/null || true
  exit 0
fi

WORKER_URL="$(
  flyctl machines list -a "$APP" --json | python3 -c "
import json, sys

app = sys.argv[1]
machines = json.load(sys.stdin)

def process_group(m):
    meta = (m.get('config') or {}).get('metadata') or {}
    return (
        meta.get('fly_process_group')
        or meta.get('process_group')
        or m.get('process_group')
        or 'web'
    ).lower()

started = [
    m for m in machines
    if process_group(m) == 'worker' and (m.get('state') or '').lower() == 'started'
]
if not started:
    for m in machines:
        if process_group(m) == 'worker':
            started.append(m)
if not started:
    raise SystemExit(0)
mid = started[0].get('id') or ''
if mid:
    print(f'http://{mid}.vm.{app}.internal:8080')
" "$APP"
)"

if [ -z "$WORKER_URL" ]; then
  echo "fly_set_worker_internal_url: no worker machine — skip"
  exit 0
fi

echo "fly_set_worker_internal_url: WORKER_INTERNAL_URL=$WORKER_URL"
flyctl secrets set "WORKER_INTERNAL_URL=$WORKER_URL" --app "$APP"
