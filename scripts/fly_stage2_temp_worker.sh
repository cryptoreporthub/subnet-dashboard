#!/usr/bin/env bash
# Stage 2: deploy temp worker via v2 kit [[services]] on :8081 (NOT machine run).
#
# Web stays on v1 fly.toml (volume + inline worker). This adds a dedicated worker
# machine registered through Fly's services mesh so hop probes are representative.
#
# Uses fly.worker-v2-hop.toml (v2 routing, no volume mount).
#
# Does NOT: set WORKER_SPLIT_V2, modify fly.toml, or touch fly.yml.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
CONFIG="${STAGE2_WORKER_CONFIG:-fly.worker-v2-hop.toml}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== Stage 2 temp worker deploy: $APP =="
echo "Config: $CONFIG (v2 [[services]] on :8081, no volume)"
echo ""

if ! flyctl auth whoami 2>/dev/null; then
  echo "ABORT: flyctl not authenticated"
  exit 1
fi

if [ ! -f "$CONFIG" ]; then
  echo "ABORT: missing $CONFIG"
  exit 1
fi

# Stage 2 forbids split_v2 secrets.
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

echo "=== machines before ==="
flyctl machines list -a "$APP"

echo ""
echo "=== deploy worker process group (v2 hop overlay) ==="
flyctl deploy --config "$CONFIG" --process-groups worker -a "$APP" --ha=false --yes

echo ""
echo "=== wait for worker :8081 health ==="
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
echo "=== probe from web (flycast path must OK) ==="
chmod +x "$SCRIPT_DIR/fly_probe_worker_from_web.sh"
FLY_APP="$APP" "$SCRIPT_DIR/fly_probe_worker_from_web.sh"

echo ""
echo "=== machines after ==="
flyctl machines list -a "$APP"
echo ""
echo "Temp worker ready. Run Stage 2 soak via GHA workflow 'Fly Stage 2 soak (hop proof)'"
echo "(workflow_dispatch, confirm=soak, timeout-minutes: 240)."
