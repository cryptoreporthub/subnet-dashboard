
#!/bin/sh
# Fly web machine — HTTP (uvicorn) + optional inline worker on same VM/volume.
# ponytail: one Fly process group (web=1) avoids volume split-brain; worker is a
# sibling OS process, not a second machine.
set -eu

INLINE_WORKER_PIDFILE="${INLINE_WORKER_PIDFILE:-/tmp/inline_worker.pid}"
INLINE_WORKER_STOP_GRACE_SECONDS="${INLINE_WORKER_STOP_GRACE_SECONDS:-15}"
INLINE_WORKER_SUPERVISOR_SLEEP_SECONDS="${INLINE_WORKER_SUPERVISOR_SLEEP_SECONDS:-90}"
INLINE_WORKER_LAUNCH="${INLINE_WORKER_LAUNCH:-python -m internal.worker}"

_inline_worker_proc_state() {
  pid="$1"
  if [ ! -r "/proc/$pid/stat" ]; then
    return 1
  fi
  awk '{print $3}' "/proc/$pid/stat"
}

_inline_worker_group_live() {
  pgid="$1"
  if [ -z "$pgid" ]; then
    return 1
  fi
  if ! kill -0 -"$pgid" 2>/dev/null; then
    return 1
  fi
  if ps -o stat= -g "$pgid" 2>/dev/null | grep -qv '^Z'; then
    return 0
  fi
  return 1
}

_stop_inline_worker() {
  pgid="$1"
  if [ -z "$pgid" ]; then
    return 0
  fi
  if ! _inline_worker_group_live "$pgid"; then
    wait "$pgid" 2>/dev/null || true
    return 0
  fi
  kill -TERM -"$pgid" 2>/dev/null || kill -TERM "$pgid" 2>/dev/null || true
  deadline=$(( $(date +%s) + INLINE_WORKER_STOP_GRACE_SECONDS ))
  while _inline_worker_group_live "$pgid"; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "inline worker pgid=$pgid did not exit after ${INLINE_WORKER_STOP_GRACE_SECONDS}s; sending SIGKILL"
      kill -KILL -"$pgid" 2>/dev/null || kill -KILL "$pgid" 2>/dev/null || true
      sleep 1
      break
    fi
    sleep 1
  done
  wait "$pgid" 2>/dev/null || true
}

_start_inline_worker() {
  case "${ENABLE_INLINE_WORKER:-1}" in
    0|false|no|off)
      echo "ENABLE_INLINE_WORKER=${ENABLE_INLINE_WORKER} — skipping inline worker (v2 web config)"
      return 0
      ;;
  esac
  case "${WORKER_SPLIT_V2:-0}" in
    1|true|yes|on)
      echo "WORKER_SPLIT_V2=on — skipping inline worker (dedicated worker process group)"
      return 0
      ;;
  esac
  if [ -f "$INLINE_WORKER_PIDFILE" ]; then
    old_pgid="$(cat "$INLINE_WORKER_PIDFILE" 2>/dev/null || true)"
    if _inline_worker_group_live "$old_pgid"; then
      return 0
    fi
    rm -f "$INLINE_WORKER_PIDFILE"
  fi
  echo "starting inline background worker (RUN_MODE=worker, WORKER_HEAVY=${WORKER_HEAVY:-essential})..."
  nice -n 10 env RUN_MODE=worker WORKER_HEAVY="${WORKER_HEAVY:-essential}" setsid sh -c "exec $INLINE_WORKER_LAUNCH" &
  echo $! > "$INLINE_WORKER_PIDFILE"
  echo "inline worker pgid=$(cat "$INLINE_WORKER_PIDFILE")"
}

_supervise_inline_worker() {
  case "${ENABLE_INLINE_WORKER:-1}" in
    0|false|no|off)
      echo "ENABLE_INLINE_WORKER=${ENABLE_INLINE_WORKER} — skipping inline worker (v2 web config)"
      return 0
      ;;
  esac
  (
    _start_inline_worker
    while true; do
      sleep "$INLINE_WORKER_SUPERVISOR_SLEEP_SECONDS"
      pgid=""
      if [ -f "$INLINE_WORKER_PIDFILE" ]; then
        pgid="$(cat "$INLINE_WORKER_PIDFILE" 2>/dev/null || true)"
      fi
      need_restart=0
      if [ -z "$pgid" ] || ! _inline_worker_group_live "$pgid"; then
        need_restart=1
      elif ! python -c "from internal.worker_heartbeat import is_alive; import sys; sys.exit(0 if is_alive(max_age_seconds=180) else 1)"; then
        echo "inline worker heartbeat stale (pgid=$pgid), restarting..."
        need_restart=1
      fi
      if [ "$need_restart" = 1 ]; then
        if [ -n "$pgid" ]; then
          _stop_inline_worker "$pgid"
        fi
        if [ -n "$pgid" ] && _inline_worker_group_live "$pgid"; then
          echo "inline worker restart skipped: pgid=$pgid still alive after stop"
        else
          rm -f "$INLINE_WORKER_PIDFILE"
          _start_inline_worker
        fi
      fi
    done
  ) &
}

case "${ENABLE_INLINE_WORKER:-1}" in
  0|false|no|off) ;;
  *)
    case "${WORKER_SPLIT_V2:-0}" in
      1|true|yes|on) ;;
      *)
        python scripts/tmp_boot_reap_once.py || echo "WARN: tmp boot reaper skipped at entrypoint"
        ;;
    esac
    ;;
esac

_supervise_inline_worker
exec python scripts/run_web_with_guard.py
