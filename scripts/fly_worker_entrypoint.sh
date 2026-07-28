#!/bin/sh
# Fly dedicated worker machine (v2 split) — owns volume writes + background jobs.
set -eu
echo "starting dedicated worker (RUN_MODE=worker, WORKER_HEAVY=${WORKER_HEAVY:-essential})..."
exec env RUN_MODE=worker WORKER_HEAVY="${WORKER_HEAVY:-essential}" python -m internal.worker
