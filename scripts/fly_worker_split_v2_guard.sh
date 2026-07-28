#!/bin/sh
# True when app runs split v2 (secret, CI force flag, or worker process group exists).
set -eu
APP="${FLY_APP:-subnet-dashboard}"
if [ "${FORCE_WORKER_SPLIT_V2:-}" = "1" ]; then
  exit 0
fi
flyctl secrets list -a "$APP" --json 2>/dev/null | python3 -c "
import json, subprocess, sys
app = sys.argv[1]
try:
    rows = json.load(sys.stdin)
except Exception:
    rows = []
for row in rows:
    if row.get('Name') == 'WORKER_SPLIT_V2':
        sys.exit(0)
try:
    machines = json.loads(
        subprocess.check_output(['flyctl', 'machines', 'list', '-a', app, '--json'], text=True)
    )
except Exception:
    machines = []
for m in machines:
    meta = (m.get('config') or {}).get('metadata') or {}
    pg = (meta.get('fly_process_group') or meta.get('process_group') or m.get('process_group') or '').lower()
    if pg == 'worker':
        sys.exit(0)
sys.exit(1)
" "$APP"
