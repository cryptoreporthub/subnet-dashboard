# PR-1522 review-agent project: comms channel

DO NOT MERGE. This draft PR exists only so comments wake the agents. Close it when the project is done.

## Goal (definition of done)
A good review agent: the `review-gate-bot` gives correct verdicts on hard fixtures without over-blocking legitimate changes. Done = fix proven on locked bars, over-block risk measured on a new oracle-PASS pack, outside review passed, and PR #1522 is ready for Joshua's merge GO.

## Owner
Claude (planner, reviewer, implementer, project owner). Cursor implements and runs exams when asked. Joshua gives final merge GO only.

## Protocol
1. Read the newest `ROUND` comment on this PR first. Obey its `GATE` line.
2. One comment per finished step. Fixed fields:
   `ROUND`, `PINS` (full SHAs), `BARS (locked before run)`, `RESULT`, `ARTIFACT_BRANCH`, `NEXT_ACTION`, `OWNER`, `GATE`.
3. Artifacts go on branch `exam-artifacts/r<N>` (never PR-bound), file names include the SHA.
4. Bars are written in a comment before any run. No retro-editing after scores.
5. Reviewer/judge: Composer 2.5, fast: false. Never Composer fast.
6. Pinned eval stack: bot 50e231f3 + r18, harness b9ccd6a7, eval stub post_verdict posted:true reason:eval, no r19 overlay. Do not mix new fixtures into pin b9ccd6a7; new harness commit instead.
7. Standing GO (Joshua): comms PR, comments, `exam-artifacts/*` pushes, running exams.
   Needs Joshua GO each time: any push to PR #1522's branch, any merge, any deploy.
8. STOP r21: no C1/C2 merge. r22 shelved. Empty-key 45 parked.

## Current gate
GATE: HOLD for Cursor to publish r23 artifacts (see first Claude comment for the list).
