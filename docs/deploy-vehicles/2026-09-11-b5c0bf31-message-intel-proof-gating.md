# Deploy vehicle — message-intel proof gating + Subnet Summers formatting (#1275, #1277)

| | |
|---|---|
| Vehicle type | Docs-only Fly deploy vehicle |
| Target | refs/heads/main (post-merge) |
| Ships | PR #1277 — proof-gate call leaderboard stats, silently exclude desk accounts |
| Ships | PR #1275 — Subnet Summers summary formatting (double-label, pluralization, 4096 cap) |
| Base main | b5c0bf3157a4fdb2d8be68bd18a421687d498ce2 |

## Why a vehicle is required

Push-to-main deploys are disabled (INCIDENT 2026-08-19). The only deploy levers are
workflow_dispatch on main, or applying the exact label fly-deploy to a same-repo PR.

This PR is docs-only under docs/deploy-vehicles/, so once it is merged and labeled, the
Deploy Guard resolves refs/heads/main and ships the current main HEAD — which includes
#1275 and #1277.

## What this deploy ships

### #1277 — proof-gated call leaderboard (internal/message_intel/rollup.py)

- build_author_reliability_rows no longer falls back to the legacy author_reliability
  ledger (pre-contract TAO-price grading recorded as message counts). total_graded_calls,
  accuracy_pct, and graded_calls_caution now derive only from proof-gated graded/hits.
- Legacy counts remain available on the reliability_* fields for the caller-receipt view,
  where they are labelled as legacy.
- _author_rolling_quality reads graded/hits only, so the trending-subnet ChatterPower
  ranking (velocity x conviction x quality) can no longer be moved by pre-contract
  message counts.
- build_trending_subnets and _yesterday_top_accuracy now consume proof-gated
  _author_outcome_stats.
- New is_desk_author() silently excludes product-generated desk accounts
  (8661669822 / @SubnetSummerBot) from build_weekly_authors, build_trending_subnets,
  and build_reaction_crowns. No "filtered" note is surfaced.
- Tests updated to the new contract; added coverage for the desk helper, weekly authors,
  trending, and crowns.

### #1275 — Subnet Summers summary formatting (internal/message_intel/summary_bot.py)

- Double-label removal, pluralization fixes, and the 4096-character cap.

## Post-deploy expectation

- /version equals the post-merge main short SHA (b5c0bf3157).
- /api/message-intel/authors reports 0 graded calls for every current row (the legacy
  fallback is gone) and no longer includes the desk bot account. The honest empty state
  takes over: "No graded callers yet — leaderboard fills as calls resolve."
- /api/message-intel/trending-v2 quality terms derive only from proof-gated call stats.

## Non-goals

No config or secret changes, no other workflows. #1276 (Subnet Summers restyle) is NOT
included — it is stacked and carries no CI checks yet.
