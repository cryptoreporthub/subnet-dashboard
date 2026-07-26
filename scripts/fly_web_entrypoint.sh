#!/bin/sh
# Fly web machine — HTTP (uvicorn) + optional inline worker on same VM/volume.
# ponytail: one Fly process group (web=1) avoids volume split-brain; worker is a
# sibling OS process, not a second machine.
set -eu

INLINE_WORKER_PIDFILE="${INLINE_WORKER_PIDFILE:-/tmp/inline_worker.pid}"

_start_inline_worker() {
  case "${ENABLE_INLINE_WORKER:-1}" in
    0|false|no|off) return 0 ;;
  esac
  if [ -f "$INLINE_WORKER_PIDFILE" ]; then
    old_pid="$(cat "$INLINE_WORKER_PIDFILE" 2>/dev/null || true)"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      return 0
    fi
  fi
  echo "starting inline background worker (RUN_MODE=worker, WORKER_HEAVY=${WORKER_HEAVY:-essential})..."
  # Lower CPU priority so HTTP wins under contention on shared 2GB machine.
  nice -n 10 env RUN_MODE=worker WORKER_HEAVY="${WORKER_HEAVY:-essential}" python -m internal.worker &
  echo $! > "$INLINE_WORKER_PIDFILE"
  echo "inline worker pid=$(cat "$INLINE_WORKER_PIDFILE")"
}

_supervise_inline_worker() {
  case "${ENABLE_INLINE_WORKER:-1}" in
    0|false|no|off) return 0 ;;
  esac
  (
    while true; do
      sleep 90
      pid=""
      if [ -f "$INLINE_WORKER_PIDFILE" ]; then
        pid="$(cat "$INLINE_WORKER_PIDFILE" 2>/dev/null || true)"
      fi
      need_restart=0
      if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        need_restart=1
      elif ! python -c "from internal.worker_heartbeat import is_alive; import sys; sys.exit(0 if is_alive(max_age_seconds=180) else 1)"; then
        echo "inline worker heartbeat stale (pid=$pid), restarting..."
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        rm -f "$INLINE_WORKER_PIDFILE"
        need_restart=1
      fi
      if [ "$need_restart" = 1 ]; then
        _start_inline_worker
      fi
    done
  ) &
}

_start_inline_worker
_supervise_inline_worker
exec uvicorn server:app --host 0.0.0.0 --port 8080
