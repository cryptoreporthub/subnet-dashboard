#!/bin/sh
# Fly web machine — HTTP (uvicorn) + optional inline worker on same VM/volume.
# ponytail: one Fly process group (web=1) avoids volume split-brain; worker is a
# sibling OS process, not a second machine.
set -eu

_start_inline_worker() {
  case "${ENABLE_INLINE_WORKER:-1}" in
    0|false|no|off) return 0 ;;
  esac
  echo "starting inline background worker (RUN_MODE=worker, WORKER_HEAVY=${WORKER_HEAVY:-essential})..."
  env RUN_MODE=worker WORKER_HEAVY="${WORKER_HEAVY:-essential}" python -m internal.worker &
}

_start_inline_worker
exec uvicorn server:app --host 0.0.0.0 --port 8080
