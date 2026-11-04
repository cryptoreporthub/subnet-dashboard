#!/usr/bin/env bash
# Run one wave iteration: one eval id per slot, 15m wall cap, audit append per slot.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BOT="$REPO_ROOT/review-gate-bot"
PLAN="$REPO_ROOT/exam-artifacts/r1-f3/run-plan.json"
RUN_LOG="$REPO_ROOT/exam-artifacts/r1-f3/r1-f3-run-5d884c47-36d724b1.log"
SHA_SHORT="5d884c47"
WAVE_IDX="${1:?wave index 0..2 for iter 1..3}"
AUDIT="$REPO_ROOT/exam-artifacts/r1-f3/slot-audit-f3-5d884c47-36d724b1.ndjson"
APPEND="$REPO_ROOT/exam-artifacts/r1-f3/append-slot-audit-line.mjs"
MERGE="$REPO_ROOT/exam-artifacts/r1-f3/merge-slot-into-wave-json.mjs"
SLOT_WALL_SEC="${SLOT_WALL_SEC:-900}"

SYSPROMPT_CHARS="${2:?sysprompt chars}"
SYSPROMPT_SHA="${3:?sysprompt sha}"
MODEL_JSON="${4:?model json}"
FIX_SHA_FULL="${5:?fixture pin sha}"

readarray -t WAVE_META < <(python3 - <<PY
import json
plan=json.load(open("$PLAN"))
w=plan["waves"][$WAVE_IDX]
print(w["iteration"])
print(w["outputJson"])
PY
)
ITER="${WAVE_META[0]}"
OUT="$REPO_ROOT/${WAVE_META[1]}"
mapfile -t IDS < <(python3 - <<PY
import json
print("\n".join(json.load(open("$PLAN"))["waves"][$WAVE_IDX]["evalIds"]))
PY
)

HERMETIC=(env -i HOME="$HOME" PATH="$PATH" USER="${USER:-ubuntu}" TMPDIR="${TMPDIR:-/tmp}"
  CURSOR_API_KEY="${CURSOR_API_KEY:?CURSOR_API_KEY required}" R2_METHOD_ARM=A)

mkdir -p "$(dirname "$OUT")"
if [[ ! -f "$OUT" ]]; then
  python3 -c "import json; json.dump({'results':[]}, open('$OUT','w'))"
fi

echo "WAVE_${ITER}_CAP_START $(date -u +%Y-%m-%dT%H:%M:%SZ) slots=${#IDS[@]} slot_wall_s=${SLOT_WALL_SEC}" | tee -a "$RUN_LOG"

for EVAL_ID in "${IDS[@]}"; do
  if python3 - <<PY
import json, sys
out=json.load(open("$OUT"))
sys.exit(0 if any(r.get("id")=="$EVAL_ID" for r in out.get("results",[])) else 1)
PY
  then
    echo "SLOT_SKIP eval_id=${EVAL_ID} already_in_wave_json" | tee -a "$RUN_LOG"
    continue
  fi
  readarray -t PARSED < <(python3 - <<PY
e="$EVAL_ID"
parts=e.split("/")
print(parts[-2] if len(parts)>=2 else e)
print(parts[-1] if parts else "?")
PY
)
  CASE_ID="${PARSED[0]}"
  ITER_NUM="${PARSED[1]}"
  SLOT_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "SLOT_START eval_id=${EVAL_ID} case=${CASE_ID} iteration=${ITER_NUM} at=${SLOT_START}" | tee -a "$RUN_LOG"
  SLOT_JSON="$(mktemp /tmp/r1-slot-XXXX.json)"
  STATE="/tmp/r1-slot-state-$$-${RANDOM}"
  rm -rf "$STATE"
  set +e
  timeout --kill-after=30 "$SLOT_WALL_SEC" "${HERMETIC[@]}" bash -lc \
    "cd '$BOT' && npx agent-sdk eval --dir . $(printf '%q' "$EVAL_ID") --json --no-stream --max-concurrency 1 --state-root '$STATE' --out '$SLOT_JSON'"
  EC=$?
  set -e
  SLOT_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  rm -rf "$STATE"
  if [[ "$EC" -eq 124 ]] || [[ "$EC" -eq 137 ]]; then
    echo "slot_timeout case=${CASE_ID} iteration=${ITER_NUM} eval_id=${EVAL_ID} at=${SLOT_END}" | tee -a "$RUN_LOG"
    node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$SYSPROMPT_CHARS" --sysprompt-sha "$SYSPROMPT_SHA" \
      --model-json "$MODEL_JSON" --fixture-pin "$FIX_SHA_FULL" --pack-b-v3 true \
      --eval-id "$EVAL_ID" --case-id "$CASE_ID" --iteration "$ITER_NUM" \
      --slot-started-at "$SLOT_START" --slot-ended-at "$SLOT_END" --timed-out true
    rm -f "$SLOT_JSON"
    echo "SLOT_END eval_id=${EVAL_ID} exit=timeout" | tee -a "$RUN_LOG"
    continue
  fi
  if [[ "$EC" -ne 0 ]] || [[ ! -s "$SLOT_JSON" ]]; then
    echo "STOP slot_failed eval_id=${EVAL_ID} exit=${EC}" | tee -a "$RUN_LOG"
    exit 11
  fi
  node "$MERGE" "$OUT" "$SLOT_JSON" "$EVAL_ID"
  node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$SYSPROMPT_CHARS" --sysprompt-sha "$SYSPROMPT_SHA" \
    --model-json "$MODEL_JSON" --fixture-pin "$FIX_SHA_FULL" --pack-b-v3 true \
    --eval-id "$EVAL_ID" --case-id "$CASE_ID" --iteration "$ITER_NUM" \
    --slot-started-at "$SLOT_START" --slot-ended-at "$SLOT_END" --slot-json "$SLOT_JSON"
  rm -f "$SLOT_JSON"
  echo "SLOT_END eval_id=${EVAL_ID} exit=${EC}" | tee -a "$RUN_LOG"
done

N="$(python3 -c "import json; print(len(json.load(open('$OUT')).get('results',[])))")"
echo "WAVE_${ITER}_CAP_END $(date -u +%Y-%m-%dT%H:%M:%SZ) results=${N} audit_lines=$(wc -l <"$AUDIT" | tr -d ' ')" | tee -a "$RUN_LOG"
