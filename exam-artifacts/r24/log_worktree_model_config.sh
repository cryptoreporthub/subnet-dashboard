#!/usr/bin/env bash
# Log resolved review-gate-bot model config at PRE and POST pins (before Stage A runs).
set -euo pipefail
REPO="${REPO_ROOT:-/tmp/pr-1522-exam-r8-work/repo}"
PRE_SHA="23bd34f03fb4431ad29726f500f00efc9d1dd82b"
POST_SHA="a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e"
LOG="${1:-$REPO/exam-artifacts/r24/worktree-model-config.log}"

show_model() {
  local label=$1
  local sha=$2
  echo "--- $label ($sha) bot/agent.ts model ---"
  git -C "$REPO" show "$sha:review-gate-bot/bot/agent.ts" | python3 -c '
import re, sys
text = sys.stdin.read()
id_m = re.search(r"model:\s*\{\s*id:\s*\"([^\"]+)\"", text)
if not id_m:
    sys.exit("model id not found")
params = re.findall(r"\{\s*id:\s*\"([^\"]+)\"\s*,\s*value:\s*\"([^\"]+)\"\s*\}", text)
print(f"id={id_m.group(1)} params={params}")
'
}

{
  echo "=== r24 worktree model config $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  show_model PRE "$PRE_SHA"
  show_model POST "$POST_SHA"
} | tee "$LOG"
