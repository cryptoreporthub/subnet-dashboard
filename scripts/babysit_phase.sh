#!/usr/bin/env bash
# Post-audit phased deploy babysit — run after each phase merge.
set -euo pipefail

BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"
PHASE="${1:-all}"

echo "== babysit phase=$PHASE base=$BASE =="

health_ok=0
for i in 1 2 3; do
  if curl -fsS --max-time 8 -o /dev/null -w "" "$BASE/health" 2>/dev/null; then
    health_ok=$((health_ok + 1))
    curl -fsS --max-time 8 -w "health $i: %{http_code} %{time_total}s\n" -o /dev/null "$BASE/health" || true
  else
    echo "health $i: FAILED"
  fi
  sleep 2
done
echo "health summary: $health_ok/3"
[ "$health_ok" -ge 2 ] || { echo "ABORT: /health unstable"; exit 1; }

curl -fsS --max-time 8 "$BASE/api/ops/live" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('status') in ('ok','degraded'), d
wp=d.get('worker_peer') or {}
print('ops/live:', d.get('status'), 'worker_alive=', wp.get('alive'))
"

case "$PHASE" in
  a|A|ops|all)
    echo "== Phase A: ops =="
    code=$(curl -sS -m 8 -o /dev/null -w "%{http_code}" "$BASE/metrics" 2>/dev/null || echo 000)
    echo "metrics: HTTP $code (404 ok if ENABLE_METRICS=0)"
    curl -sS -m 8 -D - -o /dev/null "$BASE/health" 2>/dev/null | grep -iE 'x-content-type|strict-transport' || echo "WARN: security headers missing on /health"
    ;;
esac

case "$PHASE" in
  b|B|outcome|all)
    echo "== Phase B: outcome loop =="
    curl -fsS --max-time 12 "$BASE/api/message-intel/status" | python3 -c "
import json,sys
d=json.load(sys.stdin)
o=d.get('outcomes') or {}
print('outcomes:', o)
assert o.get('running') or o.get('live'), 'outcome loop not running'
"
    ;;
esac

case "$PHASE" in
  c|C|worker|all)
    echo "== Phase C: worker split =="
    curl -fsS --max-time 15 "$BASE/api/ops/readiness" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('worker_mode:', d.get('worker_mode'))
print('worker_peer:', d.get('worker_peer'))
wp=d.get('worker_peer') or {}
if wp.get('expected') and not wp.get('alive'):
    print('WARN: worker_peer not alive — volume may still be on web')
"
    for i in 1 2 3; do
      curl -fsS --max-time 10 -w "pump-alerts $i: %{http_code} %{time_total}s\n" -o /dev/null "$BASE/api/pump-alerts" || echo "pump-alerts $i: FAIL"
    done
    ;;
esac

case "$PHASE" in
  d|D|security|all)
    echo "== Phase D: security =="
    curl -sS -m 8 -D - -o /dev/null "$BASE/" 2>/dev/null | grep -iE 'content-security|x-content-type' || echo "WARN: CSP/nosniff check"
    ;;
esac

case "$PHASE" in
  e|E|w4|summary|all)
    echo "== Phase E: W4 24h summary =="
    curl -fsS --max-time 12 "$BASE/api/message-intel?limit=1" | python3 -c "
import json,sys
d=json.load(sys.stdin)
s=(d.get('meta') or {}).get('summary_24h')
print('summary_24h:', 'present' if s else 'missing (ok pre-W4)')
"
    curl -fsS --max-time 12 "$BASE/" | grep -q 'message-intel__summary-24h' && echo "HTML summary strip: present" || echo "HTML summary strip: absent (pre-W4)"
    ;;
esac

case "$PHASE" in
  f|F|w5|filters|all)
    echo "== Phase F: W5 filters =="
    grep -q 'message-intel-filter' static/js/message_intel_feed.js 2>/dev/null && echo "filter JS: present" || echo "filter JS: absent (pre-W5)"
    ;;
esac

case "$PHASE" in
  telegram|tg|all)
    echo "== Telegram desk =="
    curl -fsS --max-time 12 "$BASE/api/message-intel?limit=1" | python3 -c "
import json,sys
d=json.load(sys.stdin)
m=d.get('meta') or {}
p=m.get('telegram_proof') or {}
print('telegram_proof:', p.get('hit_rate'), p.get('graded'), 'ready=', p.get('ready'))
print('hc_strip:', len(m.get('high_conviction_strip') or []))
"
    ;;
esac

case "$PHASE" in
  la|LA|hero|all)
    echo "== Phase LA: hero source-of-truth =="
    for i in 1 2 3; do
      curl -fsS --max-time 12 "$BASE/api/daily-pick" | python3 -c "
import json,sys
d=json.load(sys.stdin)
act=str(d.get('action') or 'HOLD').upper()
assert act in ('LONG','HOLD','SHORT'), act
ga=d.get('generated_at') or d.get('timestamp_utc')
print('daily-pick action=', act, 'generated_at=', 'yes' if ga else 'no')
" || echo "daily-pick $i: FAIL"
    done
    curl -fsS --max-time 12 "$BASE/api/data-freshness" | python3 -c "
import json,sys
d=json.load(sys.stdin)
src=d.get('effective_source') or d.get('source') or ''
print('data-freshness effective_source:', src or '(empty)')
assert src, 'missing effective_source'
"
    html=$(curl -fsS --max-time 15 "$BASE/")
    echo "$html" | grep -q 'k3-action-badge' && echo "hero badge: present" || echo "WARN: k3-action-badge missing"
    echo "$html" | grep -q 'k3-call-headline' && echo "hero headline: present" || echo "WARN: k3-call-headline missing"
    ;;
esac

case "$PHASE" in
  lb|LB|integrations|pulse|all)
    echo "== Phase LB: integrations + pulse rail =="
    curl -fsS --max-time 15 "$BASE/api/subnet-integrations" | python3 -c "
import json,sys
d=json.load(sys.stdin)
rows=d.get('integrations') or []
connected=d.get('connected_count', 0)
print('integrations:', connected, '/', d.get('integration_total', len(rows)))
chutes=next((r for r in rows if r.get('slug')=='chutes'), {})
print('chutes:', chutes.get('status'), chutes.get('detail','')[:60])
assert len(rows) >= 4, rows
"
    html=$(curl -fsS --max-time 15 "$BASE/")
    echo "$html" | grep -q 'subnet-int-strip\|subnet-integrations-bar' && echo "integrations strip SSR: present" || echo "WARN: integrations strip missing in HTML"
    echo "$html" | grep -q 'section-market-pulse' && echo "market pulse: present" || echo "WARN: market pulse missing"
    echo "$html" | grep -qi 'built on bittensor' && echo "brand line: present" || echo "WARN: Built on Bittensor line missing"
    ;;
esac

echo "== babysit phase=$PHASE OK =="
