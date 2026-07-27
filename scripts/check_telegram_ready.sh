#!/usr/bin/env bash
# Telegram message-intel readiness (API id/hash in Fly is not enough — need session file).
set -euo pipefail

BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"

echo "== message-intel status ($BASE) =="
curl -fsS --max-time 20 "$BASE/api/message-intel/status" | python3 -c "
import json, sys

d = json.load(sys.stdin)
listener = d.get('listener') or {}
outcomes = d.get('outcomes') or {}
store = d.get('store') or {}

print('listener.reason:', listener.get('reason'))
print('listener.live:', listener.get('live'))
print('has_creds:', listener.get('has_creds'))
print('has_session:', listener.get('has_session'))
print('worker_heavy:', listener.get('worker_heavy'))
print('hint:', listener.get('hint'))
print('store.total_messages:', store.get('total_messages'))
print('outcomes:', outcomes)

reason = listener.get('reason')
if listener.get('live'):
    print('OK — Telegram listener live')
    sys.exit(0)
if reason == 'missing_session' and listener.get('has_creds'):
    print('NEXT — bootstrap locally, paste TELEGRAM_SESSION_STRING (see DEPLOY.md)')
    print('      python scripts/bootstrap_telegram_session.py')
    print('      flyctl secrets set TELEGRAM_SESSION_STRING=\'<whole line>\' MESSAGE_INTEL_LISTENER=auto WORKER_HEAVY=essential --app subnet-dashboard')
    sys.exit(1)
if reason == 'disabled':
    print('NEXT — flyctl secrets set MESSAGE_INTEL_LISTENER=auto WORKER_HEAVY=essential --app subnet-dashboard')
    sys.exit(1)
if reason == 'idle_not_started':
    print('WAIT — listener defers ~2min after worker boot; re-run this script')
    sys.exit(1)
print('WARN — listener not live:', reason)
sys.exit(1)
"
