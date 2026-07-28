#!/bin/sh
# Fly dedicated worker machine (v2 split) — volume writes + internal HTTP for web proxy.
set -eu
WORKER_PIDFILE="${WORKER_PIDFILE:-/tmp/fly_worker.pid}"

_start_worker() {
  if [ -f "$WORKER_PIDFILE" ]; then
    old_pid="$(cat "$WORKER_PIDFILE" 2>/dev/null || true)"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      return 0
    fi
  fi
  echo "starting background worker (RUN_MODE=worker, WORKER_HEAVY=${WORKER_HEAVY:-essential}, MESSAGE_INTEL_LISTENER=${MESSAGE_INTEL_LISTENER:-on})..."
  env RUN_MODE=worker WORKER_HEAVY="${WORKER_HEAVY:-essential}" MESSAGE_INTEL_LISTENER="${MESSAGE_INTEL_LISTENER:-on}" python -m internal.worker &
  echo $! > "$WORKER_PIDFILE"
  echo "worker pid=$(cat "$WORKER_PIDFILE")"
}

_start_worker
echo "starting internal HTTP on :8080 for split_v2 web volume proxy..."
exec env RUN_MODE=worker WORKER_HEAVY="${WORKER_HEAVY:-essential}" uvicorn server:app --host 0.0.0.0 --port 8080
