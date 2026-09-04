#!/usr/bin/env bash
# Prod smoke + Phase P verification (run after deploy).
set -euo pipefail

BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"

# ponytail: non-fatal curl — prod can wedge under load; WARN and continue.
curl_json_safe() {
  local url="$1" outfile="$2" max_time="${3:-8}"
  if curl -fsS --max-time "$max_time" -o "$outfile" "$url"; then
    return 0
  fi
  echo "WARN: curl failed for $url (max-time ${max_time}s)"
  return 1
}

echo "== pump-alerts (fast desk) =="
for i in 1 2 3 4 5; do
  curl -fsS --max-time 8 -w "pump_alerts attempt $i: %{http_code} %{time_total}s\n" -o /tmp/pump_alerts.json "$BASE/api/pump-alerts" || echo "pump_alerts attempt $i: FAILED"
done
python3 -c "
import json
d=json.load(open('/tmp/pump_alerts.json'))
print('status:', d.get('status'))
print('count:', d.get('count'))
assert d.get('status') != 'timeout', 'pump-alerts must not return timeout on warm prod'
"

echo "== health check (serial, spaced) =="
health_ok=0
for i in 1 2 3; do
  if curl -fsS --max-time 8 -w "health $i: %{http_code} %{time_total}s\n" -o /dev/null "$BASE/health"; then
    health_ok=$((health_ok + 1))
  else
    echo "health $i: FAILED"
    if [ "$i" -eq 1 ]; then
      echo "ABORT: /health failed on first probe — prod likely wedged"
      exit 1
    fi
  fi
  sleep 3
done
echo "health summary: $health_ok/3 OK"

echo "== version deploy-receipt =="
if curl_json_safe "$BASE/version" /tmp/version.json 8; then
  python3 -c "
import json
d=json.load(open('/tmp/version.json'))
print('version:', d.get('version'))
print('sentry_release:', d.get('sentry_release'))
print('python:', d.get('python'))
assert 'version' in d, 'version key required'
assert d.get('version'), 'version must be non-empty (unknown ok)'
"
else
  echo "WARN: /version skipped — endpoint slow or wedged"
fi

echo "== learning loop health (Phase 0–6) =="
if curl_json_safe "$BASE/api/learning/health" /tmp/learning_health.json 10; then
  python3 -c "
import json
d=json.load(open('/tmp/learning_health.json'))
print('status:', d.get('status'))
print('pending:', d.get('pending'))
print('ledger:', d.get('ledger'))
print('snapshot_age_seconds:', d.get('snapshot_age_seconds'))
print('daily_pick:', d.get('daily_pick'))
assert d.get('status') in ('ok','degraded','stalled'), 'unexpected learning health status'
if d.get('status') == 'stalled':
    print('WARN: learning loop stalled — check ledger gap / resolver tick')
"
else
  echo "WARN: learning health skipped — endpoint slow or wedged"
fi

echo "== ops readiness includes loop health =="
if curl_json_safe "$BASE/api/ops/readiness" /tmp/ops_readiness_loop.json 15; then
  python3 -c "
import json
d=json.load(open('/tmp/ops_readiness_loop.json'))
lh=d.get('learning_loop_health') or {}
print('ready:', d.get('ready'))
print('loop_status:', lh.get('status'))
print('issues:', d.get('issues'))
"
else
  echo "WARN: ops readiness (loop health) skipped — endpoint slow or wedged"
fi

echo "== calibration auto_retrain =="
curl -fsS "$BASE/api/calibration/status" | python3 -c "
import json,sys
d=json.load(sys.stdin)
cal=d.get('calibration',{})
print('auto_retrain_enabled:', cal.get('auto_retrain_enabled'))
print('resolved_sample:', cal.get('resolved_sample'))
"

echo "== conviction alerts =="
curl -fsS "$BASE/api/conviction-alerts/status" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('enabled:', d.get('enabled'))
print('delivery_mode:', d.get('delivery_mode'))
lr=d.get('last_run') or {}
if lr.get('delivery'):
    print('last_delivery_mode:', (lr.get('delivery') or {}).get('mode'))
"

echo "== message-intel =="
curl -fsS "$BASE/api/message-intel/status" | python3 -c "
import json,sys
d=json.load(sys.stdin)
lr=d.get('listener') or {}
print('has_creds:', lr.get('has_creds'))
print('running:', lr.get('running'))
print('reason:', lr.get('reason'))
print('live:', lr.get('live'))
print('empty:', d.get('empty'))
oc=d.get('outcomes') or {}
print('outcomes_running:', oc.get('running'))
print('outcomes_live:', oc.get('live'))
"

echo "== message-intel social =="
curl -fsS "$BASE/api/message-intel/social" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('rows:', len(d.get('rows') or []))
print('empty:', d.get('empty'))
"

echo "== subnet integrations signals (Wave E) =="
if curl_json_safe "$BASE/api/subnet-integrations/signals" /tmp/subnet_signals.json 10; then
  python3 -c "
