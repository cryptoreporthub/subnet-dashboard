# Deploy vehicle — proof-gated author-trust line (#1280)

| | |
|---|---|
| Vehicle type | Docs-only Fly deploy vehicle |
| Target | refs/heads/main (post-merge) |
| Ships | PR #1280 — proof-gate the message-intel author-trust line |
| Base main | e71a4415c8e7e39e2056d65d5529e2933bb40107 |

## Why a vehicle is required

Push-to-main deploys are disabled (INCIDENT 2026-08-19), so the deploy lever is the
fly-deploy label on a same-repo PR.

## What this deploy ships

### #1280 — stop reporting legacy message counts as graded calls

- internal/message_intel/summary.py: the "Author trust (closed loop)" sentence now reads the
  proof-gated build_author_reliability_rows, filters to total_graded_calls > 0, and ranks by
  accuracy then graded volume then influence. It no longer reads the legacy author_reliability
  ledger and no longer prints total_messages as "graded calls".
- Empty state when nothing has resolved: "No graded callers yet — leaderboard fills as calls
  resolve."
- tests/test_phase_c_mindmap_wiring.py: the old test seeded legacy rows and pinned the bug; it
  now asserts the legacy ledger is not presented as an author-trust record. Added coverage for
  the proof-graded leader sentence.

## Post-deploy expectation

/version equals the post-merge main short SHA (e71a4415c8e7). /api/message-intel/summary no
longer claims a legacy author "leads at N% over N graded calls" that disagreed with
/api/message-intel/authors.

## Non-goals

No config or secret changes. share_pages graded_count is intentionally left as total_messages
(templates/listener.html labels it "messages graded").
