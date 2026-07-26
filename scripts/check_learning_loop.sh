#!/usr/bin/env bash
# Learning loop settle check (pick → ledger → resolver → snapshots).
set -euo pipefail

BASE="${APP_BASE_URL:-https://subnet-dashboard.fly.dev}"

echo "== learning loop health ($BASE) =="
curl -fsS --max-time 25 "$BASE/api/learning/health" | python3 -c "
import json, sys

d = json.load(sys.stdin)
print('status:', d.get('status'))
print('pending:', d.get('pending'))
print('resolver.running:', (d.get('resolver') or {}).get('running'))
print('resolver.age_seconds:', (d.get('resolver') or {}).get('age_seconds'))
print('worker_peer.alive:', (d.get('worker_peer') or {}).get('alive'))
print('snapshot_age_seconds:', d.get('snapshot_age_seconds'))
ss = d.get('score_snapshot') or {}
print('score_snapshot.file_present:', ss.get('file_present'))
lc = ss.get('last_cycle') or {}
print('score_snapshot.last_cycle.run_at:', lc.get('run_at'))
print('watchdog.warning:', (d.get('watchdog') or {}).get('warning'))
print('daily_pick.action:', (d.get('daily_pick') or {}).get('action'))

status = d.get('status')
snap = d.get('snapshot_age_seconds')
peer = (d.get('worker_peer') or {}).get('alive')
res_running = (d.get('resolver') or {}).get('running')

if status == 'ok':
    print('OK — learning loop healthy')
    if snap is None:
        print('NOTE — score snapshot not written yet; wait ~5min after worker boot')
    sys.exit(0)
if status == 'degraded':
    print('WARN — degraded (often post-restart; resolver catching up)')
    sys.exit(0)
if not peer:
    print('FAIL — inline worker not alive; check data/.worker_heartbeat')
    sys.exit(1)
if status == 'stalled':
    print('WARN — stalled; check resolver tick and pending watchdog')
    sys.exit(1)
print('WARN — unexpected status:', status)
sys.exit(1)
"
