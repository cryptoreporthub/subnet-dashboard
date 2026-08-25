#!/usr/bin/env bash
# Gate before Stage 2b representative soak or Stage 3 cutover retry.
# Confirms v1 baseline freshness has recovered — do not stack attempts on degraded prod.
#
# Read the printed diagnostics, not just exit code. A green gate rules out the
# "v1 baseline capacity" concern; degraded/timeout output is the buried finding.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
BASE="${APP_BASE_URL:-https://${APP}.fly.dev}"
WAIT="${FRESHNESS_WAIT_SECONDS:-300}"
INTERVAL="${FRESHNESS_INTERVAL_SECONDS:-15}"
MAX_LEARNING_AGE="${MAX_LEARNING_HEALTH_AGE_SECONDS:-900}"
MAX_LEARNING_LATENCY="${MAX_LEARNING_HEALTH_LATENCY_SECONDS:-10}"

_fail() {
  echo "V1 FRESHNESS GATE FAIL: $1"
  exit 1
}

echo "== v1 freshness gate: $APP =="
echo "base=$BASE wait=${WAIT}s max_learning_age=${MAX_LEARNING_AGE}s max_latency=${MAX_LEARNING_LATENCY}s"
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
print(f'  readiness status: {d.get(\"status\")}')
if mode == 'split_v2':
    print('FAIL: still on split_v2 — rollback to v1 first')
    sys.exit(1)
" || _fail "readiness worker_mode check failed"

echo "=== Check 3: data-freshness not stale (bounded wait ${WAIT}s) ==="
fresh_ok=0
elapsed=0
fresh_body=""
while [ "$elapsed" -lt "$WAIT" ]; do
  fresh_body=$(curl -fsS --max-time 15 "$BASE/api/data-freshness" 2>/dev/null || echo '{}')
  stale=$(echo "$fresh_body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('stale','unknown'))" 2>/dev/null || echo unknown)
  count=$(echo "$fresh_body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('subnet_count',0))" 2>/dev/null || echo 0)
  last_sync=$(echo "$fresh_body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('last_sync','?'))" 2>/dev/null || echo ?)
  age=$(echo "$fresh_body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('age_seconds','?'))" 2>/dev/null || echo ?)
  echo "  stale=$stale subnet_count=$count age_seconds=$age last_sync=$last_sync (${elapsed}s)"
  if [ "$stale" = "False" ] && [ "$count" != "0" ]; then
    fresh_ok=1
    break
  fi
  sleep "$INTERVAL"
  elapsed=$((elapsed + INTERVAL))
done
[ "$fresh_ok" = "1" ] || _fail "data-freshness still stale after ${WAIT}s"

echo "$fresh_body" | python3 -c "
import json,sys
d=json.load(sys.stdin)
boot=d.get('boot_status') or {}
if boot:
    print(f'  live_subnets boot_status: phase={boot.get(\"phase\")} ok={boot.get(\"ok\")} reason={boot.get(\"reason\")}')
    if boot.get('ok') is False and boot.get('reason'):
        print('FAIL: live_subnets boot reported failure — v1 capacity/sync problem')
        sys.exit(1)
" || _fail "live_subnets boot_status check failed"

