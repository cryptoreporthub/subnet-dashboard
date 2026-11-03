#!/usr/bin/env bash
# Wait for orphaned wave-2 eval, then run resume (extract wave2 + wave3).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SHA_SHORT="5d884c47"
ITER2="$REPO_ROOT/exam-artifacts/r1-packb-a/runs/review-gate-r1packb-iter2-${SHA_SHORT}.json"
LOG="$REPO_ROOT/exam-artifacts/r1-packb-a/r1-packb-a2-run-${SHA_SHORT}.log"
echo "wait_wave2_then_resume start $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
while pgrep -f 'agent-sdk eval.*review-gate-r1packb-iter2' >/dev/null 2>&1; do
  sleep 30
done
while [[ ! -f "$ITER2" ]] || [[ "$(python3 -c "import json; print(len(json.load(open('$ITER2')).get('results',[])))" 2>/dev/null || echo 0)" -lt 48 ]]; do
  sleep 15
done
echo "wave2_json_ready $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
exec bash "$REPO_ROOT/exam-artifacts/r1-packb-a/resume-r1-packb-a2-waves23.sh"
