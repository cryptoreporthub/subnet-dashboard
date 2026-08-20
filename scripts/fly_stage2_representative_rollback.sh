#!/usr/bin/env bash
# Roll back Stage 2b representative soak → v1 fly.toml (web + inline worker + volume).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
REGION="${FLY_PRIMARY_REGION:-sjc}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== Stage 2b representative rollback: $APP → v1 fly.toml =="

if ! flyctl auth whoami 2>/dev/null; then
  echo "ABORT: flyctl not authenticated"
  exit 1
fi

# Clear representative marker if set as secret (optional).
flyctl secrets unset STAGE2_REPRESENTATIVE --app "$APP" 2>/dev/null || true

echo "=== destroy all machines (release volume) ==="
flyctl scale count worker=0 --app "$APP" --yes 2>/dev/null || true
for id in $(flyctl machines list -a "$APP" --json 2>/dev/null | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    if m.get('id'):
        print(m['id'])
" 2>/dev/null); do
  echo "destroy $id"
  flyctl machine destroy "$id" -a "$APP" --force 2>/dev/null || true
done

echo "waiting 25s for volume detach..."
sleep 25

echo "=== redeploy v1 fly.toml ==="
flyctl deploy --config fly.toml --remote-only --no-cache --yes --regions "$REGION" --ha=false
flyctl scale count web=1 --app "$APP" --yes

echo "waiting 45s for v1 boot..."
sleep 45

echo "=== verify v1 health ==="
curl -fsS --max-time 15 "https://${APP}.fly.dev/health" && echo ""

if [ -x "$SCRIPT_DIR/fly_v1_freshness_gate.sh" ]; then
  FRESHNESS_WAIT_SECONDS=120 "$SCRIPT_DIR/fly_v1_freshness_gate.sh" || echo "WARN: freshness gate not yet green — monitor before Stage 3"
fi

echo ""
echo "Rollback complete. v1 topology restored."
