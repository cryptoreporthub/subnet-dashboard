#!/usr/bin/env bash
# R2 exam: 268 slots, 15m cap, per-slot bot checkout + R2_METHOD_ARM, stop on 2nd hang or V1 fail.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ART="$REPO_ROOT/exam-artifacts/r2"
BOT="$REPO_ROOT/review-gate-bot"
PLAN="$ART/run-plan.json"
BASE_SHA="532f3fbd"
FIX_SHA="d7345633"
TAG="${BASE_SHA}-${FIX_SHA}"
RUN_LOG="$ART/r2-run-${TAG}.log"
AUDIT="$ART/slot-audit-r2-${TAG}.ndjson"
AGG="$ART/runs/review-gate-r2-${TAG}.json"
SYNC="$ART/sync-bot-checkout.sh"
PREF="$ART/preflight-r2-slot.sh"
APPEND="$ART/append-slot-audit-line.mjs"
MERGE="$ART/merge-slot-into-wave-json.mjs"
STRIKE_FILE="$ART/.hang-strikes"
PROGRESS_FILE="$ART/.run-progress.json"
SLOT_WALL_SEC="${SLOT_WALL_SEC:-900}"

mkdir -p "$ART/runs"
: >"$AUDIT"
echo '{"results":[]}' >"$AGG"
echo 0 >"$STRIKE_FILE"

exec >>"$RUN_LOG" 2>&1
echo "=== R2 start $(date -u +%Y-%m-%dT%H:%M:%SZ) fixtures=${FIX_SHA} base_bot=${BASE_SHA} ==="
echo "fixture_pin_full=$(git -C "$REPO_ROOT" rev-parse HEAD)"
echo "plan_slots=$(python3 -c "import json; print(len(json.load(open('$PLAN'))['slots']))")"

TOTAL="$(python3 -c "import json; print(len(json.load(open('$PLAN'))['slots']))")"
START_IDX="${START_IDX:-0}"
SLOT_IDX=0

python3 - <<PY > /tmp/r2-slot-lines.tsv
import json
plan = json.load(open("$PLAN"))
for i, s in enumerate(plan["slots"]):
    print("\t".join([
        str(i),
        s["evalId"],
        s["condition"],
        s["role"],
        s["botCheckoutSha"],
        s["r2MethodArm"],
        s["caseSlug"],
        str(s["iteration"]),
    ]))
PY

cd "$BOT"
npm ci --silent 2>/dev/null || npm install --silent

