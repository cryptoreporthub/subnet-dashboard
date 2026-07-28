#!/usr/bin/env bash
# Enable Fly worker split v2 — migrates data_volume from web → worker machine.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
REGION="${FLY_PRIMARY_REGION:-sjc}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== Phase C: enable worker split v2 on $APP =="
echo "Migrates existing data_volume to worker; web serves HTTP only (no volume)."
echo ""

if ! flyctl auth whoami 2>/dev/null; then
  echo "ABORT: flyctl not authenticated"
  exit 1
fi

echo "=== 1. Release data_volume from web machine (preserve volume data) ==="
flyctl scale count worker=0 --app "$APP" --yes 2>/dev/null || true

for id in $(flyctl machines list -a "$APP" --json 2>/dev/null | python3 -c "
import json,sys
try:
    for m in json.load(sys.stdin):
        if m.get('id'):
            print(m['id'])
except Exception:
    pass
" 2>/dev/null); do
  echo "destroy machine $id (releases volume attachment)"
  flyctl machine destroy "$id" -a "$APP" --force 2>/dev/null || true
done

echo "waiting 25s for volume detach..."
sleep 25

unattached=$(flyctl volumes list -a "$APP" --json 2>/dev/null | python3 -c "
import json,sys,os
region=os.environ.get('FLY_PRIMARY_REGION','sjc')
vols=json.load(sys.stdin)
print(sum(1 for v in vols if v.get('name')=='data_volume' and v.get('region')==region and not v.get('attached_machine_id')))
" 2>/dev/null || echo 0)

if [ "$unattached" = "0" ]; then
  COUNT=$(flyctl volumes list -a "$APP" --json | python3 -c "
import json,sys,os
region=os.environ.get('FLY_PRIMARY_REGION','sjc')
rows=json.load(sys.stdin)
print(sum(1 for v in rows if v.get('name')=='data_volume' and v.get('region')==region))
")
  if [ "$COUNT" -lt 1 ]; then
    echo "Creating data_volume in $REGION..."
    flyctl volumes create data_volume --app "$APP" --region "$REGION" -n 1 --yes
  else
    echo "ABORT: data_volume still attached — run scripts/fly_volume_recover.sh first"
    flyctl volumes list -a "$APP" || true
    exit 1
  fi
else
  echo "unattached data_volume in $REGION: $unattached (ready for worker attach)"
fi

echo "=== 2. Set WORKER_SPLIT_V2=on (before deploy — disables inline worker on web) ==="
flyctl secrets set WORKER_SPLIT_V2=on --app "$APP"

echo "=== 3. Deploy v2 config (worker-only volume mount) ==="
flyctl deploy --config fly.worker-v2.toml --remote-only --no-cache --yes --regions "$REGION" --ha=false

echo "=== 4. Scale web=1 worker=1 ==="
flyctl scale count web=1 worker=1 --app "$APP" --yes

echo "=== 5. Start machines + brief health wait ==="
for id in $(flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    if m.get('id'):
        print(m['id'])
"); do
  flyctl machine start "$id" -a "$APP" 2>/dev/null || true
done

echo "waiting 45s for boot..."
sleep 45

BASE="https://${APP}.fly.dev"
echo "=== 6. Verify ==="
for i in 1 2 3 4 5 6; do
  if curl -fsS --max-time 12 "$BASE/health" >/dev/null 2>&1; then
    echo "health OK (attempt $i)"
    break
  fi
  echo "health attempt $i failed — waiting 15s"
  sleep 15
done

curl -fsS --max-time 15 "$BASE/health" && echo ""
curl -fsS --max-time 20 "$BASE/api/ops/readiness" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('worker_mode:', d.get('worker_mode'))
print('worker_peer:', d.get('worker_peer'))
print('status:', d.get('status'))
" || echo "WARN: readiness probe failed (may still be warming)"

echo ""
echo "Rollback:"
echo "  fly scale count worker=0 --app $APP --yes"
echo "  fly secrets set WORKER_SPLIT_V2=off --app $APP"
echo "  fly deploy --config fly.toml --remote-only --yes"
echo "  fly scale count web=1 --app $APP --yes"
