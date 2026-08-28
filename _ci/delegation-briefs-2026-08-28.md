# Bot Delegation Briefs — 2026-08-28

Purpose: Delegation-ready prompts for Mission Control to continue fan-out to each fleet bot, grounded in current progress.
Source: Ditto relay via _ci/. PR state as of 2026-08-28 ~06:40Z.

1. Mission Control: rebase #1086 onto main (collision with #1089 cleared, keep draft, CI green). Merge #1091 (docs-only Ditto-MC mirror log) when CI green. Keep #1088 parked (human merge only). Dispatch briefs 2-6.
2. Sentinel: post-merge soak — probe prod /health and /api/ops/live on Fly, desktop + 390px mobile, watch 24h for event-loop wedge recurrence. #1072 closed via #1089. Regressions: open issue, draft on <issue>-<bot>, do NOT merge.
3. Drift/QA: rebase #1086 (1078-drift-qa) onto new main; continue #1090 (1079-drift-qa, hour-slot tracker + loop_health registry lookup). Owned files only; CI green before Shield.
4. Market Desk: HOLD #1088 (1080-market-desk) at draft — behavior change (trust.ready gate), park for explicit human approval. Validate only; never auto-merge.
5. Proof Scout: continue allowlist shrink 7 -> 0 (monotonic, guard fails re-adds) with conformance fixture updates, CI green. #1087 (1081-proof-scout).
6. Shield: re-audit #1086 post-rebase, final audit #1088 before any human decision, spot-check landed #1089. Verify verdicts into MC log before ANY merge decision.

Report: per-bot {issue, branch, PR, CI status, owned files} into cursor-agents-communication/mission-control-log.md (post-#1091 merge).

Relayed by Ditto: 2026-08-28 ~06:43Z.