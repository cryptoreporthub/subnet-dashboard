# r24 Stage A harness (H2)

Parent harness: `b9ccd6a73295567775ab83761d1db5c2497ac0bc`

PRE bot pin: `23bd34f03fb4431ad29726f500f00efc9d1dd82b`  
POST bot pin: `a5819378e012cfe21b021bf2b6c5a52d5c4e2d7e`

## Contents

- 11 new `hard-r24-*` fixture directories (existing `hard-ci-skipped-tests` unchanged for MODIFY anchor)
- `review-gate-bot/evals/score-r24-first-line.py` — first-line verdict scorer (no dets)
- `stage-a-manifest.json` — Stage A fixture slugs + oracle labels
- `blind/*.md` — blind labeling packages (no oracle / rule text)
- `sha256-manifest.json` — SHA-256 of fixtures, scorer, blind files

Stage A **runs** wait for Claude **RUN-READY** after dry-run review (LOCK `6590596058`). No model eval until then. Run log will record per-run system blob SHA from runner `store.db` (per review-4).

## Runner

- `review-gate-bot/evals/review-gate-r24.eval.ts` — 12 cases (one per `stage-a-manifest.json` slug), no det gates
- `exam-artifacts/r24/run-plan.json` — seed `20261102`, 5 blocks × 2 invocations (regenerate: `python3 exam-artifacts/r24/gen_run_plan.py` @ committed tip)
- `exam-artifacts/r24/prove_worktrees.sh` — PRE/POST overlay proof
- `python3 exam-artifacts/r24/r24_dry_run.py` — synthetic scorer smoke (no `CURSOR_API_KEY`)

Regenerate fixtures: `python3 review-gate-bot/evals/oracle-gen/r24_stage_a.py`
