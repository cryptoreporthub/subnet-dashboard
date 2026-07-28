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
resolver = d.get('resolver') or {}
print('resolver.running:', resolver.get('running'))
print('resolver.age_seconds:', resolver.get('age_seconds'))
print('resolver.refresh_minutes:', resolver.get('refresh_minutes'))
print('worker_peer.alive:', (d.get('worker_peer') or {}).get('alive'))
print('snapshot_age_seconds:', d.get('snapshot_age_seconds'))
ss = d.get('score_snapshot') or {}
print('score_snapshot.file_present:', ss.get('file_present'))
lc = ss.get('last_cycle') or {}
print('score_snapshot.last_cycle.run_at:', lc.get('run_at'))
print('score_snapshot.last_cycle.skipped:', lc.get('skipped'))
sched = ss.get('scheduler') or {}
print('score_snapshot.scheduler.running:', sched.get('running'))
print('watchdog.warning:', (d.get('watchdog') or {}).get('warning'))
print('daily_pick.action:', (d.get('daily_pick') or {}).get('action'))

status = d.get('status')
snap = d.get('snapshot_age_seconds')
peer = (d.get('worker_peer') or {}).get('alive')
pending = int(d.get('pending') or 0)
tick_age = resolver.get('age_seconds')
refresh_m = float(resolver.get('refresh_minutes') or 15)
stall_after = refresh_m * 2 * 60

if pending > 0 and tick_age is not None and float(tick_age) > stall_after:
    print('FAIL — pending work but resolver tick older than 2x refresh')
    sys.exit(1)

if status == 'ok':
    print('OK — learning loop healthy')
    if snap is None and not lc.get('run_at'):
        print('NOTE — score snapshot not written yet; wait ~15min after worker boot')
    sys.exit(0)
if status == 'degraded':
    print('WARN — degraded (post-restart, snapshot catching up, or resolver lag)')
    sys.exit(0)
if not peer:
    wp = d.get('worker_peer') or {}
    if wp.get('source') == 'http':
        print('FAIL — split_v2 worker_peer not alive (HTTP probe)')
    else:
        print('FAIL — inline worker not alive; check data/.worker_heartbeat')
    sys.exit(1)
if status == 'stalled':
    if tick_age is not None and float(tick_age) < stall_after:
        print('WARN — stalled label but resolver tick fresh; ok for post-restart')
        sys.exit(0)
    print('WARN — stalled; check resolver tick and pending watchdog')
    sys.exit(1)
print('WARN — unexpected status:', status)
sys.exit(1)
"
