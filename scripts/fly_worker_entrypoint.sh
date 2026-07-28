#!/bin/sh
# Fly dedicated worker machine (v2 split) — owns volume writes + background jobs.
set -eu
echo "starting dedicated worker (RUN_MODE=worker, WORKER_HEAVY=${WORKER_HEAVY:-essential}, MESSAGE_INTEL_LISTENER=${MESSAGE_INTEL_LISTENER:-on})..."
exec env RUN_MODE=worker WORKER_HEAVY="${WORKER_HEAVY:-essential}" MESSAGE_INTEL_LISTENER="${MESSAGE_INTEL_LISTENER:-on}" python -m internal.worker
