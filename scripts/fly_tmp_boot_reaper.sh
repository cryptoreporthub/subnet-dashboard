#!/usr/bin/env bash
# Reap stale *.tmp atomic-write orphans on the Fly data volume.
# Run before representative soak / cutover, or via fly machine exec on worker.
set -euo pipefail

APP="${FLY_APP:-subnet-dashboard}"
DRY="${TMP_BOOT_REAP_DRY:-0}"
MIN_AGE="${TMP_BOOT_REAP_MIN_AGE_SECONDS:-3600}"

TARGET_ID="${WORKER_MACHINE_ID:-}"
if [ -z "$TARGET_ID" ]; then
  TARGET_ID="$(flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    meta=(m.get('config') or {}).get('metadata') or {}
    pg=(meta.get('fly_process_group') or m.get('process_group') or '').lower()
    mounts=(m.get('config') or {}).get('mounts') or []
    if pg=='worker' and mounts and m.get('id'):
        print(m['id'])
        break
" 2>/dev/null || true)"
fi

if [ -z "$TARGET_ID" ]; then
  TARGET_ID="$(flyctl machines list -a "$APP" --json | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    meta=(m.get('config') or {}).get('metadata') or {}
    pg=(meta.get('fly_process_group') or m.get('process_group') or 'web').lower()
    mounts=(m.get('config') or {}).get('mounts') or []
    if pg=='web' and mounts and m.get('id'):
        print(m['id'])
        break
" 2>/dev/null || true)"
fi

if [ -z "$TARGET_ID" ]; then
  echo "ABORT: no machine with data_volume mount found on $APP"
  exit 1
fi

echo "== tmp boot reaper: app=$APP machine=$TARGET_ID min_age=${MIN_AGE}s dry=$DRY =="

flyctl machine exec -a "$APP" "$TARGET_ID" --timeout 120 \
  "env TMP_BOOT_REAP_MIN_AGE_SECONDS=${MIN_AGE} TMP_BOOT_REAP_DRY=${DRY} python3 /app/scripts/tmp_boot_reap_once.py"
