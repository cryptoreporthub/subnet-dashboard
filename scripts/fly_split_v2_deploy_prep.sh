#!/usr/bin/env bash
# Pre-deploy prep for split v2: release volume from web, clear stale machines/leases.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
REGION="${FLY_PRIMARY_REGION:-sjc}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WAIT="${FLY_PREP_WAIT_SECONDS:-25}"

echo "=== fly_split_v2_deploy_prep: app=$APP region=$REGION ==="

chmod +x "$SCRIPT_DIR/fly_v2_volume_repair.sh"
FLY_V2_REPAIR_MODE=destroy FLY_APP="$APP" FLY_PRIMARY_REGION="$REGION" \
  "$SCRIPT_DIR/fly_v2_volume_repair.sh" || true

destroyed=0
while IFS= read -r mid; do
  [ -z "$mid" ] && continue
  echo "destroy machine $mid (web volume mount or stale lease)"
  flyctl machine destroy "$mid" -a "$APP" --force || true
  destroyed=1
done < <(flyctl machines list -a "$APP" --json | python3 -c "
import json, sys

machines = json.load(sys.stdin)

def process_group(m):
    meta = (m.get('config') or {}).get('metadata') or {}
    return (
        meta.get('fly_process_group')
        or meta.get('process_group')
        or m.get('process_group')
        or 'web'
    ).lower()

def has_volume_mount(m):
    mounts = (m.get('config') or {}).get('mounts') or []
    return any(mount.get('volume') for mount in mounts)

for m in machines:
    mid = m.get('id') or ''
    if not mid:
        continue
    pg = process_group(m)
    state = (m.get('state') or '').lower()
    if pg == 'web' and has_volume_mount(m):
        print(mid)
    elif state in ('created', 'starting', 'stopped', 'failed'):
        print(mid)
")

if [ "$destroyed" = 1 ]; then
  echo "waiting ${WAIT}s after machine cleanup..."
  sleep "$WAIT"
fi

flyctl machines list -a "$APP" || true
flyctl volumes list -a "$APP" || true
echo "=== fly_split_v2_deploy_prep done ==="
