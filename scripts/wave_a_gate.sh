#!/usr/bin/env bash
# Wave A — automated prod gate (post-stability sprint).
# Human 390px sign-off still required separately (see post-stability-sprint-plan.md).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"
export APP_BASE_URL="$BASE"

echo "== Wave A gate @ $BASE =="

echo "-- local contract --"
PYTHONPATH="$ROOT" .venv/bin/pytest \
  tests/test_endpoint_contract.py \
  tests/test_reconnect_smoke.py \
  tests/test_prod_stability.py \
  -q

echo "-- G0 SSR + tier-1 APIs --"
bash scripts/g0_phone_qa.sh

echo "-- pump soak (5x, must not timeout) --"
for i in 1 2 3 4 5; do
  curl -fsS --max-time 8 -w "pump $i: %{http_code} %{time_total}s\n" -o /tmp/wave_a_pump.json "$BASE/api/pump-alerts"
done
python3 -c "
import json
d=json.load(open('/tmp/wave_a_pump.json'))
assert d.get('status') != 'timeout', d
print('pump final: status=%s count=%s' % (d.get('status'), d.get('count')))
"

echo "-- health burst (10x) --"
for i in $(seq 1 10); do
  curl -fsS --max-time 5 -w "health $i: %{http_code} %{time_total}s\n" -o /dev/null "$BASE/health"
done

echo "-- verify_prod (soft SSE) --"
bash scripts/verify_prod.sh

echo ""
echo "Wave A automated gate: PASS"
echo "Remaining: human 390px sign-off (Call → Pump desk → horizon path)"
