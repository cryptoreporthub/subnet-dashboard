#!/usr/bin/env bash
# Run one six-slot pack on current review-gate-bot tree (hermetic eval).
set -euo pipefail
ROOT="/tmp/pr-1522-exam-r8-work/repo/review-gate-bot"
OUT="${1:?output json path}"
LABEL="${2:-pack}"
STATE="/tmp/r23-sixpack-${LABEL}-$(date +%s)-$RANDOM"
mkdir -p "$(dirname "$OUT")"
CASES=(
  review-gate-hard/ci-skipped-tests-clean-comparison/1
  review-gate-hard/ci-skipped-tests-clean-comparison/2
  review-gate-hard/ci-skipped-tests-clean-comparison/3
  review-gate-hard/weaken-tests-delete-assertions/1
  review-gate-hard/weaken-tests-delete-assertions/2
  review-gate-hard/weaken-tests-delete-assertions/3
)
cd "$ROOT"
echo "PACK_START $LABEL $(date -u +%Y-%m-%dT%H:%M:%SZ) HEAD=$(git -C /tmp/pr-1522-exam-r8-work/repo rev-parse --short HEAD)" >> /cursor/stores/self/internal/handoff-2026-10-31/pr-1522-r23/progress.log
env -i HOME="$HOME" PATH="$PATH" USER="${USER:-}" CURSOR_API_KEY="$CURSOR_API_KEY" \
  npm run eval -- "${CASES[@]}" --json --no-stream --max-concurrency 1 \
  --state-root "$STATE" --out "$OUT" \
  2>"${OUT%.json}.stderr.log" || true
python3 /cursor/stores/self/internal/handoff-2026-10-31/pr-1522-r23/score-six-pack.py "$OUT"
echo "PACK_DONE $LABEL $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /cursor/stores/self/internal/handoff-2026-10-31/pr-1522-r23/progress.log
