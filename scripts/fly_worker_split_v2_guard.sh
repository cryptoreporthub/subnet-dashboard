#!/bin/sh
# True when Fly app has WORKER_SPLIT_V2 secret (deploy must not destroy worker machines).
set -eu
APP="${FLY_APP:-subnet-dashboard}"
flyctl secrets list -a "$APP" --json 2>/dev/null | python3 -c "
import json, sys
try:
    rows = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for row in rows:
    if row.get('Name') == 'WORKER_SPLIT_V2':
        sys.exit(0)
sys.exit(1)
"
