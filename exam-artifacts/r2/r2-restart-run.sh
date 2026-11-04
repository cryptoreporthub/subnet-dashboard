#!/usr/bin/env bash
# Restart tmux r2-run from START_IDX (RESUME=1). Uses portal tmux config.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ART="$REPO_ROOT/exam-artifacts/r2"
RUN_LOG="$ART/r2-run-532f3fbd-d7345633.log"
START_IDX="${1:?plan idx}"
GATE="$ART/r2-harness-gate.sh"
KILLED="$ART/r2-write-killed-inflight-audit.sh"
HOLD="$ART/.r2-gate-hold"
TMUX=(tmux -f /exec-daemon/tmux.portal.conf)
SESSION=r2-run

if [[ -f "$HOLD" ]]; then
  echo "r2-restart ABORT gate_hold START_IDX=${START_IDX}" >>"$RUN_LOG"
  exit 3
fi
if ! bash "$GATE" "$RUN_LOG"; then
  echo "r2-restart ABORT START_IDX=${START_IDX} harness_gate_failed" >>"$RUN_LOG"
  exit 2
fi
bash "$KILLED" "$RUN_LOG" || {
  echo "r2-restart WARN killed_audit_write_failed START_IDX=${START_IDX}" >>"$RUN_LOG"
}
"${TMUX[@]}" kill-session -t "$SESSION" 2>/dev/null || true
pkill -f 'run-r2.sh' 2>/dev/null || true
pkill -f 'agent-sdk eval.*review-gate-r1packb' 2>/dev/null || true
sleep 1
"${TMUX[@]}" new-session -d -s "$SESSION" -c "$REPO_ROOT" -- bash -lc \
  "export CURSOR_API_KEY; RESUME=1 START_IDX=${START_IDX} ./exam-artifacts/r2/run-r2.sh"
echo "r2-restart START_IDX=${START_IDX} at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
