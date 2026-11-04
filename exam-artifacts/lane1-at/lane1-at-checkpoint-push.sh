#!/usr/bin/env bash
# Periodic checkpoint: commit + push exam-artifacts/lane1-at run outputs (safe while run live).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
ART="exam-artifacts/lane1-at"
TAG="f3c84766-d7345633"
shopt -s nullglob
FILES=(
  "$ART/slot-audit-lane1-at-${TAG}.ndjson"
  "$ART/lane1-at-run-${TAG}.log"
  "$ART/runs/review-gate-lane1-at-${TAG}.json"
  "$ART/.run-progress.json"
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
LINES="$(wc -l <"${ART}/slot-audit-lane1-at-${TAG}.ndjson" 2>/dev/null | tr -d ' ' || echo 0)"
git commit -m "lane1-at checkpoint: audit=${LINES} lines (live run, no scoring)"
git push origin exam-artifacts/lane1-at
echo "checkpoint pushed audit_lines=${LINES} sha=$(git rev-parse HEAD)"
