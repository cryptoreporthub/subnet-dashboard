#!/usr/bin/env bash
# ponytail: repair split_v2 when data_volume stuck on web instead of worker.
# FLY_V2_REPAIR_MODE=destroy — only recycle machines (GHA pre-deploy; main deploy follows).
# FLY_V2_REPAIR_MODE=full — destroy + deploy + scale (GHA post-deploy if still misplaced).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
REGION="${FLY_PRIMARY_REGION:-sjc}"
MODE="${FLY_V2_REPAIR_MODE:-destroy}"

echo "=== fly_v2_volume_repair: check volume placement ($APP) mode=$MODE ==="

read -r vol_id attached_id web_id worker_id <<<"$(flyctl volumes list -a "$APP" --json | python3 -c "
import json, subprocess, sys

app = sys.argv[1]
vols = json.load(sys.stdin)
data = next((v for v in vols if v.get('name') == 'data_volume'), None)
if not data:
    print('', '', '', '')
    raise SystemExit(0)

vol_id = data.get('id') or ''
attached = data.get('attached_machine_id') or ''

machines = json.loads(
    subprocess.check_output(['flyctl', 'machines', 'list', '-a', app, '--json'], text=True)
)

def process_group(m):
    meta = (m.get('config') or {}).get('metadata') or {}
    return (
        meta.get('fly_process_group')
        or meta.get('process_group')
        or m.get('process_group')
        or 'web'
    ).lower()

web_id = worker_id = ''
for m in machines:
    pg = process_group(m)
    mid = m.get('id') or ''
    if pg == 'web':
        web_id = mid
    elif pg == 'worker':
        worker_id = mid

print(vol_id, attached, web_id, worker_id)
" "$APP")"

echo "data_volume=$vol_id attached_to=$attached_id web=$web_id worker=$worker_id"

if [ -z "$vol_id" ]; then
  echo "fly_v2_volume_repair: no data_volume — skip"
  exit 0
fi

if [ -z "$web_id" ] || [ -z "$worker_id" ]; then
  echo "fly_v2_volume_repair: need web=1 worker=1 — skip"
  exit 0
fi

if [ "$attached_id" != "$web_id" ]; then
  if [ -n "$attached_id" ] && [ "$attached_id" = "$worker_id" ]; then
    echo "fly_v2_volume_repair: volume already on worker — ok"
  else
    echo "fly_v2_volume_repair: volume not on web (attached_to=$attached_id) — skip"
  fi
  exit 0
fi

echo "REPAIR: data_volume on web — recycle machines so worker mounts volume"

flyctl machine destroy "$web_id" -a "$APP" --force
echo "destroyed web $web_id — waiting 25s for volume detach..."
sleep 25

flyctl volumes list -a "$APP" || true

if [ -n "$worker_id" ]; then
  echo "destroying worker $worker_id before redeploy"
  flyctl machine destroy "$worker_id" -a "$APP" --force || true
  sleep 10
fi

if [ "$MODE" = "destroy" ]; then
  echo "REPAIR: destroy-only — main deploy step will recreate machines"
  exit 0
fi

echo "REPAIR: redeploy fly.worker-v2.toml (worker process owns [mounts])"
flyctl deploy --config fly.worker-v2.toml --remote-only --no-cache --yes --regions "$REGION" --ha=false
flyctl scale count web=1 worker=1 --app "$APP" --yes

echo "waiting 45s for worker boot + volume attach..."
sleep 45
flyctl machines list -a "$APP" || true
flyctl volumes list -a "$APP" || true
