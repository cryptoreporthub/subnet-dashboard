#!/usr/bin/env bash
# Stub: parent waits on child; both ignore SIGTERM; continuous stdout (repro item 2 gap).
set -euo pipefail
MARKER="${R2_STUB_MARKER:-stub_ignore_term}"
trap '' TERM
echo "${MARKER} parent_start pid=$$ pgid=$(ps -o pgid= -p $$ 2>/dev/null | tr -d ' ')"
bash -c "
  trap '' TERM
  MARKER=\"${MARKER}\"
  while true; do
    echo \"\${MARKER} child_line pid=\$\$ ts=\$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
    sleep 1
  done
" &
CHILD=$!
echo "${MARKER} child_spawn pid=${CHILD}"
wait "$CHILD"
