#!/usr/bin/env bash
# Syntax gate before r2-run restart (node --check *.mjs, bash -n *.sh).
set -euo pipefail
ART="$(cd "$(dirname "$0")" && pwd)"
LOG="${1:-/dev/stderr}"
fail=0
for f in "$ART"/*.mjs; do
  [[ -f "$f" ]] || continue
  if ! node --check "$f" >>"$LOG" 2>&1; then
    echo "r2-harness-gate FAIL node --check $(basename "$f")" >>"$LOG"
    fail=1
  fi
done
for f in "$ART"/*.sh; do
  [[ -f "$f" ]] || continue
  if ! bash -n "$f" >>"$LOG" 2>&1; then
    echo "r2-harness-gate FAIL bash -n $(basename "$f")" >>"$LOG"
    fail=1
  fi
done
if (( fail )); then
  echo "r2-harness-gate STOP restart blocked at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$LOG"
  exit 1
fi
echo "r2-harness-gate ok at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$LOG"
