#!/usr/bin/env bash
# Resume R1-A2 after WAVE_1: backfill slot-audit from iter1 JSON, then run waves 2–3 only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BOT="$REPO_ROOT/review-gate-bot"
PLAN="$REPO_ROOT/exam-artifacts/r1-packb-a/run-plan.json"
EXTRACT="$REPO_ROOT/exam-artifacts/r1-packb-a/extract-slot-audit.mjs"
SHA_SHORT="5d884c47"
FIX_SHA_FULL="$(python3 -c "import json; print(json.load(open('$PLAN'))['fixturePinSha'])")"
FIX_SHA="${FIX_SHA_FULL:0:8}"
RUN_LOG="$REPO_ROOT/exam-artifacts/r1-packb-a/r1-packb-a2-run-${SHA_SHORT}.log"
AUDIT="$REPO_ROOT/exam-artifacts/r1-packb-a/slot-audit-a2-${SHA_SHORT}.ndjson"
ITER1="$REPO_ROOT/exam-artifacts/r1-packb-a/runs/review-gate-r1packb-iter1-${SHA_SHORT}.json"

if [[ ! -f "$EXTRACT" ]]; then
  echo "STOP: missing extract-slot-audit.mjs at $EXTRACT"
  exit 2
fi
if [[ ! -f "$ITER1" ]]; then
  echo "STOP: missing wave-1 output $ITER1"
  exit 2
fi

exec >> >(tee -a "$RUN_LOG") 2>&1
echo "=== R1-A2 resume waves 2–3 $(date -u +%Y-%m-%dT%H:%M:%SZ) harness=$SHA_SHORT fixtures=$FIX_SHA ==="
echo "git_rev=$(git -C "$REPO_ROOT" rev-parse HEAD)"
echo "resume_path=backfill_wave1_audit_then_waves_2_3"

cd "$BOT"
export R2_METHOD_ARM=A

PREF="$(bash "$REPO_ROOT/exam-artifacts/r1-packb-a/preflight-r1-packb-a.sh")"
echo "$PREF"
echo "$PREF" | grep -q preflight_ok || { echo "STOP preflight failed"; exit 3; }

SYSPROMPT_CHARS="$(echo "$PREF" | sed -n 's/^sysprompt_chars=\([0-9]*\)$/\1/p' | head -1)"
SYSPROMPT_SHA="$(echo "$PREF" | sed -n 's/^sysprompt_sha256=\([a-f0-9]\{64\}\)$/\1/p' | head -1)"
MODEL_JSON="$(echo "$PREF" | sed -n 's/^model_object=\(.*\)/\1/p')"
if [[ ${#SYSPROMPT_SHA} -ne 64 ]]; then
  echo "STOP: empty sysprompt sha256 (V1)"
  exit 5
fi

W1_COUNT="$(python3 -c "import json; print(len(json.load(open('$ITER1')).get('results',[])))")"
if [[ "$W1_COUNT" -ne 48 ]]; then
  echo "STOP: iter1 result count $W1_COUNT (expected 48)"
  exit 6
fi

AUDIT_LINES="$(wc -l <"$AUDIT" | tr -d ' ')"
if [[ "$AUDIT_LINES" -eq 0 ]]; then
  echo "WAVE_1_AUDIT_BACKFILL $(date -u +%Y-%m-%dT%H:%M:%SZ) from=$ITER1"
  node "$EXTRACT" "$ITER1" "$AUDIT" "$SYSPROMPT_CHARS" "$SYSPROMPT_SHA" "$MODEL_JSON" "$FIX_SHA_FULL" "true"
  echo "WAVE_1_AUDIT_BACKFILL_DONE lines=$(wc -l <"$AUDIT" | tr -d ' ')"
elif [[ "$AUDIT_LINES" -lt 48 ]]; then
  echo "STOP: partial audit ($AUDIT_LINES lines); need clean restart"
  exit 7
fi

HERMETIC=(env -i
  HOME="$HOME"
  PATH="$PATH"
  USER="${USER:-ubuntu}"
  TMPDIR="${TMPDIR:-/tmp}"
  CURSOR_API_KEY="${CURSOR_API_KEY:?CURSOR_API_KEY required}"
  R2_METHOD_ARM=A
)

for wave_idx in 1 2; do
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
  STATE="/tmp/r1-packb-a-state-iter${ITER}-$$"
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
  node "$EXTRACT" "$OUT" "$AUDIT" "$SYSPROMPT_CHARS" "$SYSPROMPT_SHA" "$MODEL_JSON" "$FIX_SHA_FULL" "true"
  echo "WAVE_${ITER}_WROTE $OUT_REL audit_lines=$(wc -l <"$AUDIT" | tr -d ' ')"
  rm -rf "$STATE"
done

FINAL_LINES="$(wc -l <"$AUDIT" | tr -d ' ')"
echo "=== R1-A2 pack B run complete $(date -u +%Y-%m-%dT%H:%M:%SZ) audit_lines=$FINAL_LINES ==="
if [[ "$FINAL_LINES" -ne 144 ]]; then
  echo "STOP: expected 144 audit lines, got $FINAL_LINES"
  exit 8
fi