echo "=== Check 4: app /metrics scheduler signals ==="
metrics=$(curl -fsS --max-time 10 "$BASE/metrics" 2>/dev/null || echo "")
if [ -n "$metrics" ]; then
  echo "$metrics" | grep -E '^subnet_sync_last_ok |^subnet_scheduler_running|^subnet_scheduler_failures' | head -10 | sed 's/^/  /' || true
  sync_ok=$(echo "$metrics" | awk '/^subnet_sync_last_ok / {print $2; exit}')
  if [ "$sync_ok" = "0.0" ] || [ "$sync_ok" = "0" ]; then
    worker_alive=$(curl -fsS --max-time 15 "$BASE/api/ops/readiness" 2>/dev/null | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('true' if (d.get('worker_peer') or {}).get('alive') is True else 'false')
except Exception:
    print('false')
" || echo false)
    fresh_ok=$(echo "$fresh_body" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('true' if d.get('stale') is False and (d.get('subnet_count') or 0) != 0 else 'false')
except Exception:
    print('false')
" || echo false)
    if [ "$worker_alive" = "true" ] && [ "$fresh_ok" = "true" ]; then
      echo "  subnet_sync_last_ok=0 is web-local; worker heartbeat and shared cache are healthy"
    else
      echo "  WARN/FAIL: subnet_sync_last_ok=0 with no healthy worker-backed cache"
      _fail "subnet_sync_last_ok=0 on v1 — worker-backed sync path unhealthy"
    fi
  fi
else
  echo "  WARN: /metrics unavailable — skipping scheduler gauge check"
fi

echo "=== Check 5: learning-health (status, latency, scheduler ticks) ==="
lh_tmp="$(mktemp)"
lh_meta=$(curl -sS -m 30 -w "%{http_code} %{time_total}" -o "$lh_tmp" "$BASE/api/learning/health" 2>/dev/null || echo "000 0")
lh_code=$(echo "$lh_meta" | awk '{print $1}')
lh_secs=$(echo "$lh_meta" | awk '{print $2}')
lh_ms=$(python3 -c "print(int(float('${lh_secs}')*1000))" 2>/dev/null || echo "?")
echo "  learning-health HTTP $lh_code latency=${lh_ms}ms (max ${MAX_LEARNING_LATENCY}s)"
if [ "$lh_code" != "200" ]; then
  rm -f "$lh_tmp"
  _fail "learning-health returned HTTP $lh_code"
fi
if [ "$lh_ms" != "?" ] && [ "$lh_ms" -gt $((MAX_LEARNING_LATENCY * 1000)) ]; then
  rm -f "$lh_tmp"
  _fail "learning-health latency ${lh_ms}ms exceeds ${MAX_LEARNING_LATENCY}s — v1 HTTP starvation"
fi

LH_FILE="$lh_tmp" MAX_LEARNING_HEALTH_AGE_SECONDS="$MAX_LEARNING_AGE" python3 - <<'PY' || { rm -f "$lh_tmp"; _fail "learning-health semantic check failed"; }
import json, os, sys
from datetime import datetime, timezone

path = os.environ["LH_FILE"]
max_age = float(os.environ.get("MAX_LEARNING_HEALTH_AGE_SECONDS", "900"))
with open(path, encoding="utf-8") as fh:
    d = json.load(fh)

status = d.get("status")
print(f"  learning-health status: {status}")
if status not in ("ok", "live"):
    print(f"FAIL: learning-health is {status!r} (need ok/live) — v1 baseline not recovered")
    if status == "degraded":
        print("  >>> buried finding: treat as prod capacity problem, not 'expected before soak'")

resolver = d.get("resolver") or {}
print(f"  resolver running: {resolver.get('running')} last_ok: {resolver.get('last_ok')}")

pick = d.get("pick_scheduler") or {}
daily = pick.get("daily") or {}
last_tick = pick.get("last_tick") or {}
print(f"  daily pick last_run_ok: {daily.get('last_run_ok')} error: {daily.get('last_run_error')!r}")
print(f"  daily pick reason: {(d.get('daily_pick') or {}).get('reason')!r}")

if daily.get("last_run_error") and "timed out" in str(daily.get("last_run_error")).lower():
    print("FAIL: daily pick scheduler timeout on v1 — live capacity problem")
    sys.exit(1)
if last_tick.get("ok") is False and last_tick.get("error"):
    print(f"  last_tick error: {last_tick.get('error')!r}")
    if "timed out" in str(last_tick.get("error")).lower():
        print("FAIL: pick scheduler last_tick timeout on v1")
        sys.exit(1)
if resolver.get("running") is False:
    print("FAIL: resolver scheduler not running on v1")
    sys.exit(1)

tick = d.get("last_resolver_tick") or resolver.get("last_tick")
if tick:
    ts = datetime.fromisoformat(str(tick).replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
    print(f"  resolver tick age: {int(age)}s (max {int(max_age)}s)")
    if age > max_age:
        print("FAIL: resolver tick too stale")
        sys.exit(1)
else:
    print("  resolver tick: (none reported)")
    print("FAIL: no resolver tick on v1 — learning loop not healthy")
    sys.exit(1)

if status != "ok":
    sys.exit(1)
PY
rm -f "$lh_tmp"

echo ""
echo "== V1 FRESHNESS GATE PASSED =="
echo "  v1 baseline looks healthy — buried capacity concern ruled out for now."
