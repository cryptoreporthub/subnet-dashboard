#!/usr/bin/env bash
# Stage 3, step 7: v2 cutover verification gate.
# Scripted — exits nonzero on ANY check failure. Do not hand-check under
# incident-adjacent fatigue.
#
# All of the following must pass:
#   1. GET /health 200
#   2. worker_mode: split_v2
#   3. worker_peer.alive true FROM WEB (readiness API)
#   4. /api/data-freshness not stale after bounded wait
#   5. volume attached_machine_id = worker machine
#   6. web has NO volume
#   7. web logs: "skipping inline worker" (BLOCKING — not advisory)
#   8. worker process running on worker machine
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
BASE="${APP_BASE_URL:-https://${APP}.fly.dev}"
FRESHNESS_WAIT="${FRESHNESS_WAIT_SECONDS:-300}"
FRESHNESS_INTERVAL="${FRESHNESS_INTERVAL_SECONDS:-15}"

_fail() {
  echo "GATE FAIL: $1"
  echo ""
  echo "ROLLBACK: ./scripts/fly_disable_worker_v2.sh"
  exit 1
}

echo "== v2 cutover verification gate: $APP =="
echo ""

# --- 1. GET /health 200 ---
echo "=== Check 1: /health 200 ==="
health_code=$(curl -sS -m 10 -o /dev/null -w "%{http_code}" "$BASE/health" || echo 000)
echo "  /health: HTTP $health_code"
[ "$health_code" = "200" ] || _fail "/health returned $health_code, expected 200"

# --- 2 + 3. worker_mode: split_v2 + worker_peer.alive ---
echo "=== Check 2+3: readiness (worker_mode + worker_peer.alive) ==="
readiness=$(curl -fsS --max-time 20 "$BASE/api/ops/readiness" 2>/dev/null || echo '{}')
echo "$readiness" | python3 -c "
import json,sys
d=json.load(sys.stdin)
mode=d.get('worker_mode')
peer=d.get('worker_peer') or {}
alive=peer.get('alive')
print(f'  worker_mode: {mode}')
print(f'  worker_peer.alive: {alive}')
if mode != 'split_v2':
    print('FAIL: worker_mode is not split_v2')
    sys.exit(1)
if alive is not True:
    print('FAIL: worker_peer.alive is not True')
    sys.exit(1)
" || _fail "readiness check failed (worker_mode or worker_peer.alive)"

# --- 4. /api/data-freshness not stale ---
echo "=== Check 4: data-freshness (bounded wait ${FRESHNESS_WAIT}s) ==="
fresh_ok=0
elapsed=0
while [ "$elapsed" -lt "$FRESHNESS_WAIT" ]; do
  body=$(curl -fsS --max-time 15 "$BASE/api/data-freshness" 2>/dev/null || echo '{}')
  stale=$(echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('stale','unknown'))" 2>/dev/null || echo unknown)
  count=$(echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('subnet_count',0))" 2>/dev/null || echo 0)
  echo "  freshness: stale=$stale subnet_count=$count (${elapsed}s elapsed)"
  if [ "$stale" = "False" ] && [ "$count" != "0" ]; then
    fresh_ok=1
    break
  fi
  sleep "$FRESHNESS_INTERVAL"
  elapsed=$((elapsed + FRESHNESS_INTERVAL))
done
[ "$fresh_ok" = "1" ] || _fail "data-freshness still stale after ${FRESHNESS_WAIT}s"

# --- 5 + 6. Volume on worker, NOT on web ---
echo "=== Check 5+6: volume topology ==="
flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
machines=json.load(sys.stdin)
web_ids=[]
worker_ids=[]
for m in machines:
    meta=(m.get('config') or {}).get('metadata') or {}
    pg=(meta.get('fly_process_group') or m.get('process_group') or 'web').lower()
    mid=m.get('id','')
    if pg=='web':
        web_ids.append(mid)
    elif pg=='worker':
        worker_ids.append(mid)
print(f'  web machines: {web_ids}')
print(f'  worker machines: {worker_ids}')
if not worker_ids:
    print('FAIL: no worker machine found')
    sys.exit(1)
" || _fail "machine list parse failed"

flyctl volumes list -a "$APP" --json | python3 -c "
import json,sys,os
region=os.environ.get('FLY_PRIMARY_REGION','sjc')
vols=json.load(sys.stdin)
data_vols=[v for v in vols if v.get('name')=='data_volume' and v.get('region')==region]
if not data_vols:
    print('FAIL: no data_volume in region')
    sys.exit(1)
