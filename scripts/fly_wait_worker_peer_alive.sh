#!/usr/bin/env bash
# Post-deploy gate: split v2 web→worker private HTTP must work (worker_peer.alive).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"
MAX_ATTEMPTS="${WORKER_PEER_WAIT_ATTEMPTS:-12}"
SLEEP="${WORKER_PEER_WAIT_SECONDS:-15}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

chmod +x "$SCRIPT_DIR/fly_probe_worker_from_web.sh"

echo "== fly_wait_worker_peer_alive: app=$APP base=$BASE attempts=$MAX_ATTEMPTS =="

internal_ok=0
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  echo "=== internal web→worker probe $attempt/$MAX_ATTEMPTS ==="
  if FLY_APP="$APP" "$SCRIPT_DIR/fly_probe_worker_from_web.sh"; then
    internal_ok=1
    break
  fi
  sleep "$SLEEP"
done
if [ "$internal_ok" != 1 ]; then
  echo "GUARD FAIL: web machine could not reach worker :8081 (private HTTP)"
  exit 1
fi

readiness_ok=0
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  echo "=== public readiness worker_peer $attempt/$MAX_ATTEMPTS ==="
  body="$(curl -fsS --max-time 20 "$BASE/api/ops/readiness" 2>/dev/null || echo '{}')"
  echo "$body" | python3 -c "
import json, sys
d = json.load(sys.stdin)
wp = d.get('worker_peer') or {}
mode = d.get('worker_mode')
alive = wp.get('alive')
print('worker_mode:', mode)
print('worker_peer:', json.dumps(wp, default=str))
if alive is True:
    sys.exit(0)
sys.exit(1)
" && { readiness_ok=1; break; }
  sleep "$SLEEP"
done
if [ "$readiness_ok" != 1 ]; then
  echo "GUARD FAIL: worker_peer.alive stayed false on $BASE/api/ops/readiness"
  exit 1
fi

echo "OK — worker_peer.alive=true (split v2 private HTTP verified)"
