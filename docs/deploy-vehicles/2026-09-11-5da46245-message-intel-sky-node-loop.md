# Deploy vehicle — trending sky node loop bound (#1284)

| | |
|---|---|
| Vehicle type | Docs-only Fly deploy vehicle |
| Target | refs/heads/main (post-merge) |
| Ships | PR #1284 — bound trending sky node loop by list.length |
| Base main | 5da4624518d067c488296ed8ea3f047e7149f5cc |

## Why a vehicle is required

Push-to-main deploys are disabled (INCIDENT 2026-08-19), so the deploy lever is the
`fly-deploy` label on a same-repo PR.

## What this deploy ships

### #1284 — stop the trending orbit rendering as static chrome with zero nodes

- `static/js/message_intel_feed.js`: `renderTrendingSky`'s node loop ran a fixed three
  iterations while `list` is `rows.slice(0, 3)`. With 1–2 rows the tail iteration
  dereferenced `undefined` and threw on `row.sentiment`. The throw occurred after
  `skyEl.hidden = false` and `data-empty="false"` were set but before `innerHTML` was
  assigned — leaving the sky visible, marked non-empty, and rendering zero nodes. The loop
  is now bounded by `list.length`.
- 0 rows was already handled by the existing early return and is unchanged; ≥3 rows is
  unaffected.

Verified by extracting the function verbatim from the deployed bundle and executing it
against controlled inputs: 0 rows → graceful, 1–2 rows → TypeError, 3 rows → ok.

## Post-deploy expectation

`/version` equals the post-merge main short SHA (`5da46245`). The trending orbit renders N
nodes for N in 1..3 instead of throwing; 0 rows still hides the sky.

## Not in this deploy

- **#1282** (pluralize the proof-gated graded-call count) — green, reviewed, not merged.
- **#1283** (select 1h/4h price columns in activity + conviction receipts) — **blocked by a
  failing `smoke` check.** Its branch contains a leaked markdown extraction header
  (`Title:` / `URL Source:`) at the top of `internal/message_intel/rollup.py`, which is a
  Python syntax error. Do not merge as-is; needs a faithful re-push. Tracked separately.
