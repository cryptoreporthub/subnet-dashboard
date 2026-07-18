#!/bin/sh
# Free data_volume when prod has no healthy machine (post failed process-group migration).
# ponytail: aggressive destroy-all — prod is already down; one volume must reattach on deploy.
set -eu
APP="${FLY_APP:-subnet-dashboard}"

echo "=== fly_volume_recover: machines before ==="
flyctl machines list -a "$APP" || true

# Scale every process group to zero — releases volume attachments.
flyctl scale count 0 --app "$APP" --yes 2>/dev/null || true

for id in $(flyctl machines list -a "$APP" --json 2>/dev/null | python3 -c "
import json,sys
try:
    for m in json.load(sys.stdin):
        if m.get('id'):
            print(m['id'])
except Exception:
    pass
" 2>/dev/null); do
  echo "force destroy machine $id"
  flyctl machine destroy "$id" -a "$APP" --force 2>/dev/null || true
done

echo "waiting 20s for volume detach..."
sleep 20

echo "=== volumes after recover ==="
flyctl volumes list -a "$APP" || true

unattached=$(flyctl volumes list -a "$APP" --json 2>/dev/null | python3 -c "
import json,sys
vols=json.load(sys.stdin)
print(sum(1 for v in vols if v.get('name')=='data_volume' and not v.get('attached_machine_id')))
" 2>/dev/null || echo 0)

echo "unattached data_volume: $unattached"
if [ "$unattached" = "0" ]; then
  echo "ERROR: no unattached data_volume in $APP — deploy will fail"
  exit 1
fi
