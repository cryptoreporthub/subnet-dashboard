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
    echo "$html" | grep -q 'data-generated-at' && echo "hero SSR meta: present" || echo "WARN: data-generated-at missing"
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
print('chutes:', chutes.get('status'), (chutes.get('detail') or '')[:60])
assert len(rows) >= 4, rows
"
    html=$(curl -fsS --max-time 15 "$BASE/")
    echo "$html" | grep -q 'subnet-int-strip' && echo "integrations strip SSR: present" || echo "WARN: integrations strip missing"
    echo "$html" | grep -q 'sr-pulse-ribbon' && echo "pulse ribbon: present" || echo "WARN: pulse ribbon missing"
    echo "$html" | grep -qi 'built on bittensor' && echo "brand line: present" || echo "WARN: Built on Bittensor missing"
    echo "$html" | grep -q 'sr-pulse__oneline' && echo "compact pulse: present" || echo "WARN: oneline pulse missing"
  ;;
esac

case "$PHASE" in
  lc|LC|legal|trust|seo|all|sprint)
    echo "== Phase LC: legal / trust / SEO =="
    code=$(curl -sS -m 8 -o /dev/null -w "%{http_code}" "$BASE/robots.txt" 2>/dev/null || echo 000)
    echo "robots.txt: HTTP $code"
    [ "$code" = "200" ] || echo "WARN: robots.txt not 200"
    html=$(curl -fsS --max-time 15 "$BASE/" 2>/dev/null || true)
    echo "$html" | grep -qi 'not financial advice' && echo "NFA disclaimer: present" || echo "WARN: NFA disclaimer missing"
    echo "$html" | grep -q 'og-share.png\|og:image' && echo "og:image: present" || echo "WARN: og:image missing"
    curl -sS -m 8 -D - -o /dev/null "$BASE/" 2>/dev/null | grep -iE 'content-security|strict-transport' || echo "WARN: security headers"
    ;;
esac

case "$PHASE" in
  ld|LD|surface|honesty|all|sprint)
    echo "== Phase LD: surface honesty =="
    html=$(curl -fsS --max-time 15 "$BASE/" 2>/dev/null || true)
    if echo "$html" | grep -q 'id="habit-alert-btn"'; then
      if echo "$html" | grep -q 'data-enabled="0"'; then
        echo "$html" | grep -q 'habit-alert-btn.*hidden\|display:\s*none' && echo "alerts btn: hidden when disabled" || echo "WARN: alert btn visible while disabled"
      else
        echo "alerts btn: present (enabled deploy)"
      fi
    else
      echo "alerts btn: absent (ok when disabled)"
    fi
    curl -fsS --max-time 12 -o /dev/null -w "portfolio/status: %{http_code}\n" "$BASE/api/portfolio/status" 2>/dev/null || echo "WARN: portfolio/status failed"
    curl -fsS --max-time 12 "$BASE/api/daily-pick" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('daily-pick action=', str(d.get('action') or 'HOLD').upper())
" || echo "WARN: daily-pick failed"
    ;;
esac

case "$PHASE" in
  acc0|ACC0|acc-0|all|sprint)
    echo "== Phase Acc-0: ledger plumbing =="
    case "$PHASE" in acc0|ACC0|acc-0) export BABYSIT_STRICT_ACC0=1 ;; *) export BABYSIT_STRICT_ACC0=0 ;; esac
    curl -fsS --max-time 12 "$BASE/api/learning/health" | python3 -c "
import json,sys,os
d=json.load(sys.stdin)
lg=d.get('ledger') or {}
strict=os.environ.get('BABYSIT_STRICT_ACC0')=='1'
print('status=', d.get('status'), 'ledger.gap=', lg.get('gap'), 'required=', lg.get('required'))
if lg.get('required') and lg.get('gap'):
    if strict:
        raise SystemExit('ledger gap still true for published LONG')
    print('WARN: ledger gap (Acc-0 not shipped or heal pending)')
"
    ;;
esac

