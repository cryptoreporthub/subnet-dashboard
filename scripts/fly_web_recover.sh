#!/bin/sh
# Ensure only the web process group serves HTTP — destroy orphan worker machines.
set -eu
APP="${FLY_APP:-subnet-dashboard}"

echo "=== fly_web_recover: machines before ==="
flyctl machines list -a "$APP" || true

flyctl machines list -a "$APP" --json 2>/dev/null | python3 -c "
import json, subprocess, sys

app = sys.argv[1]
try:
    machines = json.load(sys.stdin)
except Exception:
    machines = []

for m in machines:
    mid = m.get('id') or ''
    pg = (m.get('process_group') or '').strip().lower()
    if not mid:
        continue
    if pg and pg != 'web':
        print(f'destroy non-web machine {mid} (process_group={pg})')
        subprocess.run(
            ['flyctl', 'machine', 'destroy', mid, '-a', app, '--force'],
            check=False,
        )
" "$APP" || true

echo "=== scaling web=1 ==="
flyctl scale count web=1 --app "$APP" --yes || true

echo "=== fly_web_recover: machines after ==="
flyctl machines list -a "$APP" || true
