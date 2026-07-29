#!/bin/sh
# Fly dedicated worker machine (v2 split) — volume writes + internal HTTP for web proxy.
set -eu
WORKER_PIDFILE="${WORKER_PIDFILE:-/tmp/fly_worker.pid}"

# ponytail: app-wide fly secret WORKER_HEAVY=essential (v1 inline) must not win here —
# ${WORKER_HEAVY:-full} expands the secret and skips live-subnet sync on the volume worker.
DEDICATED_WORKER_HEAVY=full
DEDICATED_BOOT_IMMEDIATE="${LIVE_SUBNETS_BOOT_IMMEDIATE:-on}"

_start_worker() {
  if [ -f "$WORKER_PIDFILE" ]; then
    old_pid="$(cat "$WORKER_PIDFILE" 2>/dev/null || true)"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      return 0
    fi
  fi
  echo "starting background worker (RUN_MODE=worker, WORKER_HEAVY=${DEDICATED_WORKER_HEAVY}, MESSAGE_INTEL_LISTENER=${MESSAGE_INTEL_LISTENER:-on})..."
  env RUN_MODE=worker WORKER_HEAVY="${DEDICATED_WORKER_HEAVY}" LIVE_SUBNETS_BOOT_IMMEDIATE="${DEDICATED_BOOT_IMMEDIATE}" MESSAGE_INTEL_LISTENER="${MESSAGE_INTEL_LISTENER:-on}" python -m internal.worker &
  echo $! > "$WORKER_PIDFILE"
  echo "worker pid=$(cat "$WORKER_PIDFILE")"
}

_start_worker
PORT="${WORKER_HTTP_PORT:-8081}"
echo "starting internal HTTP on :${PORT} for split_v2 web volume proxy..."
exec env RUN_MODE=worker WORKER_HEAVY="${DEDICATED_WORKER_HEAVY}" LIVE_SUBNETS_BOOT_IMMEDIATE="${DEDICATED_BOOT_IMMEDIATE}" MESSAGE_INTEL_LISTENER="${MESSAGE_INTEL_LISTENER:-on}" uvicorn server:app --host 0.0.0.0 --port "$PORT"
