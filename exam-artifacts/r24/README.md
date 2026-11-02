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

Stage A **runs** wait for Claude LOCK comment on PR #1544 (step 4). Run log will record per-run system blob SHA from runner `store.db` (per review-4).

Regenerate fixtures: `python3 review-gate-bot/evals/oracle-gen/r24_stage_a.py`
