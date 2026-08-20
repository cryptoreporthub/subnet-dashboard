#!/usr/bin/env bash
# One soak probe tick: health latency, proxy/metrics signals, optional CPU/RSS snapshot.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
BASE="${APP_BASE_URL:-https://${APP}.fly.dev}"
PROBE_N="${SOAK_PROBE_N:-0}"
SAMPLES="${SOAK_SAMPLES_LOG:-soak_samples.jsonl}"
PORT="${WORKER_HTTP_PORT:-8081}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
epoch="$(date +%s)"

web_code_only="000"
web_ms=""
web_raw=$(curl -sS -m 10 -o /dev/null -w "%{http_code} %{time_total}" "$BASE/health" 2>/dev/null || echo "000 0")
web_code_only=$(echo "$web_raw" | awk '{print $1}')
web_s=$(echo "$web_raw" | awk '{print $2}')
web_ms=$(python3 -c "print(int(float('${web_s}')*1000))" 2>/dev/null || echo "")

worker_code=""
worker_ms=""
alive=""
probe_rc=1
if [ -x "$SCRIPT_DIR/fly_probe_worker_from_web.sh" ]; then
  probe_out="$(mktemp)"
  set +e
  FLY_APP="$APP" "$SCRIPT_DIR/fly_probe_worker_from_web.sh" > "$probe_out" 2>&1
  probe_rc=$?
  set -e
  grep -qE "OK 200 http://${APP}\\.flycast:${PORT}/health" "$probe_out" && worker_code=200 || true
  if grep -qE '"alive"[[:space:]]*:[[:space:]]*true' "$probe_out"; then
    alive=true
  else
    alive=false
  fi
  rm -f "$probe_out"
fi

WEB_ID="$(flyctl machines list -a "$APP" --json 2>/dev/null | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    meta=(m.get('config') or {}).get('metadata') or {}
    pg=(meta.get('fly_process_group') or 'web').lower()
    if pg=='web' and m.get('id'):
        print(m['id']); break
" 2>/dev/null || true)"
if [ -n "$WEB_ID" ]; then
  wc=$(flyctl machine exec -a "$APP" "$WEB_ID" --timeout 25 \
    "curl -sS -m 5 -o /dev/null -w '%{http_code} %{time_total}' http://${APP}.flycast:${PORT}/health" 2>/dev/null || echo "000 0")
  worker_code=$(echo "$wc" | awk '{print $1}')
  ws=$(echo "$wc" | awk '{print $2}')
  worker_ms=$(python3 -c "print(int(float('${ws}')*1000))" 2>/dev/null || echo "")
fi

readiness=$(curl -fsS --max-time 15 "$BASE/api/ops/readiness" 2>/dev/null || echo '{}')
peer_alive=$(echo "$readiness" | python3 -c "import json,sys; d=json.load(sys.stdin); v=(d.get('worker_peer') or {}).get('alive'); print('true' if v is True else ('false' if v is False else 'null'))" 2>/dev/null || echo "null")
worker_mode=$(echo "$readiness" | python3 -c "import json,sys; print(json.load(sys.stdin).get('worker_mode') or '')" 2>/dev/null || echo "")

metrics_snip=""
metrics_tmp="$(mktemp)"
if curl -fsS --max-time 8 "$BASE/metrics" -o "$metrics_tmp" 2>/dev/null; then
  metrics_snip=$(grep -E 'subnet_scheduler_failures|subnet_sync_last_ok|http_request' "$metrics_tmp" 2>/dev/null | head -15 | tr '\n' ';' || true)
fi
rm -f "$metrics_tmp"

rss_kb=""
cpu_pct=""
WORKER_ID="$(flyctl machines list -a "$APP" --json 2>/dev/null | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    meta=(m.get('config') or {}).get('metadata') or {}
    pg=(meta.get('fly_process_group') or '').lower()
    if pg=='worker' and m.get('id'):
        print(m['id']); break
" 2>/dev/null || true)"
if [ -n "$WORKER_ID" ]; then
  ps_line=$(flyctl machine exec -a "$APP" "$WORKER_ID" --timeout 30 \
    "ps -o pcpu=,rss= -C python3 2>/dev/null | head -5" 2>/dev/null || true)
  rss_kb=$(echo "$ps_line" | awk '{sum+=$2} END {print sum+0}')
  cpu_pct=$(echo "$ps_line" | awk '{sum+=$1} END {print sum+0}')
fi

export SAMPLE_TS="$ts" SAMPLE_EPOCH="$epoch" SAMPLE_PROBE="$PROBE_N"
export SAMPLE_WEB_MS="$web_ms" SAMPLE_WEB_CODE="$web_code_only"
export SAMPLE_WORKER_MS="$worker_ms" SAMPLE_WORKER_CODE="$worker_code"
export SAMPLE_PROBE_RC="$probe_rc" SAMPLE_ALIVE="$alive"
export SAMPLE_PEER_ALIVE="$peer_alive" SAMPLE_WORKER_MODE="$worker_mode"
export SAMPLE_RSS="$rss_kb" SAMPLE_CPU="$cpu_pct" SAMPLE_METRICS="$metrics_snip"

python3 - <<'PY' >> "$SAMPLES"
import json, os

def opt_int(key):
    v = os.environ.get(key, "").strip()
    return int(v) if v.isdigit() or (v.startswith("-") and v[1:].isdigit()) else None

def opt_float(key):
    v = os.environ.get(key, "").strip()
    try:
        return float(v) if v else None
    except ValueError:
        return None

alive_raw = os.environ.get("SAMPLE_ALIVE", "")
if alive_raw == "true":
    alive = True
elif alive_raw == "false":
    alive = False
else:
    alive = None

peer_raw = os.environ.get("SAMPLE_PEER_ALIVE", "null")
if peer_raw == "true":
    peer = True
elif peer_raw == "false":
    peer = False
else:
    peer = None

row = {
    "ts": os.environ["SAMPLE_TS"],
    "epoch": int(os.environ["SAMPLE_EPOCH"]),
    "probe": int(os.environ.get("SAMPLE_PROBE", "0")),
    "web_health_ms": opt_int("SAMPLE_WEB_MS"),
    "web_health_code": os.environ.get("SAMPLE_WEB_CODE", ""),
    "worker_flycast_ms": opt_int("SAMPLE_WORKER_MS"),
    "worker_flycast_code": os.environ.get("SAMPLE_WORKER_CODE", ""),
    "flycast_probe_rc": int(os.environ.get("SAMPLE_PROBE_RC", "1")),
    "flycast_alive": alive,
    "readiness_peer_alive": peer,
    "worker_mode": os.environ.get("SAMPLE_WORKER_MODE", ""),
    "worker_rss_kb_sum": opt_int("SAMPLE_RSS"),
    "worker_cpu_pct_sum": opt_float("SAMPLE_CPU"),
    "metrics_snip": os.environ.get("SAMPLE_METRICS", ""),
}
print(json.dumps(row, separators=(",", ":")))
PY

echo "[$ts] sample probe=$PROBE_N web_health_ms=${web_ms} worker_flycast_ms=${worker_ms} peer_alive=$peer_alive" >&2
