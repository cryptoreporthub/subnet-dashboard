#!/usr/bin/env bash
# Rollback split_v2 → v1: one web machine owns data_volume + inline worker.
# Canon: docs/fly-web-worker-split.md · cursor-agents-communication/split-v2-rollback-runbook.md
#
# Why: web→worker private HTTP has been chronically unreachable on this app.
# Soft stubs / proxy fallthroughs cannot restore volume data — only co-locating
# HTTP + volume on one machine does.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
REGION="${FLY_PRIMARY_REGION:-sjc}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== Rollback: disable worker split v2 on $APP =="
echo "Restores inline worker on web; data_volume attaches to the web machine."
echo ""

if ! flyctl auth whoami 2>/dev/null; then
  echo "ABORT: flyctl not authenticated"
  exit 1
fi

echo "=== 1. Clear v2 secrets (presence alone flips the guard) ==="
flyctl secrets unset WORKER_SPLIT_V2 --app "$APP" 2>/dev/null || true
flyctl secrets unset WORKER_INTERNAL_URL --app "$APP" 2>/dev/null || true

echo "=== 2. Scale dedicated worker to zero ==="
flyctl scale count worker=0 --app "$APP" --yes 2>/dev/null || true

echo "=== 3. Destroy machines so data_volume detaches ==="
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
    echo "WARN: data_volume still attached — listing volumes/machines"
    flyctl volumes list -a "$APP" || true
    flyctl machines list -a "$APP" || true
    echo "Continuing deploy — Fly may re-attach on create"
  fi
else
  echo "unattached data_volume in $REGION: $unattached (ready for web attach)"
fi

echo "=== 4. Deploy v1 config (fly.toml — volume on web, inline worker) ==="
if [ "${FLY_DISABLE_SKIP_DEPLOY:-}" = "1" ]; then
  echo "FLY_DISABLE_SKIP_DEPLOY=1 — skip deploy (caller will flyctl deploy fly.toml)"
else
  flyctl deploy --config fly.toml --remote-only --no-cache --yes --regions "$REGION" --ha=false

  echo "=== 5. Scale web=1 only ==="
  flyctl scale count web=1 --app "$APP" --yes
  flyctl scale count worker=0 --app "$APP" --yes 2>/dev/null || true

  echo "=== 6. Start web + wait for /health ==="
  for id in $(flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    if m.get('id'):
        print(m['id'])
"); do
    flyctl machine start "$id" -a "$APP" 2>/dev/null || true
    flyctl machines restart "$id" -a "$APP" 2>/dev/null || true
  done

  code=000
  for i in $(seq 1 36); do
    code=$(curl -sS -m 10 -o /tmp/health_body -w "%{http_code}" "https://${APP}.fly.dev/health" || echo 000)
    body=$(cat /tmp/health_body 2>/dev/null || true)
    echo "health attempt $i: HTTP $code body=$body"
    if [ "$code" = "200" ]; then
      break
    fi
    sleep 5
  done

  if [ "$code" != "200" ]; then
    echo "ABORT: public /health not 200 after rollback"
    flyctl status -a "$APP" || true
    flyctl volumes list -a "$APP" || true
    exit 1
  fi

  echo "=== 7. Verify v1 readiness (inline worker) ==="
  curl -fsS -m 20 "https://${APP}.fly.dev/api/ops/readiness" | python3 -c "
import json,sys
d=json.load(sys.stdin)
mode=d.get('worker_mode')
peer=(d.get('worker_peer') or {})
print('worker_mode=', mode)
print('worker_peer=', peer)
# v1 reports worker_mode 'split' (inline) — not split_v2
if mode == 'split_v2':
    print('WARN: still reporting split_v2 — check secrets / process groups')
    sys.exit(1)
print('rollback verify ok')
  "
fi

echo ""
echo "Done. Canon is v1 inline worker (fly.toml)."
echo "Optional: MESSAGE_INTEL_LISTENER=auto after telegram session on volume."
echo "Re-enable v2 only via workflow Enable Worker Split v2 / scripts/fly_enable_worker_v2.sh"
