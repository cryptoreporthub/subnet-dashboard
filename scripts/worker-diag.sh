#!/usr/bin/env bash
set -euo pipefail
APP="subnet-dashboard"

echo "== machine states =="
flyctl machines list -a "$APP" --json | jq -r '.[] | "\(.id) state=\(.state) pg=\(.process_group // .config.process_group // \"web\")"' || true

echo "== resolving probe machine (worker when split v2, else web) =="
# split v2: background jobs + Telegram listener run on the worker process group.
WORKER_ID="$(flyctl machines list -a "$APP" --json | jq -r '[.[] | select(((.process_group // .config.process_group // \"\") | ascii_downcase) == \"worker\") and (.state == \"running\" or .state == \"started\")][0].id // empty')"
if [ -n "${WORKER_ID:-}" ] && [ "$WORKER_ID" != "null" ]; then
  TARGET_ID="$WORKER_ID"
  echo "split v2 — probing worker machine"
else
  # v1 fallback: inline worker on web machine
  TARGET_ID="$(flyctl machines list -a "$APP" --json | jq -r '[.[] | select(((.process_group // .config.process_group // \"web\") == \"web\") and .state == \"running\")][0].id // empty')"
  if [ -z "${TARGET_ID:-}" ] || [ "$TARGET_ID" = "null" ]; then
    TARGET_ID="$(flyctl machines list -a "$APP" --json | jq -r '[.[] | select((.process_group // .config.process_group // \"web\") == \"web\")][0].id // empty')"
  fi
  if [ -z "${TARGET_ID:-}" ] || [ "$TARGET_ID" = "null" ]; then
    TARGET_ID="$(flyctl machines list -a "$APP" --json | jq -r '.[0].id')"
  fi
  echo "v1 inline — probing web machine"
fi
echo "probe machine=$TARGET_ID"

# if it is not running, start it and wait
STATE="$(flyctl machine status "$TARGET_ID" -a "$APP" --json 2>/dev/null | jq -r '.state // empty')"
echo "machine state=$STATE"
if [ "$STATE" != "running" ] && [ "$STATE" != "started" ] && [ -n "$STATE" ]; then
  echo "machine not running (state=$STATE); starting..."
  flyctl machine start "$TARGET_ID" --app "$APP" || true
  sleep 20
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE_B64="$(base64 -w0 "$SCRIPT_DIR/worker_probe.py")"

echo "== worker probe =="
flyctl machine exec "$TARGET_ID" "cd /app && echo \"$PROBE_B64\" | base64 -d > /tmp/probe.py && python3 /tmp/probe.py" --app "$APP" --timeout 600 || true

echo "== telegram entity probe =="
flyctl machine exec "$TARGET_ID" "cd /app && python3 scripts/probe_telegram_entity.py" --app "$APP" --timeout 120 || true