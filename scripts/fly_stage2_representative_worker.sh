#!/usr/bin/env bash
# Stage 2b: deploy representative worker (volume + essential schedulers, NOT hop decoy).
#
# Prerequisites:
#   - scripts/fly_v1_freshness_gate.sh passes
#   - WORKER_SPLIT_V2 / WORKER_INTERNAL_URL secrets unset
#
# Migrates data_volume web → worker using fly.worker-v2-essential-soak.toml.
# Does NOT set WORKER_SPLIT_V2=on (that remains Stage 3).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
REGION="${FLY_PRIMARY_REGION:-sjc}"
CONFIG="${STAGE2_REPRESENTATIVE_CONFIG:-fly.worker-v2-essential-soak.toml}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== Stage 2b representative worker deploy: $APP =="
echo "Config: $CONFIG"
echo ""

if ! flyctl auth whoami 2>/dev/null; then
  echo "ABORT: flyctl not authenticated"
  exit 1
fi

if [ ! -f "$CONFIG" ]; then
  echo "ABORT: missing $CONFIG"
  exit 1
fi

if flyctl secrets list -a "$APP" --json 2>/dev/null | python3 -c "
import json, sys
rows = json.load(sys.stdin)
bad = [r['Name'] for r in rows if r.get('Name') in ('WORKER_SPLIT_V2', 'WORKER_INTERNAL_URL')]
if bad:
    print('ABORT: secrets present:', ', '.join(bad))
    sys.exit(1)
"; then
  echo "OK: WORKER_SPLIT_V2 / WORKER_INTERNAL_URL unset"
else
  exit 1
fi

echo "=== 0. v1 freshness gate ==="
chmod +x "$SCRIPT_DIR/fly_v1_freshness_gate.sh"
FLY_APP="$APP" "$SCRIPT_DIR/fly_v1_freshness_gate.sh"

echo ""
echo "=== 1. tmp boot reaper (volume owner before migration) ==="
chmod +x "$SCRIPT_DIR/fly_tmp_boot_reaper.sh"
FLY_APP="$APP" "$SCRIPT_DIR/fly_tmp_boot_reaper.sh" || echo "WARN: tmp reaper skipped (no volume machine yet)"

echo ""
echo "=== 2. Release data_volume from web (preserve volume data) ==="
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
  echo "ABORT: data_volume not detached — run scripts/fly_volume_recover.sh"
  flyctl volumes list -a "$APP" || true
  exit 1
fi
echo "unattached data_volume ready: $unattached"

echo ""
echo "=== 3. Deploy representative soak config (volume on worker) ==="
echo "NOTE: WORKER_SPLIT_V2 stays off — hop + scheduler load soak only"
flyctl deploy --config "$CONFIG" --remote-only --no-cache --yes --regions "$REGION" --ha=false

echo ""
echo "=== 4. Scale web=1 worker=1 ==="
flyctl scale count web=1 worker=1 --app "$APP" --yes

echo ""
echo "=== 5. Wait for worker :8081 health ==="
for i in $(seq 1 30); do
  if flyctl checks list -a "$APP" 2>/dev/null | grep -q ':8081.*passing\|8081.*passing'; then
    echo "worker :8081 check passing (attempt $i)"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ABORT: worker :8081 never passed health"
    flyctl checks list -a "$APP" || true
    exit 1
  fi
  sleep 10
done

echo ""
echo "=== 6. tmp boot reaper on worker volume ==="
FLY_APP="$APP" "$SCRIPT_DIR/fly_tmp_boot_reaper.sh" || true

echo ""
echo "=== 7. Probe from web (flycast) ==="
chmod +x "$SCRIPT_DIR/fly_probe_worker_from_web.sh"
FLY_APP="$APP" "$SCRIPT_DIR/fly_probe_worker_from_web.sh"

echo ""
echo "=== machines ==="
flyctl machines list -a "$APP"
echo ""
echo "Representative worker ready."
echo "Run soak: GHA 'Fly Stage 2 representative soak' (confirm=soak-representative)"
echo "Rollback: ./scripts/fly_stage2_representative_rollback.sh"
