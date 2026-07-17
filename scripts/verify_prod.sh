#!/usr/bin/env bash
# Prod smoke + Phase P verification (run after deploy).
set -euo pipefail

BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"

echo "== health =="
curl -fsS "$BASE/health"
echo

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
"

echo "== message-intel social =="
curl -fsS "$BASE/api/message-intel/social" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('rows:', len(d.get('rows') or []))
print('empty:', d.get('empty'))
"

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
print('council win_rate:', c.get('win_rate'))
print('oracle win_rate:', o.get('win_rate'))
print('oracle filtered win_rate:', flt.get('win_rate'), 'n=', flt.get('n'), 'min_score=', flt.get('min_score'))
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
curl -fsS "$BASE/api/ops/readiness" | python3 -c "
import json,sys
d=json.load(sys.stdin)
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
curl -fsS -o /dev/null -w "%{http_code}\n" "$BASE/api/cockpit/stream?once=1"

echo "== shareable subnet page =="
curl -fsS "$BASE/subnet/1" | head -c 200 >/dev/null
echo "subnet page OK"

echo "== search API =="
curl -fsS "$BASE/api/search?q=1" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('results:', len(d.get('results') or d.get('matches') or []))
"

echo "== shareable wallet page =="
WALLET_FIXTURE="${WALLET_FIXTURE:-5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY}"
curl -fsS "$BASE/wallet/$WALLET_FIXTURE" | head -c 200 >/dev/null
echo "wallet page OK"

echo "OK"

if [ -n "${CUSTOM_DOMAIN:-}" ]; then
  echo "== custom domain ($CUSTOM_DOMAIN) =="
  curl -fsS "https://${CUSTOM_DOMAIN}/health"
  echo
fi