while IFS=$'\t' read -r IDX EVAL_ID CONDITION ROLE BOT_SHA METHOD_ARM CASE_SLUG ITER_NUM; do
  if (( IDX < START_IDX )); then
    continue
  fi
  SLOT_IDX=$((SLOT_IDX + 1))
  echo "PROGRESS slot=$((IDX + 1))/${TOTAL} idx=${IDX} eval_id=${EVAL_ID} condition=${CONDITION} bot=${BOT_SHA:0:8} arm=${METHOD_ARM}"
  bash "$SYNC" "$BOT_SHA"
  export R2_METHOD_ARM="$METHOD_ARM"
  PREF_OUT="$(bash "$PREF")" || {
    echo "STOP V1 preflight fail eval_id=${EVAL_ID}"
    echo "$PREF_OUT"
    exit 10
  }
  SYSPROMPT_CHARS="$(echo "$PREF_OUT" | sed -n 's/^sysprompt_chars=\([0-9]*\)$/\1/p' | head -1)"
  SYSPROMPT_SHA="$(echo "$PREF_OUT" | sed -n 's/^sysprompt_sha256=\([a-f0-9]\{64\}\)$/\1/p' | head -1)"
  MODEL_JSON="$(echo "$PREF_OUT" | sed -n 's/^model_object=\(.*\)/\1/p')"
  FIX_FULL="$(python3 -c "import json; print(json.load(open('$PLAN'))['fixturePinSha'])")"

  SLOT_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "SLOT_START idx=${IDX} eval_id=${EVAL_ID} at=${SLOT_START}"
  SLOT_JSON="$(mktemp /tmp/r2-slot-XXXX.json)"
  STATE="/tmp/r2-slot-state-${IDX}-$$"
  rm -rf "$STATE"
  HERMETIC=(env -i HOME="$HOME" PATH="$PATH" USER="${USER:-ubuntu}" TMPDIR="${TMPDIR:-/tmp}"
    CURSOR_API_KEY="${CURSOR_API_KEY:?CURSOR_API_KEY required}" R2_METHOD_ARM="$METHOD_ARM")
  set +e
  timeout --kill-after=30 "$SLOT_WALL_SEC" "${HERMETIC[@]}" bash -lc \
    "cd '$BOT' && npx agent-sdk eval --dir . $(printf '%q' "$EVAL_ID") --json --no-stream --max-concurrency 1 --state-root '$STATE' --out '$SLOT_JSON'"
  EC=$?
  set -e
  SLOT_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  rm -rf "$STATE"

  if [[ "$EC" -eq 124 ]] || [[ "$EC" -eq 137 ]]; then
    STRIKES=$(($(cat "$STRIKE_FILE") + 1))
    echo "$STRIKES" >"$STRIKE_FILE"
    echo "slot_timeout eval_id=${EVAL_ID} at=${SLOT_END} strikes=${STRIKES}"
    node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$SYSPROMPT_CHARS" --sysprompt-sha "$SYSPROMPT_SHA" \
      --model-json "$MODEL_JSON" --fixture-pin "$FIX_FULL" --eval-id "$EVAL_ID" --case-id "$CASE_SLUG" \
      --iteration "$ITER_NUM" --condition "$CONDITION" --role "$ROLE" --bot-checkout-sha "$BOT_SHA" \
      --r2-method-arm "$METHOD_ARM" --slot-started-at "$SLOT_START" --slot-ended-at "$SLOT_END" --timed-out true
    rm -f "$SLOT_JSON"
    python3 - <<PY
import json
json.dump({"lastCompletedIdx": $IDX, "slotTimeoutCount": $STRIKES, "stopped": False}, open("$PROGRESS_FILE","w"))
PY
    if (( STRIKES >= 2 )); then
      echo "STOP second hang at eval_id=${EVAL_ID}"
      exit 12
    fi
    continue
  fi
  if [[ "$EC" -ne 0 ]] || [[ ! -s "$SLOT_JSON" ]]; then
    echo "STOP slot_failed eval_id=${EVAL_ID} exit=${EC}"
    exit 11
  fi
  node "$MERGE" "$AGG" "$SLOT_JSON" "$EVAL_ID"
  node "$APPEND" --audit "$AUDIT" --sysprompt-chars "$SYSPROMPT_CHARS" --sysprompt-sha "$SYSPROMPT_SHA" \
    --model-json "$MODEL_JSON" --fixture-pin "$FIX_FULL" --eval-id "$EVAL_ID" --case-id "$CASE_SLUG" \
    --iteration "$ITER_NUM" --condition "$CONDITION" --role "$ROLE" --bot-checkout-sha "$BOT_SHA" \
    --r2-method-arm "$METHOD_ARM" --slot-started-at "$SLOT_START" --slot-ended-at "$SLOT_END" --slot-json "$SLOT_JSON"
  rm -f "$SLOT_JSON"
  echo "SLOT_END idx=${IDX} eval_id=${EVAL_ID} exit=${EC} at=${SLOT_END}"
  python3 - <<PY
import json
from pathlib import Path
p=Path("$PROGRESS_FILE")
doc=json.loads(p.read_text()) if p.is_file() else {}
doc.update({"lastCompletedIdx": $IDX, "slotTimeoutCount": int(Path("$STRIKE_FILE").read_text().strip() or 0), "stopped": False})
p.write_text(json.dumps(doc))
PY
done < /tmp/r2-slot-lines.tsv

TO="$(grep -c slot_timeout "$RUN_LOG" 2>/dev/null || true)"
echo "=== R2 complete $(date -u +%Y-%m-%dT%H:%M:%SZ) audit_lines=$(wc -l <"$AUDIT" | tr -d ' ') slot_timeout_count=${TO} ==="
