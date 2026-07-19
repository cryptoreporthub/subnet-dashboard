#!/bin/sh
# Free data_volume when prod has no healthy machine (post failed process-group migration).
# ponytail: aggressive destroy-all — prod is already down; one volume must reattach on deploy.
set -eu
APP="${FLY_APP:-subnet-dashboard}"
REGION="${FLY_PRIMARY_REGION:-sjc}"

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

echo "=== volumes before dedupe ==="
flyctl volumes list -a "$APP" || true

# Multiple unattached data_volume copies in one region break deploy volume pick.
flyctl volumes list -a "$APP" --json 2>/dev/null | python3 -c "
import json,sys,os,subprocess
app=os.environ.get('FLY_APP','subnet-dashboard')
region=os.environ.get('FLY_PRIMARY_REGION','sjc')
vols=[v for v in json.load(sys.stdin)
      if v.get('name')=='data_volume' and v.get('region')==region and not v.get('attached_machine_id')]
if len(vols) <= 1:
    sys.exit(0)
vols.sort(key=lambda v: v.get('created_at') or '')
keep=vols[-1]['id']
for v in vols:
    if v['id']==keep:
        print(f'keeping volume {keep}', file=sys.stderr)
        continue
    vid=v['id']
    print(f'destroying duplicate unattached volume {vid}', file=sys.stderr)
    subprocess.run(['flyctl','volumes','destroy',vid,'-a',app,'--yes'], check=False)
" 2>/dev/null || true

echo "waiting 10s after volume dedupe..."
sleep 10

echo "=== volumes after recover ==="
flyctl volumes list -a "$APP" || true

unattached=$(flyctl volumes list -a "$APP" --json 2>/dev/null | python3 -c "
import json,sys,os
region=os.environ.get('FLY_PRIMARY_REGION','sjc')
vols=json.load(sys.stdin)
print(sum(1 for v in vols if v.get('name')=='data_volume' and v.get('region')==region and not v.get('attached_machine_id')))
" 2>/dev/null || echo 0)

echo "unattached data_volume in $REGION: $unattached"
if [ "$unattached" = "0" ]; then
  echo "ERROR: no unattached data_volume in $APP ($REGION) — deploy will fail"
  exit 1
fi
