# r24 Stage A harness (H2)

**RUN_TIP** (git commit for frozen overlay) is posted on PR #1544 only after LOCK-2 dry run — not stored in repo files. Do not hand-edit SHAs; use `git rev-parse HEAD`.

**Content pins** live in `stage-a-manifest.json` → `contentPins` (SHA-256 of frozen `run-plan.json`, runner, prompts, scorer, and manifest body). `run-plan.json` has **no** `contentTip` (harness parent ref: `harnessParent` = `b9ccd6a73295567775ab83761d1db5c2497ac0bc`).

PRE bot pin: `23bd34f03fb4431ad29726f500f00efc9d1dd82b`  
POST bot pin: `a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e`

## Contents

- 11 new `hard-r24-*` fixture directories (existing `hard-ci-skipped-tests` unchanged for MODIFY anchor)
- `review-gate-bot/evals/score-r24-first-line.py` — first-line verdict scorer (unparseable post → `NO_POST`)
- `review-gate-bot/evals/r24-prompts.ts` — ci-skipped-anchor uses r23 verbatim prompt
- `stage-a-manifest.json` — Stage A slugs + `contentPins`
- `blind/*.md` — blind labeling packages
- `sha256-manifest.json` — SHA-256 of fixtures, scorer, blind files, overlay tree

Stage A **runs** wait for Claude **RUN-READY** (LOCK `6590596058`, LOCK-2 `6590681923`). No model eval until then.

## Runner

- `review-gate-bot/evals/review-gate-r24.eval.ts` — 12 cases, no det gates
- `exam-artifacts/r24/run-plan.json` — seed `20261102` (`python3 exam-artifacts/r24/gen_run_plan.py`)
- `exam-artifacts/r24/runs/` — raw invocation JSON + sysprompt hashes (see `runs/README.md`)
- `exam-artifacts/r24/prove_worktrees.sh` — PRE/POST overlay proof (`TIP_SHA` = `git rev-parse HEAD` at proof time)
- `exam-artifacts/r24/log_worktree_model_config.sh` — Composer 2.5 `fast:false` at PRE/POST pins
- `python3 exam-artifacts/r24/r24_dry_run.py` — no `CURSOR_API_KEY`

Regenerate fixtures: `python3 review-gate-bot/evals/oracle-gen/r24_stage_a.py`
