#!/usr/bin/env bash
# Gate before Stage 2b representative soak or Stage 3 cutover retry.
# Confirms v1 baseline freshness has recovered — do not stack attempts on degraded prod.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
BASE="${APP_BASE_URL:-https://${APP}.fly.dev}"
WAIT="${FRESHNESS_WAIT_SECONDS:-300}"
INTERVAL="${FRESHNESS_INTERVAL_SECONDS:-15}"
MAX_LEARNING_AGE="${MAX_LEARNING_HEALTH_AGE_SECONDS:-900}"

_fail() {
  echo "V1 FRESHNESS GATE FAIL: $1"
  exit 1
}

echo "== v1 freshness gate: $APP =="
echo "base=$BASE wait=${WAIT}s max_learning_age=${MAX_LEARNING_AGE}s"
echo ""

echo "=== Check 1: /health 200 ==="
code=$(curl -sS -m 10 -o /dev/null -w "%{http_code}" "$BASE/health" || echo 000)
echo "  /health: HTTP $code"
[ "$code" = "200" ] || _fail "/health returned $code"

echo "=== Check 2: worker_mode not split_v2 (v1 baseline) ==="
readiness=$(curl -fsS --max-time 20 "$BASE/api/ops/readiness" 2>/dev/null || echo '{}')
echo "$readiness" | python3 -c "
import json,sys
d=json.load(sys.stdin)
mode=d.get('worker_mode')
print(f'  worker_mode: {mode}')
if mode == 'split_v2':
    print('FAIL: still on split_v2 — rollback to v1 first')
    sys.exit(1)
" || _fail "readiness worker_mode check failed"

echo "=== Check 3: data-freshness not stale (bounded wait ${WAIT}s) ==="
fresh_ok=0
elapsed=0
while [ "$elapsed" -lt "$WAIT" ]; do
  body=$(curl -fsS --max-time 15 "$BASE/api/data-freshness" 2>/dev/null || echo '{}')
  stale=$(echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('stale','unknown'))" 2>/dev/null || echo unknown)
  count=$(echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('subnet_count',0))" 2>/dev/null || echo 0)
  last_sync=$(echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('last_sync','?'))" 2>/dev/null || echo ?)
  echo "  stale=$stale subnet_count=$count last_sync=$last_sync (${elapsed}s)"
  if [ "$stale" = "False" ] && [ "$count" != "0" ]; then
    fresh_ok=1
    break
  fi
  sleep "$INTERVAL"
  elapsed=$((elapsed + INTERVAL))
done
[ "$fresh_ok" = "1" ] || _fail "data-freshness still stale after ${WAIT}s"

echo "=== Check 4: learning-health ok + resolver tick age ==="
lh=$(curl -fsS --max-time 25 "$BASE/api/learning/health" 2>/dev/null || echo '{}')
echo "$lh" | python3 -c "
import json,sys,os
from datetime import datetime, timezone

d=json.load(sys.stdin)
status=d.get('status')
print(f'  learning-health status: {status}')
if status not in ('ok', 'live', 'degraded'):
    print(f'FAIL: unexpected learning-health status {status!r}')
    sys.exit(1)

max_age=float(os.environ.get('MAX_LEARNING_HEALTH_AGE_SECONDS','900'))
tick=d.get('last_resolver_tick') or d.get('resolver_last_tick') or d.get('last_tick')
if tick:
    try:
        ts=datetime.fromisoformat(str(tick).replace('Z','+00:00'))
        age=(datetime.now(timezone.utc)-ts.astimezone(timezone.utc)).total_seconds()
        print(f'  resolver tick age: {int(age)}s (max {int(max_age)}s)')
        if age > max_age:
            print('FAIL: resolver tick too stale for cutover/soak retry')
            sys.exit(1)
    except Exception as exc:
        print(f'  WARN: could not parse tick {tick!r}: {exc}')
" || _fail "learning-health check failed"

echo ""
echo "== V1 FRESHNESS GATE PASSED =="
