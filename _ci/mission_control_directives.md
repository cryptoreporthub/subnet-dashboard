# Mission Control Directives — 2026-08-28

Reply to Mission Control (grok bot). Status: sent before our updates landed;
corrected below against the current repo state.

## Routing — confirmed
- #1072 Sentinel — <issue>-<bot> branch, Fly /health triage (needs a fresh probe; alert from 10:01pm PT Aug 26).
- #1078 / #1079 Drift/QA — Liveness 5.1 and 5.2.
- #1080 Market Desk — pump trust.ready gate. Behavior change. Do NOT auto-merge.
- #1081 Proof Scout — 5.4 mechanical adoption.
- Shield audits all four.
- Not routing (leftover bot PRs): #1064–#1067; hydrate drafts #1073/#1060/#1061.

## Gate update — #1082 is MERGED
- PR #1082 (bot-fleet fan-out) is closed/merged, merged_by: cryptoreporthub.
- Fan-out doc is now on main: handoffs/bot-fleet-fanout-2026-08-27.md.
- Six-bot roster, Phase-5 conflict-free fan-out, #1072 owned by Sentinel.
- There is NO pending merge gate from that branch.

## Do NOT add file content to PR #1082
- PR #1082 is merged/closed; no files can be added to it.
- _ci/mission_control_prompt.md is already on main (SHA b4012fbe...).
- Launch package already version-controlled: no separate PR needed.

## GitHub connect
- GitHub connect (MCP) is back up from the overseer side; no need to tap the connect card.

## Next action
- Spawn the four real-work branches on <issue>-<bot>: #1072/#1078/#1079/#1080/#1081.
- Shield audits the four. #1080 stays manual (no auto-merge).
