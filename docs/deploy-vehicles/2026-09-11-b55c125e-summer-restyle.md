# Deploy vehicle — Subnet Summers Telegram restyle (#1276)

| | |
|---|---|
| Vehicle type | Docs-only Fly deploy vehicle |
| Target | refs/heads/main (post-merge) |
| Ships | PR #1276 — Restyle Subnet Summers Telegram desk (sections, attribution, author counts) |
| Base main | b55c125e08b7672277709059049dc3f2c197e14f |

## Why a vehicle is required

Push-to-main deploys are disabled (INCIDENT 2026-08-19). The only deploy levers are
workflow_dispatch on main, or applying the exact label fly-deploy to a same-repo PR.

This PR is docs-only under docs/deploy-vehicles/, so once it is merged and labeled, the
Deploy Guard resolves refs/heads/main and ships the current main HEAD — which includes
#1276.

## What this deploy ships

### #1276 — Subnet Summers Telegram restyle

- Professional sectioned layout for the Subnet Summers Telegram desk summary.
- Attribution and author counts on the trending payload: "authors": len(rank["author_ids"]).
- Test coverage extended for the restyled output (32 tests in the w6 bot suite).

### Carried forward (already live, unchanged)

#1275 summary formatting (double-label, pluralization, 4096 cap) and #1277 proof-gated
call leaderboard stats with silent desk-account exclusion are already deployed at
f5ee804d and remain in main.

## Merge-conflict resolution note

#1276 was stacked on #1275's branch and branched before #1277 landed. Retargeting it to
main surfaced a conflict in internal/message_intel/rollup.py, because both #1276 and
#1277 modified overlapping regions. Resolution (commit ba3f05dd):

- rollup.py: main (post-#1277) content plus #1276's single "authors" key addition.
- summary_bot.py and tests/test_summers_telegram_w6_bot.py: #1276's versions, which are
  byte-for-byte supersets of main's (main was verified identical to the formatter branch).

A merge of main into the branch (bbccf8b1d) then followed, and smoke passed.

## Post-deploy expectation

/version equals the post-merge main short SHA (b55c125e08b7). The /summary desk output uses
the restyled sectioned layout, and the trending payload includes the authors count.

## Non-goals

No config or secret changes, no other workflows.
