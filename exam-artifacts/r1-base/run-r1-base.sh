#!/usr/bin/env bash
# R1-BASE: 21-case hard exam x 3 iterations, arm A, concurrency 1, hermetic env.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BOT="$REPO_ROOT/review-gate-bot"
PLAN="$REPO_ROOT/exam-artifacts/r1-base/run-plan.json"
SHA_SHORT="5d884c47"
RUN_LOG="$REPO_ROOT/exam-artifacts/r1-base/r1-base-run-${SHA_SHORT}.log"
AUDIT="$REPO_ROOT/exam-artifacts/r1-base/slot-audit-${SHA_SHORT}.ndjson"
mkdir -p "$REPO_ROOT/exam-artifacts/r1-base/runs"
: >"$AUDIT"

exec > >(tee -a "$RUN_LOG") 2>&1
echo "=== R1-BASE run start $(date -u +%Y-%m-%dT%H:%M:%SZ) harness=$SHA_SHORT ==="
echo "git_rev=$(git -C "$REPO_ROOT" rev-parse HEAD)"
echo "plan=$PLAN"

cd "$BOT"
export R2_METHOD_ARM=A

PREF="$(bash "$REPO_ROOT/exam-artifacts/r1-base/preflight-r1-base.sh")"
echo "$PREF"
echo "$PREF" | grep -q preflight_ok || { echo "STOP preflight failed"; exit 3; }

SYSPROMPT_CHARS="$(echo "$PREF" | sed -n 's/^sysprompt_chars=\([0-9]*\).*/\1/p')"
SYSPROMPT_SHA="$(echo "$PREF" | sed -n 's/^sysprompt_sha256=\([a-f0-9]*\).*/\1/p')"
MODEL_JSON="$(echo "$PREF" | sed -n 's/^model_object=\(.*\)/\1/p')"

echo "eval_build=$(cd "$BOT" && npx agent-sdk eval --dir . --version 2>&1 | tail -1)"

HERMETIC=(env -i
  HOME="$HOME"
  PATH="$PATH"
  USER="${USER:-ubuntu}"
  TMPDIR="${TMPDIR:-/tmp}"
  CURSOR_API_KEY="${CURSOR_API_KEY:?CURSOR_API_KEY required}"
  R2_METHOD_ARM=A
)

WAVE_COUNT="$(python3 -c "import json; print(len(json.load(open('$PLAN'))['waves']))")"
for wave_idx in $(seq 0 $((WAVE_COUNT - 1))); do
  readarray -t WAVE_META < <(python3 - <<PY
import json
plan=json.load(open("$PLAN"))
w=plan["waves"][$wave_idx]
print(w["iteration"])
print(w["outputJson"])
PY
)
  ITER="${WAVE_META[0]}"
  OUT_REL="${WAVE_META[1]}"
  OUT="$REPO_ROOT/$OUT_REL"
  mapfile -t IDS < <(python3 - <<PY
import json
print("\n".join(json.load(open("$PLAN"))["waves"][$wave_idx]["evalIds"]))
PY
)
  STATE="/tmp/r1-base-state-iter${ITER}-$$"
  rm -rf "$STATE"
  echo "WAVE_${ITER}_START $(date -u +%Y-%m-%dT%H:%M:%SZ) slots=${#IDS[@]}"
  START=$SECONDS
  set +e
  "${HERMETIC[@]}" bash -lc "cd '$BOT' && npx agent-sdk eval --dir . $(printf '%q ' "${IDS[@]}") --json --no-stream --max-concurrency 1 --state-root '$STATE' --out '$OUT'"
  EC=$?
  set -e
  DUR=$((SECONDS - START))
  echo "WAVE_${ITER}_END $(date -u +%Y-%m-%dT%H:%M:%SZ) duration_s=${DUR} exit=${EC}"
  if [[ ! -f "$OUT" ]]; then
    echo "STOP: missing output $OUT"
    exit 4
  fi
  (cd "$BOT" && node "$REPO_ROOT/exam-artifacts/r1-base/extract-slot-audit.mjs" \
    "$OUT" "$AUDIT" "$SYSPROMPT_CHARS" "$SYSPROMPT_SHA" "$MODEL_JSON")
  echo "WAVE_${ITER}_WROTE $OUT_REL"
  if [[ "$EC" -ne 0 ]]; then
    echo "NOTE: agent-sdk exit $EC (raw JSON still published; Claude scores)"
  fi
  rm -rf "$STATE"
done

echo "=== R1-BASE run complete $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
