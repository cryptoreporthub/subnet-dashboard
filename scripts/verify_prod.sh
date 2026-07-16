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
print('sample_size:', d.get('sample_size'))
print('council win_rate:', c.get('win_rate'))
print('oracle win_rate:', o.get('win_rate'))
cal=o.get('calibration') or []
hi=[b for b in cal if b.get('count',0)>0 and b.get('score_lo',0)>=0.55]
if hi:
    w=sum(b['count']*b['hit_rate'] for b in hi)
    n=sum(b['count'] for b in hi)
    print('oracle filtered>=0.55 hit_rate:', round(w/n,4), 'n=', n)
"

echo "OK"

if [ -n "${CUSTOM_DOMAIN:-}" ]; then
  echo "== custom domain ($CUSTOM_DOMAIN) =="
  curl -fsS "https://${CUSTOM_DOMAIN}/health"
  echo
fi
