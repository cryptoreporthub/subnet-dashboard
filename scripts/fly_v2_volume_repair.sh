#!/usr/bin/env bash
# ponytail: repair split_v2 when data_volume stuck on web instead of worker.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! "$SCRIPT_DIR/fly_worker_split_v2_guard.sh"; then
  echo "fly_v2_volume_repair: WORKER_SPLIT_V2 not set — skip"
  exit 0
fi

echo "=== fly_v2_volume_repair: check volume placement ==="
read -r web_vol worker_vol web_id worker_id <<<"$(flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
web_vol=''
worker_vol=''
web_id=''
worker_id=''
for m in json.load(sys.stdin):
    pg=(m.get('process_group') or 'web').lower()
    vol=(m.get('config',{}).get('mounts') or [])
    vid=vol[0].get('volume') if vol else ''
    mid=m.get('id') or ''
    if pg=='web':
        web_id=mid
        web_vol=vid or ''
    elif pg=='worker':
        worker_id=mid
        worker_vol=vid or ''
print(web_vol, worker_vol, web_id, worker_id)
")"

echo "web machine=$web_id volume=$web_vol"
echo "worker machine=$worker_id volume=$worker_vol"

if [ -n "$web_vol" ] && [ -z "$worker_vol" ] && [ -n "$web_id" ]; then
  echo "REPAIR: data_volume on web — destroy web machine to release for worker mount"
  flyctl machine destroy "$web_id" -a "$APP" --force
  echo "waiting 25s for volume detach..."
  sleep 25
  flyctl volumes list -a "$APP" || true
  echo "REPAIR: redeploy so worker attaches data_volume (web recreated without mount)"
  flyctl deploy --config fly.worker-v2.toml --remote-only --no-cache --yes --regions "${FLY_PRIMARY_REGION:-sjc}" --ha=false
  flyctl scale count web=1 worker=1 --app "$APP" --yes
else
  echo "fly_v2_volume_repair: no web-only volume misplacement detected"
fi
