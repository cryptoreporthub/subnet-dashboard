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
