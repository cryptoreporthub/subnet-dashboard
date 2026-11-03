#!/usr/bin/env bash
set -euo pipefail
REPO="${REPO_ROOT:-/tmp/pr-1522-exam-r8-work/repo}"
R23_SHA="a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e"
C25_SHA="06269de964afc69bc81dd71156caa5bb2594bea1"
TIP_SHA="${TIP_SHA:-$(git -C "$REPO" rev-parse HEAD)}"
WT="${WT_ROOT:-/tmp/r25-wt-proof-$$}"
LOG="${1:-$REPO/exam-artifacts/r25/worktree-proof.log}"
MANIFEST="$REPO/exam-artifacts/r25/sha256-manifest.json"

exec > >(tee "$LOG") 2>&1
echo "=== r25 worktree overlay proof $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "REPO=$REPO R23_SHA=$R23_SHA C25_SHA=$C25_SHA TIP_SHA=$TIP_SHA"

cleanup() {
  git -C "$REPO" worktree remove -f "$WT/r23" 2>/dev/null || true
  git -C "$REPO" worktree remove -f "$WT/c25" 2>/dev/null || true
  rm -rf "$WT"
}
trap cleanup EXIT

mkdir -p "$WT"
git -C "$REPO" worktree add -q "$WT/r23" "$R23_SHA"
git -C "$REPO" worktree add -q "$WT/c25" "$C25_SHA"

mapfile -t OVERLAY < <(python3 - <<'PY' "$MANIFEST"
import json, sys
doc = json.loads(open(sys.argv[1]).read())
for path in sorted(doc):
    if path.startswith("review-gate-bot/"):
        print(path)
PY
)
for extra in review-gate-bot/evals/review-gate-r24.eval.ts review-gate-bot/evals/review-gate-r24b.eval.ts review-gate-bot/evals/review-gate-r25.eval.ts review-gate-bot/evals/r24-prompts.ts review-gate-bot/evals/r25-prompts.ts; do
  OVERLAY+=("$extra")
done
readarray -t OVERLAY < <(printf '%s\n' "${OVERLAY[@]}" | sort -u)

for path in "${OVERLAY[@]}"; do
  [[ -z "$path" ]] && continue
  [[ "$path" == "review-gate-bot/bot/instructions.md" ]] && continue
  for wt in r23 c25; do
    mkdir -p "$(dirname "$WT/$wt/$path")"
    git -C "$REPO" show "$TIP_SHA:$path" > "$WT/$wt/$path"
  done
done
for wt in r23 c25; do
  ln -sfn "$REPO/review-gate-bot/node_modules" "$WT/$wt/review-gate-bot/node_modules"
  ln -sfn "$REPO/exam-artifacts" "$WT/$wt/exam-artifacts"
done

python3 - <<PY
import hashlib, json, os
manifest = json.loads(open("$MANIFEST").read())
paths = """$(printf '%s\n' "${OVERLAY[@]}")""".strip().splitlines()
bad = []
for rel in paths:
    if rel == "review-gate-bot/bot/instructions.md":
        continue
    if rel not in manifest:
        bad.append(f"missing from manifest: {rel}")
        continue
    for wt in ("r23", "c25"):
        p = os.path.join("$WT", wt, rel)
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if h != manifest[rel]:
            bad.append(f"{wt}:{rel} got {h} want {manifest[rel]}")
if bad:
    print("FAIL\\n" + "\\n".join(bad))
    raise SystemExit(1)
print(f"OK overlay sha256 match ({len(paths)} paths)")
PY

set +e
diff -rq "$WT/r23/review-gate-bot" "$WT/c25/review-gate-bot" > /tmp/r25-wt-diff.txt
DIFF_RC=$?
set -e
cat /tmp/r25-wt-diff.txt
[[ "$DIFF_RC" -eq 1 ]] || exit 1
[[ "$(wc -l < /tmp/r25-wt-diff.txt)" -eq 1 ]] || { echo "FAIL not exactly one file diff"; exit 1; }
grep -q instructions.md /tmp/r25-wt-diff.txt || { echo "FAIL diff not instructions"; exit 1; }
echo "PASS worktree proof"
