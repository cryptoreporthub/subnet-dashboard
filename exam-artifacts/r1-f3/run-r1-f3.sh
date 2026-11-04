#!/usr/bin/env bash
# R1-F3: 8 fixtures x 3 iterations, arm A, per-slot 15m cap, V1-V3 audit fields.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BOT="$REPO_ROOT/review-gate-bot"
PLAN="$REPO_ROOT/exam-artifacts/r1-f3/run-plan.json"
CAP="$REPO_ROOT/exam-artifacts/r1-f3/run-wave-slots-capped.sh"
PREF="$REPO_ROOT/exam-artifacts/r1-f3/preflight-r1-packb-a.sh"
AUDIT="$REPO_ROOT/exam-artifacts/r1-f3/slot-audit-f3-5d884c47-36d724b1.ndjson"
LOG="$REPO_ROOT/exam-artifacts/r1-f3/r1-f3-run-5d884c47-36d724b1.log"
FIX_SHA_FULL="$(python3 -c "import json; print(json.load(open('$PLAN'))['fixturePinSha'])")"

mkdir -p "$REPO_ROOT/exam-artifacts/r1-f3/runs"
: >"$AUDIT"

exec > >(tee -a "$LOG") 2>&1
echo "=== R1-F3 start $(date -u +%Y-%m-%dT%H:%M:%SZ) harness=5d884c47 fixtures=36d724b1 arm=A packBV3=true ==="
echo "git_rev=$(git -C "$REPO_ROOT" rev-parse HEAD)"
echo "fixture_pin_full=$FIX_SHA_FULL"

cd "$BOT"
export R2_METHOD_ARM=A
PREF_OUT="$(bash "$PREF")"
echo "$PREF_OUT"
echo "$PREF_OUT" | grep -q preflight_ok || { echo "STOP preflight failed"; exit 3; }

SYSPROMPT_CHARS="$(echo "$PREF_OUT" | sed -n 's/^sysprompt_chars=\([0-9]*\)$/\1/p' | head -1)"
SYSPROMPT_SHA="$(echo "$PREF_OUT" | sed -n 's/^sysprompt_sha256=\([a-f0-9]\{64\}\)$/\1/p' | head -1)"
MODEL_JSON="$(echo "$PREF_OUT" | sed -n 's/^model_object=\(.*\)/\1/p')"

for wave_idx in 0 1 2; do
  bash "$CAP" "$wave_idx" "$SYSPROMPT_CHARS" "$SYSPROMPT_SHA" "$MODEL_JSON" "$FIX_SHA_FULL"
done

FINAL="$(wc -l <"$AUDIT" | tr -d ' ')"
TO="$(grep -c '^slot_timeout ' "$LOG" || true)"
echo "=== R1-F3 complete $(date -u +%Y-%m-%dT%H:%M:%SZ) audit_lines=$FINAL slot_timeout_count=$TO ==="
if [[ "$FINAL" -ne 24 ]]; then
  echo "STOP: expected 24 audit lines, got $FINAL"
  exit 8
fi