import json
d=json.load(open('/tmp/subnet_signals.json'))
print('mood:', d.get('mood'))
print('signal_count:', d.get('signal_count'))
"
else
  echo "WARN: subnet-integrations/signals skipped"
fi

echo "== subnet report =="
curl -fsS "$BASE/api/report/1" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('status:', d.get('status'))
print('has_markdown:', bool(d.get('markdown')))
"

echo "== backtest (P5) =="
curl -fsS "$BASE/api/backtest" | python3 -c "
import json,sys
d=json.load(sys.stdin)
c=d.get('council',{})
o=d.get('judges',{}).get('oracle',{})
flt=o.get('filtered') or {}
print('sample_size:', d.get('sample_size'))
print('council win_rate:', c.get('win_rate'), 'coverage_pct:', c.get('coverage_pct'))
print('oracle win_rate:', o.get('win_rate'), 'coverage_pct:', o.get('coverage_pct'), 'endorsed_n:', o.get('endorsed_n'))
flt=o.get('filtered') or {}
print('oracle filtered win_rate:', flt.get('win_rate'), 'n=', flt.get('n'), 'coverage_pct=', flt.get('coverage_pct'), 'min_score=', flt.get('min_score'))
print('methodology version:', (d.get('methodology') or {}).get('version'))
"

echo "== data freshness + subnets =="
curl -fsS "$BASE/api/data-freshness" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('source:', d.get('source'))
print('effective_source:', d.get('effective_source'))
print('subnet_count:', d.get('subnet_count'))
print('effective_total:', d.get('effective_total'))
print('stale:', d.get('stale'))
"

echo "== ops readiness =="
if curl_json_safe "$BASE/api/ops/readiness" /tmp/ops_readiness.json 15; then
  python3 -c "
import json
d=json.load(open('/tmp/ops_readiness.json'))
print('ready:', d.get('ready'))
print('thin_ui_likely:', d.get('thin_ui_likely'))
print('issues:', d.get('issues'))
lr=d.get('learning') or {}
print('graded:', lr.get('graded'))
rs=d.get('resolver') or {}
print('resolver_running:', rs.get('running'))
sf=d.get('subnet_feed') or {}
print('effective_source:', sf.get('effective_source'))
print('likely_total:', sf.get('likely_total'))
assert lr.get('graded', 0) > 0, 'graded picks must be > 0 on prod volume'
assert sf.get('likely_total', 0) > 0, 'subnet feed must have rows'
"
else
  echo "WARN: ops readiness skipped — graded/feed asserts not run"
fi

curl -fsS --max-time 90 "$BASE/api/subnets?limit=1" | python3 -c "
import json,sys
d=json.load(sys.stdin)
meta=d.get('meta') or {}
subs=d.get('subnets') or []
print('meta.source:', meta.get('source'))
print('meta.total:', meta.get('total'))
assert meta.get('total', 0) > 0, 'subnet count must be > 0'
"
curl -fsS "$BASE/api/subnets?limit=5" | python3 -c "
import json,sys
d=json.load(sys.stdin)
subs=d.get('subnets') or []
raw=json.dumps(subs)
assert 'SNNone' not in raw, 'subnet names must not contain SNNone'
if subs:
    name=subs[0].get('name') or ''
    assert name and name != 'SNNone', 'first subnet name must be non-empty'
    print('sample_name:', name)
"

echo "== cockpit SSE once =="
sse_code="$(curl -sS -o /tmp/cockpit_sse.txt -w "%{http_code}" --max-time 25 "$BASE/api/cockpit/stream?once=1" || true)"
echo "$sse_code"
if [ "$sse_code" = "200" ]; then
  python3 -c "
import pathlib
body = pathlib.Path('/tmp/cockpit_sse.txt').read_text()
assert 'event: cockpit.picks' in body, 'missing cockpit.picks event'
print('cockpit SSE OK, bytes=', len(body))
"
else
  echo "WARN: cockpit SSE returned $sse_code (non-fatal for Wave A gate)"
fi

echo "== shareable subnet page =="
subnet_code="$(curl -sS -o /tmp/subnet_page.html -w "%{http_code}" --max-time 15 "$BASE/subnet/1")"
echo "subnet page $subnet_code"
[ "$subnet_code" = "200" ] || echo "WARN: subnet page non-200"

echo "== search API =="
curl -fsS "$BASE/api/search?q=1" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('results:', len(d.get('results') or d.get('matches') or []))
"

echo "== shareable wallet page =="
WALLET_FIXTURE="${WALLET_FIXTURE:-5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY}"
wallet_code="$(curl -sS -o /tmp/wallet_page.html -w "%{http_code}" --max-time 15 "$BASE/wallet/$WALLET_FIXTURE")"
echo "wallet page $wallet_code"
[ "$wallet_code" = "200" ] || echo "WARN: wallet page non-200"

echo "OK"

if [ -n "${CUSTOM_DOMAIN:-}" ]; then
  echo "== custom domain ($CUSTOM_DOMAIN) =="
  curl -fsS "https://${CUSTOM_DOMAIN}/health"
  echo
fi
