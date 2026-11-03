#!/usr/bin/env bash
# Prove PRE/POST worktrees differ only in bot/instructions.md after identical H2 overlay @ content tip.
set -euo pipefail
REPO="${REPO_ROOT:-/tmp/pr-1522-exam-r8-work/repo}"
PRE_SHA="23bd34f03fb4431ad29726f500f00efc9d1dd82b"
POST_SHA="a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e"
TIP_SHA="${TIP_SHA:-$(git -C "$REPO" rev-parse HEAD)}"
WT="${WT_ROOT:-/tmp/r24-wt-proof-$$}"
LOG="${1:-$REPO/exam-artifacts/r24/worktree-proof.log}"
MANIFEST="$REPO/exam-artifacts/r24/sha256-manifest.json"

exec > >(tee "$LOG") 2>&1

echo "=== r24 worktree overlay proof $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "REPO=$REPO"
echo "overlay_source=$(git -C "$REPO" rev-parse HEAD) (TIP_SHA=$TIP_SHA for git show paths)"
echo "Only bot/instructions.md should differ between PRE and POST worktrees after overlay."
echo

cleanup() {
  git -C "$REPO" worktree remove -f "$WT/pre" 2>/dev/null || true
  git -C "$REPO" worktree remove -f "$WT/post" 2>/dev/null || true
  rm -rf "$WT"
}
trap cleanup EXIT

mkdir -p "$WT"
git -C "$REPO" worktree add -q "$WT/pre" "$PRE_SHA"
git -C "$REPO" worktree add -q "$WT/post" "$POST_SHA"

overlay_paths() {
  python3 - <<'PY' "$MANIFEST"
import json, sys
doc = json.loads(open(sys.argv[1]).read())
for path in sorted(doc):
    if path.startswith("review-gate-bot/"):
        print(path)
PY
  echo "review-gate-bot/evals/review-gate-r24.eval.ts"
  echo "review-gate-bot/evals/review-gate-r24b.eval.ts"
  echo "review-gate-bot/evals/r24-prompts.ts"
}

mapfile -t OVERLAY < <(overlay_paths | sort -u)
for path in "${OVERLAY[@]}"; do
  [[ -z "$path" ]] && continue
  for wt in pre post; do
    mkdir -p "$(dirname "$WT/$wt/$path")"
    git -C "$REPO" show "$TIP_SHA:$path" > "$WT/$wt/$path"
  done
done

echo "=== SHA256 overlay check (manifest) ==="
python3 - <<PY
import hashlib, json, os
repo = "$REPO"
manifest = json.loads(open("$MANIFEST").read())
paths = """$(printf '%s\n' "${OVERLAY[@]}")""".strip().splitlines()
bad = []
for rel in paths:
    if rel not in manifest:
        bad.append(f"missing from manifest: {rel}")
        continue
    for wt in ("pre", "post"):
        p = os.path.join("$WT", wt, rel)
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if h != manifest[rel]:
            bad.append(f"{wt}:{rel} got {h} want {manifest[rel]}")
if bad:
    print("FAIL")
    print("\\n".join(bad))
    raise SystemExit(1)
print(f"OK {len(paths)} overlaid paths match sha256-manifest.json on both worktrees")
PY

echo
echo "=== diff -rq review-gate-bot PRE vs POST (after overlay) ==="
set +e
diff -rq "$WT/pre/review-gate-bot" "$WT/post/review-gate-bot"
DIFF_RC=$?
set -e
if [[ "$DIFF_RC" -ne 1 ]]; then
  echo "unexpected diff exit $DIFF_RC"
  exit 1
fi

echo
echo "=== unified diff (expect instructions.md only) ==="
git diff --no-index "$WT/pre/review-gate-bot/bot/instructions.md" "$WT/post/review-gate-bot/bot/instructions.md" || true

set +e
DIFF_LINES=$(diff -rq "$WT/pre/review-gate-bot" "$WT/post/review-gate-bot")
DIFF_RC=$?
set -e
echo "$DIFF_LINES"
if [[ "$DIFF_RC" -ne 1 ]]; then
  echo "FAIL: expected diff exit 1 (one file), got $DIFF_RC"
  exit 1
fi
if [[ "$(echo "$DIFF_LINES" | wc -l)" -ne 1 ]]; then
  echo "FAIL: expected exactly one differing file"
  exit 1
fi
if ! echo "$DIFF_LINES" | grep -q 'bot/instructions.md'; then
  echo "FAIL: sole diff is not instructions.md"
  exit 1
fi
echo "PASS: sole difference is review-gate-bot/bot/instructions.md"
