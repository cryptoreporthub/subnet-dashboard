#!/usr/bin/env bash
# Enable Fly worker split v2 — human ops (requires flyctl auth + volume on worker).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
REGION="${FLY_PRIMARY_REGION:-sjc}"

echo "== Phase C: enable worker split v2 on $APP =="
echo "Prereq: data_volume attached to worker machine in $REGION (web has NO volume)."
echo ""

if ! flyctl auth whoami 2>/dev/null; then
  echo "ABORT: flyctl not authenticated"
  exit 1
fi

echo "=== 1. Ensure worker volume in $REGION ==="
COUNT=$(flyctl volumes list -a "$APP" --json | python3 -c "
import json,sys,os
region=os.environ.get('FLY_PRIMARY_REGION','sjc')
rows=json.load(sys.stdin)
print(sum(1 for v in rows if v.get('name')=='data_volume' and v.get('region')==region))
")
if [ "$COUNT" -lt 1 ]; then
  echo "Creating data_volume in $REGION for worker machine..."
  flyctl volumes create data_volume --app "$APP" --region "$REGION" -n 1 --yes
else
  echo "data_volume count in $REGION: $COUNT"
fi

echo "=== 2. Deploy v2 config (worker-only volume, WORKER_SPLIT_V2=on) ==="
flyctl deploy --config fly.worker-v2.toml --remote-only --no-cache --yes --regions "$REGION" --ha=false

echo "=== 3. Scale web=1 worker=1 ==="
flyctl scale count web=1 worker=1 --app "$APP" --yes

echo "=== 4. Set WORKER_SPLIT_V2=on (disables inline worker on web) ==="
flyctl secrets set WORKER_SPLIT_V2=on --app "$APP"

echo "=== 5. Verify ==="
sleep 30
BASE="https://${APP}.fly.dev"
curl -fsS --max-time 15 "$BASE/health" && echo " health OK"
curl -fsS --max-time 15 "$BASE/api/ops/readiness" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('worker_mode:', d.get('worker_mode'))
print('worker_peer:', d.get('worker_peer'))
print('volume:', d.get('volume') or (d.get('learning_loop_health') or {}).get('volume'))
"

echo ""
echo "Rollback:"
echo "  fly scale count worker=0 --app $APP --yes"
echo "  fly secrets set WORKER_SPLIT_V2=off --app $APP"
echo "  fly deploy --config fly.toml --remote-only --yes"
echo "  fly scale count web=1 --app $APP --yes"
