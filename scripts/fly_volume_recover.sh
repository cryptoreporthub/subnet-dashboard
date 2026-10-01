#!/bin/sh
# Free data_volume when prod has no healthy machine (post failed process-group migration).
# ponytail: aggressive destroy-all — prod is already down; one volume must reattach on deploy.
set -eu
APP="${FLY_APP:-subnet-dashboard}"
REGION="${FLY_PRIMARY_REGION:-sjc}"

echo "=== fly_volume_recover: machines before ==="
if ! machines_json="$(flyctl machines list -a "$APP" --json)"; then
  echo "ERROR: unable to inspect Fly machines; refusing recovery" >&2
  exit 1
fi
printf '%s\n' "$machines_json" | python3 -c 'import json, sys; print(json.dumps(json.load(sys.stdin), indent=2))'
machine_count="$(printf '%s' "$machines_json" | python3 -c 'import json, sys; print(len(json.load(sys.stdin)))')"

if [ "$machine_count" -gt 0 ]; then
  if [ "${FLY_VOLUME_RECOVER_CONFIRM:-}" != "destroy" ]; then
    echo "ERROR: expected zero machines; set FLY_VOLUME_RECOVER_CONFIRM=destroy to authorize machine deletion" >&2
    exit 1
  fi
  # Scale every process group to zero — releases volume attachments.
  flyctl scale count 0 --app "$APP" --yes
fi

if [ "$machine_count" -gt 0 ]; then
  printf '%s' "$machines_json" | python3 -c '
import json, sys
for machine in json.load(sys.stdin):
    if machine.get("id"):
        print(machine["id"])
' | while IFS= read -r id; do
    echo "force destroy machine $id"
    flyctl machine destroy "$id" -a "$APP" --force
  done
fi

echo "waiting 20s for volume detach..."
sleep 20

echo "=== volumes before dedupe ==="
if ! volumes_json="$(flyctl volumes list -a "$APP" --json)"; then
  echo "ERROR: unable to inspect Fly volumes; refusing recovery" >&2
  exit 1
fi
printf '%s\n' "$volumes_json" | python3 -c 'import json, sys; print(json.dumps(json.load(sys.stdin), indent=2))'

# Multiple unattached data_volume copies in one region break deploy volume pick.
duplicate_ids="$(printf '%s' "$volumes_json" | python3 -c "
import json,sys,os,subprocess
region=os.environ.get('FLY_PRIMARY_REGION','sjc')
vols=[v for v in json.load(sys.stdin)
      if v.get('name')=='data_volume' and v.get('region')==region and not v.get('attached_machine_id')]
if len(vols) <= 1:
    sys.exit(0)
vols.sort(key=lambda v: v.get('created_at') or '')
keep=vols[-1]['id']
for v in vols:
    if v['id']==keep:
        continue
    print(v['id'])
")"
if [ -n "$duplicate_ids" ]; then
  if [ "${FLY_VOLUME_RECOVER_CONFIRM:-}" != "destroy" ]; then
    echo "ERROR: duplicate unattached volumes found; set FLY_VOLUME_RECOVER_CONFIRM=destroy to authorize both machine and duplicate-volume deletion" >&2
    exit 1
  else
    while IFS= read -r volume_id; do
      [ -z "$volume_id" ] && continue
      echo "destroying duplicate unattached volume $volume_id"
      flyctl volumes destroy "$volume_id" -a "$APP" --yes
    done <<EOF
$duplicate_ids
EOF
  fi
fi

echo "waiting 10s after volume dedupe..."
sleep 10

echo "=== volumes after recover ==="
flyctl volumes list -a "$APP" || true

if ! unattached="$(flyctl volumes list -a "$APP" --json | python3 -c "
import json,sys,os
region=os.environ.get('FLY_PRIMARY_REGION','sjc')
vols=json.load(sys.stdin)
print(sum(1 for v in vols if v.get('name')=='data_volume' and v.get('region')==region and not v.get('attached_machine_id')))
")"; then
  echo "ERROR: unable to verify unattached data_volume after recovery" >&2
  exit 1
fi

echo "unattached data_volume in $REGION: $unattached"
if [ "$unattached" = "0" ]; then
  echo "ERROR: no unattached data_volume in $APP ($REGION) — deploy will fail"
  exit 1
fi
