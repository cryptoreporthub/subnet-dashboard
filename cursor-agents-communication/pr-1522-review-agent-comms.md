# PR-1522 review-agent project: comms channel

DO NOT MERGE. This draft PR exists only so comments wake the agents. Close it when the project is done.

## Goal (definition of done)
A good review agent: the `review-gate-bot` gives correct verdicts on hard fixtures without over-blocking legitimate changes. Done = fix proven on locked bars, over-block risk measured on a new oracle-PASS pack, outside review passed, and PR #1522 is ready for Joshua's merge GO.

## Owner
Claude = project lead: plans each round, locks bars, reviews adversarially, sets the GATE line, decides next steps. Claude does NOT implement fixes or run exams (no SDK/harness access).
Cursor = implementer and exam runner: code changes, live eval calls, scoring, artifact publishing. Cursor does not self-GO and does not change locked bars.
Joshua = final merge/deploy GO only.

## Protocol
1. Read the newest `ROUND` comment on this PR first. Obey its `GATE` line. The gate lives in that comment; this file does not carry a gate.
2. One comment per finished step. Fixed fields:
   `ROUND`, `PINS` (full 40-character SHAs, resolved, never a shell placeholder), `BARS (locked before run)`, `RESULT`, `ARTIFACT_BRANCH`, `NEXT_ACTION`, `OWNER`, `GATE`.
3. Artifacts go on branch `exam-artifacts/r<N>` (never PR-bound), file names include the SHA.
4. Bars are written in a comment before any run. No retro-editing after scores. A deviation (resume, backfill, fallback) is declared in writing with its fallback rule before the result is read.
5. Reviewer/judge: Composer 2.5, fast: false. Never Composer fast.
6. The bot under test is the shipping bot (#1522 head plus eval-only harness code). Measured runs never include product changes that have not won their own R2 arm.
7. Every SHA Cursor reports comes from a CLEAN CLONE of the pushed commit (`npm run check` 0 errors, `npm test` counts, SDK-composed prompt length via `loadAgentProject(...).agent.instructions.length`). Results from a working tree do not count. Claude re-runs the same on its own checkout.
8. Fidelity bars on every run: model object and prompt hash per slot (V1), no-post slots at most 10 percent (V2), eval tool output keys equal production keys (V3). Fixture titles and diffs use author voice; no defect-naming tokens; no copies of exam patches; claim text must appear in the title or diff.
9. Every slot has a wall-clock cap and start and end timestamps. A second hang stops the run and names the stuck case.
10. Scoring is done by Claude from raw JSON, accepted posts only (first `post_verdict` returning `posted:true`). Control fixtures are validated by two cold blind labelers plus decoys before they count.
11. Standing GO (Joshua, 2026-11-03/04): comms PR, comments, `exam-artifacts/*` pushes, running exams, arm branches, and pushing a measured diff to PR #1522's branch when the bars say it earned it. Merge and deploy of #1522 remain Joshua's decision.
12. Stop lists: C1/C2 not merged, r22 shelved, empty-key 45 parked.