case "$PHASE" in
  acc1|ACC1|acc-1|all|sprint)
    echo "== Phase Acc-1: archive measurement =="
    curl -fsS --max-time 12 "$BASE/api/ops/evidence" | python3 -c "
import json,sys; d=json.load(sys.stdin); print('ops/evidence:', d.get('status', 'ok'))
"
    test -f scripts/measure_accuracy_archive.py && echo "archive script: present" || echo "WARN: measure_accuracy_archive.py missing (local/PR artifact)"
    ;;
esac

case "$PHASE" in
  acc2|ACC2|acc-2|all|sprint)
    echo "== Phase Acc-2: accuracy experiment =="
    curl -fsS --max-time 12 "$BASE/api/learning/stats" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('graded=', d.get('graded'), 'accuracy=', d.get('accuracy'))
"
    curl -fsS --max-time 12 "$BASE/api/daily-pick" | python3 -c "
import json,sys
d=json.load(sys.stdin)
pred=d.get('prediction') or {}
print('horizon_hours=', pred.get('horizon_hours'), 'action=', d.get('action'))
"
    ;;
esac

case "$PHASE" in
  pp0|PP0|pp-0|all|sprint)
    echo "== Phase PP-0: segment ledger =="
    curl -fsS --max-time 12 "$BASE/api/pump-patterns/15" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('segments=', len(d.get('segments') or []), 'waveform=', 'yes' if d.get('waveform') else 'no')
" || echo "WARN: /api/pump-patterns/15 not live yet"
    ;;
esac

case "$PHASE" in
  pp1|PP1|pp-1|all|sprint)
    echo "== Phase PP-1: pattern classes =="
    curl -fsS --max-time 12 "$BASE/api/pump-patterns/15" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('pattern_class=', d.get('pattern_class'), 'label=', (d.get('pattern_label') or '')[:40])
" 2>/dev/null || echo "WARN: pattern API not live yet"
    ;;
esac

case "$PHASE" in
  pp2|PP2|pp-2|all|sprint)
    echo "== Phase PP-2: pump desk + council surfaces =="
    html=$(curl -fsS --max-time 15 "$BASE/pump-desk" 2>/dev/null || curl -fsS --max-time 15 "$BASE/")
    echo "$html" | grep -q 'pump-pattern' && echo "pattern chip: present" || echo "WARN: pump-pattern chip missing"
    curl -fsS --max-time 12 "$BASE/api/pump-patterns/active" 2>/dev/null | python3 -c "
import json,sys; d=json.load(sys.stdin); print('active patterns:', len(d.get('items') or []))
" || echo "WARN: /api/pump-patterns/active not live yet"
    ;;
esac

case "$PHASE" in
  fq4|FQ4|finish|all|sprint)
    echo "== Phase FQ-4: combined angles effectiveness =="
    case "$PHASE" in fq4|FQ4|finish) export BABYSIT_STRICT_FQ4=1 ;; *) export BABYSIT_STRICT_FQ4=0 ;; esac
    curl -fsS --max-time 12 "$BASE/api/learning/stats" | python3 -c "
import json,sys,os
d=json.load(sys.stdin)
g=d.get('graded', 0) or 0
strict=os.environ.get('BABYSIT_STRICT_FQ4')=='1'
print('graded=', g)
if int(g) <= 0:
    if strict:
        raise SystemExit('graded still 0 — Slice 4 blocked')
    print('WARN: graded=0 (FQ-4 blocked until picks resolve)')
"
    curl -fsS --max-time 12 "$BASE/api/ops/evidence" | python3 -c "
import json,sys
d=json.load(sys.stdin)
ca=d.get('combined_angles') or {}
print('ops/evidence keys:', list(d.keys())[:10])
print('combined_angles:', 'present' if ca else 'missing')
if ca:
    ps=ca.get('pick_source') or {}
    print('pick_source buckets:', list(ps.keys()))
"
    ;;
esac

case "$PHASE" in
  sprint|SPRINT)
    echo "== Sprint rollup: LA LB C LC LD Acc PP =="
    ;;
esac

echo "== babysit phase=$PHASE OK =="
