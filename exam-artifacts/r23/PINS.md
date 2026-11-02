# PR #1522 r23 exam — pinned refs (reachable on branch `exam-artifacts/r23`)

| Pin | Full SHA | Reachability |
|-----|----------|--------------|
| **PRE_SHA** (50e231f3 + r18 stack, before §1a) | `23bd34f03fb4431ad29726f500f00efc9d1dd82b` | `git checkout 23bd34f03fb4431ad29726f500f00efc9d1dd82b` on this branch |
| **POST_SHA** (PRE + Verdict-body §1a only) | `a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e` | branch tip @ push time (`mc/pr-1522-r23-exam` history) |
| **Harness** (eval stub `posted: true`, hard grader) | `b9ccd6a73295567775ab83761d1db5c2497ac0bc` | `git checkout b9ccd6a73295567775ab83761d1db5c2497ac0bc` (also `examlocal/mc/pr-1522-exam-harness`) |

## Eval stub (harness, not product `50e231f3`)

Copied @ harness pin:

- `exam-artifacts/r23/eval-stub/post_verdict.ts`
- `exam-artifacts/r23/eval-stub/check_gate_state.ts`

## r18 overlay

- `exam-artifacts/r23/r18-overlay/r18.diff` — apply on bot @ `50e231f36665066cbb8f3b646ec88d77bb90ded5` per exam setup

## Frozen scorer

- `internal/handoff-2026-10-31/pr-1522-r21/score-pre-five-pack.py`
- `internal/handoff-2026-10-31/pr-1522-r21/18-scorer-freeze.md`

## Exam JSON + logs

- `internal/handoff-2026-10-31/pr-1522-r23/` — progress.log, s13b outputs, `exams/*.json`
- `internal/handoff-2026-10-31/pr-1522-r21/exams/` — P1–P3 historical full-63 (`pre63`, `pre63-pre2`, `pre63-pre3`, five-packs)

## §13b helper dump @ POST_SHA

- Path: `review-gate-bot/evals/capture-eval-system-prompt.ts` (on POST commit)
- SHA-256 of composed instructions: `6637087582c794c1011219dd51951b4a9e829d3f24507a037a15c0570557d1fe`
- Lock-6 log line (`internal/handoff-2026-10-31/pr-1522-r23/progress.log` on this branch):
  `LOCK6_POST live=6637087582c794c1011219dd51951b4a9e829d3f24507a037a15c0570557d1fe helper=6637087582c794c1011219dd51951b4a9e829d3f24507a037a15c0570557d1fe MATCH`
- Live eval artifact: `internal/handoff-2026-10-31/pr-1522-r23/exams/s13b-live-ci-skipped-1-post-lock6.json`

## One POST_SHA live eval (`ci-skipped-tests-clean-comparison/1`)

Same command as PR comment **r23-cursor-status-2** (exam machine paths):

```bash
cd /tmp/pr-1522-exam-r8-work/repo \
  && git checkout a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e --quiet \
  && cd review-gate-bot \
  && DUMP=$(node --input-type=module -e "import {createHash} from 'crypto'; import {capture_eval_system_prompt} from './evals/capture-eval-system-prompt.ts'; const s=await capture_eval_system_prompt('.'); console.log(createHash('sha256').update(s).digest('hex');") \
  && echo "HELPER_DUMP=$DUMP" \
  && STATE=/tmp/r23-lock6-post-live && rm -rf "$STATE" && mkdir -p "$STATE" \
  && OUT=/cursor/stores/self/internal/handoff-2026-10-31/pr-1522-r23/exams/s13b-live-ci-skipped-1-post-lock6.json \
  && env -i HOME="$HOME" PATH="$PATH" USER="${USER:-}" CURSOR_API_KEY="$CURSOR_API_KEY" \
       npm run eval -- review-gate-hard/ci-skipped-tests-clean-comparison/1 --json --no-stream --max-concurrency 1 \
       --state-root "$STATE" --out "$OUT"
```

Portable checkout from this branch:

```bash
git fetch origin exam-artifacts/r23
git checkout a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e
cd review-gate-bot && npm ci
export CURSOR_API_KEY=…
env -i HOME="$HOME" PATH="$PATH" USER="${USER:-}" CURSOR_API_KEY="$CURSOR_API_KEY" \
  npm run eval -- review-gate-hard/ci-skipped-tests-clean-comparison/1 \
  --json --no-stream --max-concurrency 1 \
  --state-root /tmp/r23-post-live --out /tmp/ci-skipped-1-post.json
```
