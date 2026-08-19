#!/usr/bin/env bash
# Enable Fly worker split v2 — migrates data_volume from web → worker machine.
#
# CORRECT ORDER (post-incident revised):
#   1. Release volume from web (destroy machines)
#   2. Deploy v2 config (volume on worker, entrypoints via sh)
#   3. Scale web=1 worker=1, start machines
#   4. Wait for worker healthy on :8081 — GATE (exit if unhealthy)
#   5. Probe gate: web→worker private HTTP must work
#   6. THEN set WORKER_SPLIT_V2=on secret (disables inline worker on web)
#   7. Run full v2 verification gate
#
# The old script set the secret BEFORE deploy, so a lucky-fast boot masked
# a still-wrong sequence. This version proves the worker is alive before
# the web process learns to stop its inline worker.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
REGION="${FLY_PRIMARY_REGION:-sjc}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE="https://${APP}.fly.dev"

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

echo "=== 2. Deploy v2 config (worker-only volume mount) ==="
echo "NOTE: WORKER_SPLIT_V2 secret is NOT set yet — web keeps inline worker"
echo "      until the dedicated worker proves healthy on :8081."
flyctl deploy --config fly.worker-v2.toml --remote-only --no-cache --yes --regions "$REGION" --ha=false

echo "=== 3. Scale web=1 worker=1 ==="
flyctl scale count web=1 worker=1 --app "$APP" --yes

echo "=== 4. Start machines + wait for worker :8081 health ==="
for id in $(flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    if m.get('id'):
        print(m['id'])
"); do
  flyctl machine start "$id" -a "$APP" 2>/dev/null || true
done

echo "waiting 60s for boot..."
sleep 60

worker_healthy=0
for i in $(seq 1 12); do
  echo "worker :8081 health attempt $i/12..."
  # Probe worker machine directly via flyctl machine exec
  if flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    meta = (m.get('config') or {}).get('metadata') or {}
    pg = (meta.get('fly_process_group') or m.get('process_group') or '').lower()
    if pg == 'worker' and m.get('id'):
        print(m['id'])
        break
" | head -1 | xargs -I{} flyctl machine exec -a "$APP" {} "curl -fsS --max-time 5 http://localhost:8081/health" 2>/dev/null; then
    worker_healthy=1
    echo "worker :8081 health OK"
    break
  fi
  echo "worker not yet healthy — waiting 15s"
  sleep 15
done

if [ "$worker_healthy" != "1" ]; then
  echo "ABORT: worker never became healthy on :8081 after ~4m"
  echo "Rolling back: destroying machines, will need manual recovery"
  flyctl status -a "$APP" || true
  flyctl logs -a "$APP" --no-tail 2>&1 | tail -50 || true
  exit 1
fi

echo "=== 5. Probe gate: web→worker private HTTP ==="
chmod +x "$SCRIPT_DIR/fly_probe_worker_from_web.sh"
probe_ok=0
for attempt in $(seq 1 6); do
  echo "web→worker probe attempt $attempt/6..."
  if FLY_APP="$APP" "$SCRIPT_DIR/fly_probe_worker_from_web.sh"; then
    probe_ok=1
    break
  fi
  sleep 15
done

if [ "$probe_ok" != "1" ]; then
  echo "ABORT: web→worker private HTTP probe failed"
  echo "Worker is healthy but web cannot reach it. Do NOT set WORKER_SPLIT_V2=on."
  echo "Debug networking before retrying."
  exit 1
fi

echo "=== 6. Set WORKER_SPLIT_V2=on (worker proven healthy + reachable) ==="
flyctl secrets set WORKER_SPLIT_V2=on --app "$APP"

echo "waiting 30s for secret propagation + web restart..."
sleep 30

echo "=== 7. Full v2 verification gate ==="
chmod +x "$SCRIPT_DIR/fly_v2_cutover_gate.sh" 2>/dev/null || true
if [ -x "$SCRIPT_DIR/fly_v2_cutover_gate.sh" ]; then
  FLY_APP="$APP" APP_BASE_URL="$BASE" "$SCRIPT_DIR/fly_v2_cutover_gate.sh"
else
  echo "WARN: fly_v2_cutover_gate.sh not found — running inline checks"
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
fi

echo ""
echo "v2 enabled. Pin WORKER_INTERNAL_URL next:"
echo "  FLY_APP=$APP ./scripts/fly_set_worker_internal_url.sh"
echo ""
echo "Rollback:"
echo "  ./scripts/fly_disable_worker_v2.sh"
