#!/usr/bin/env bash
# Periodic checkpoint: commit + push exam-artifacts/r2 run outputs (safe while r2-run live).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
ART="exam-artifacts/r2"
TAG="532f3fbd-d7345633"
shopt -s nullglob
FILES=(
  "$ART/slot-audit-r2-${TAG}.ndjson"
  "$ART/r2-run-${TAG}.log"
  "$ART/runs/review-gate-r2-${TAG}.json"
  "$ART/.run-progress.json"
  "$ART/.hang-strikes"
)
CHANGED=0
for f in "${FILES[@]}"; do
  [[ -f "$f" ]] || continue
  git add "$f" 2>/dev/null || true
  if ! git diff --cached --quiet -- "$f" 2>/dev/null; then CHANGED=1; fi
done
if (( CHANGED == 0 )); then
  echo "checkpoint: no artifact changes"
  exit 0
fi
LINES="$(wc -l <"${ART}/slot-audit-r2-${TAG}.ndjson" 2>/dev/null | tr -d ' ' || echo 0)"
git commit -m "R2 checkpoint: audit=${LINES} lines (live run, no scoring)"
git push origin exam-artifacts/r2
echo "checkpoint pushed audit_lines=${LINES} sha=$(git rev-parse --short HEAD)"