vol=data_vols[0]
attached=vol.get('attached_machine_id','')
print(f'  data_volume attached to: {attached}')
" || _fail "volume check failed"

# Cross-check: volume must be on a worker machine, not web
flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
machines=json.load(sys.stdin)
web_ids=set()
worker_ids=set()
for m in machines:
    meta=(m.get('config') or {}).get('metadata') or {}
    pg=(meta.get('fly_process_group') or m.get('process_group') or 'web').lower()
    mid=m.get('id','')
    if pg=='web':
        web_ids.add(mid)
    elif pg=='worker':
        worker_ids.add(mid)
import subprocess
vol_json=subprocess.check_output(['flyctl','volumes','list','-a',sys.argv[1],'--json'],text=True)
vols=json.loads(vol_json)
for v in vols:
    if v.get('name')!='data_volume':
        continue
    attached=v.get('attached_machine_id','')
    if attached in web_ids:
        print(f'FAIL: data_volume attached to WEB machine {attached}')
        sys.exit(1)
    if attached in worker_ids:
        print(f'  OK: data_volume attached to WORKER machine {attached}')
    elif attached:
        print(f'  WARN: data_volume attached to unknown machine {attached}')
    else:
        print('FAIL: data_volume not attached to any machine')
        sys.exit(1)
" "$APP" || _fail "volume-on-worker cross-check failed"

# --- 7. Web logs: "skipping inline worker" (BLOCKING) ---
echo "=== Check 7: web logs must say 'skipping inline worker' ==="
# Get the web machine ID
WEB_ID=$(flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    meta=(m.get('config') or {}).get('metadata') or {}
    pg=(meta.get('fly_process_group') or m.get('process_group') or 'web').lower()
    if pg=='web' and m.get('id'):
        print(m['id'])
        break
")

skip_found=0
# Check recent logs for the skipping message
logs=$(flyctl logs -a "$APP" --no-tail 2>&1 || true)
if echo "$logs" | grep -qi "skipping inline worker"; then
  skip_found=1
  echo "  OK: found 'skipping inline worker' in logs"
fi

if [ "$skip_found" != "1" ]; then
  # Also try machine exec to check entrypoint output
  if [ -n "$WEB_ID" ]; then
    if flyctl machine exec -a "$APP" "$WEB_ID" "grep -l 'skipping inline worker' /proc/1/fd/1 2>/dev/null || journalctl -u fly-init --no-pager 2>/dev/null | grep -i 'skipping inline worker'" 2>/dev/null | grep -qi "skipping"; then
      skip_found=1
      echo "  OK: found 'skipping inline worker' via machine exec"
    fi
  fi
fi

if [ "$skip_found" != "1" ]; then
  # Check if web says "starting inline worker" — that's a hard fail
  if echo "$logs" | grep -qi "starting inline.*worker"; then
    _fail "web logs say 'starting inline worker' — v2 secret did NOT take effect. ROLL BACK."
  fi
  _fail "web logs missing 'skipping inline worker'. Web may still be running inline worker. ROLL BACK."
fi

# --- 8. Worker process running on worker machine ---
echo "=== Check 8: worker process running ==="
WORKER_ID=$(flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    meta=(m.get('config') or {}).get('metadata') or {}
    pg=(meta.get('fly_process_group') or m.get('process_group') or '').lower()
    if pg=='worker' and m.get('id'):
        print(m['id'])
        break
")

if [ -z "$WORKER_ID" ]; then
  _fail "no worker machine found"
fi

worker_state=$(flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    if m.get('id')==sys.argv[1]:
        print(m.get('state','unknown'))
        break
" "$WORKER_ID")
echo "  worker machine $WORKER_ID state: $worker_state"
if [ "$worker_state" != "started" ]; then
  _fail "worker machine state is '$worker_state', expected 'started'"
fi

echo ""
echo "== ALL CHECKS PASSED — v2 cutover verified =="
echo ""
echo "Next: pin WORKER_INTERNAL_URL to the proven hop:"
echo "  FLY_APP=$APP ./scripts/fly_set_worker_internal_url.sh"
echo ""
echo "Rollback stays armed:"
echo "  ./scripts/fly_disable_worker_v2.sh"
