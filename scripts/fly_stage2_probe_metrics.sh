#!/usr/bin/env bash
# Pull Fly Prometheus CPU/memory for web machine around Stage 2 soak probes.
# Requires an org-scoped user token (NOT the app deploy token Cloud Agents use).
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
ORG="${FLY_ORG:-personal}"
WEB_ID="${WEB_MACHINE_ID:-d8939d7c597218}"
START="${METRICS_START:-2026-08-20T02:40:00Z}"
END="${METRICS_END:-2026-08-20T03:20:00Z}"
STEP="${METRICS_STEP:-60}"
TOKEN="${FLY_METRICS_TOKEN:-$(flyctl auth token 2>/dev/null | rg -o 'fm2_[^,\s]+' | head -1)}"

if [ -z "$TOKEN" ]; then
  echo "ABORT: no token — set FLY_METRICS_TOKEN or run flyctl auth token on a user session"
  exit 1
fi

prom_query() {
  local query="$1"
  curl -sS -G "https://api.fly.io/prometheus/${ORG}/api/v1/query_range" \
    --data-urlencode "query=${query}" \
    --data-urlencode "start=${START}" \
    --data-urlencode "end=${END}" \
    --data-urlencode "step=${STEP}" \
    -H "Authorization: FlyV1 ${TOKEN}"
}

echo "== Stage 2 probe metrics: app=$APP web=$WEB_ID org=$ORG =="
echo "window: $START → $END step=${STEP}s"
echo ""

LOAD_Q="fly_instance_load_average{app=\"${APP}\",instance=\"${WEB_ID}\",minutes=\"1\"}"
MEM_Q="fly_instance_memory_mem_total{app=\"${APP}\",instance=\"${WEB_ID}\"} - fly_instance_memory_mem_available{app=\"${APP}\",instance=\"${WEB_ID}\"}"
CPU_Q="sum(increase(fly_instance_cpu{app=\"${APP}\",instance=\"${WEB_ID}\",mode!=\"idle\",mode!=\"steal\"}[60s])) / sum(count(fly_instance_cpu{app=\"${APP}\",instance=\"${WEB_ID}\",mode=\"idle\"}) without (cpu_id, mode))"

run_metric() {
  local label="$1"
  local query="$2"
  echo "--- ${label} ---"
  resp="$(prom_query "$query")" || { echo "curl failed"; exit 1; }
  if [ -z "$resp" ]; then
    echo "empty Prometheus response"
    exit 1
  fi
  if echo "$resp" | grep -qi 'not authorized for org'; then
    echo "$resp"
    echo ""
    echo "HINT: deploy/app-scoped tokens return 403 here. Use a user org token:"
    echo "  flyctl auth token   # on your laptop, not Cloud Agent deploy token"
    echo "  FLY_METRICS_TOKEN=\$(flyctl auth token | rg -o 'fm2_[^,\\s]+' | head -1) $0"
    exit 2
  fi
  if echo "$resp" | grep -qi 'resolving organization'; then
    echo "$resp"
    echo "HINT: use Authorization: FlyV1 (not Bearer) and ORG slug from: flyctl orgs list"
    exit 2
  fi
  status="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('status','?'))" "$resp" 2>/dev/null || echo parse_error)"
  if [ "$status" = "parse_error" ]; then
    echo "non-JSON response: $(echo "$resp" | head -c 200)"
    exit 1
  fi
  if [ "$status" != "success" ]; then
    echo "$resp" | head -c 400
    exit 1
  fi
  python3 - <<'PY' "$resp" "$label"
import json, sys
payload = json.loads(sys.argv[1])
label = sys.argv[2]
series = payload.get("data", {}).get("result") or []
if not series:
    print(f"no data for {label}")
    sys.exit(0)
for s in series:
    pts = s.get("values") or []
    if not pts:
        continue
    vals = [float(v[1]) for v in pts if v[1] not in (None, "NaN")]
    if not vals:
        continue
    print(f"{label}: n={len(vals)} min={min(vals):.4f} max={max(vals):.4f} last={vals[-1]:.4f}")
    markers = {"probe1": 1755655471, "probe6": 1755657025, "probe7": 1755657337}
    by_ts = {int(float(t)): float(v) for t, v in pts}
    for name, ts in markers.items():
        nearest = min(by_ts.keys(), key=lambda t: abs(t - ts), default=None)
        if nearest is not None and abs(nearest - ts) <= 120:
            print(f"  near {name}: {by_ts[nearest]:.4f} @ {nearest}")
PY
}

run_metric "load_1m" "$LOAD_Q"
run_metric "mem_used_bytes" "$MEM_Q"
run_metric "cpu_busy_fraction" "$CPU_Q"

echo ""
echo "Done. Compare probe7 vs probe1-6 max/spike before choosing soak Option A vs B."
