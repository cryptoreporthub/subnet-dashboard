#!/usr/bin/env bash
# Restart tmux r2-run from START_IDX (RESUME=1). Uses portal tmux config.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
START_IDX="${1:?plan idx}"
TMUX=(tmux -f /exec-daemon/tmux.portal.conf)
SESSION=r2-run
"${TMUX[@]}" kill-session -t "$SESSION" 2>/dev/null || true
pkill -f 'run-r2.sh' 2>/dev/null || true
pkill -f 'agent-sdk eval.*review-gate-r1packb' 2>/dev/null || true
sleep 1
"${TMUX[@]}" new-session -d -s "$SESSION" -c "$REPO_ROOT" -- bash -lc \
  "export CURSOR_API_KEY; RESUME=1 START_IDX=${START_IDX} ./exam-artifacts/r2/run-r2.sh"
echo "r2-restart START_IDX=${START_IDX} at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
