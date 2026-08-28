# Bot Delegation Briefs — 2026-08-28 (v3 — automation-first wording)

Purpose: Delegation-ready prompts for Mission Control to continue fan-out to each fleet bot, grounded in current progress.
Source: Ditto relay via _ci/. PR state as of 2026-08-28 ~06:45Z.

## ORDER OF OPERATIONS — #1091 LANDS FIRST
#1091 (cursor/mc-ditto-mirror-log) is the on-main Ditto<->MC relay: cursor-agents-communication/mission-control-log.md + .cursor/rules/ditto-sync.mdc mirror rule + board.md pointer. It is docs-only, so once CI is green it can move normally through the GitHub flow. If a human gate is needed, that gate should be called out explicitly.
1. UN-DRAFT #1091 (mark it ready).
2. Confirm CI green (docs-only: no app code, no fly.toml, no CI workflows — should pass clean).
3. MERGE #1091 when green.
4. Then rebase #1086 and dispatch briefs 2-6 below.

## 1. Mission Control (governor)
- UN-DRAFT + land #1091 FIRST (steps above).
- Rebase #1086 (1078-drift-qa) onto new main (collision with #1089 cleared; keep draft; CI green).
- Keep #1088 parked (human merge only; Tier-C behavior change).
- Dispatch briefs 2-6.

## 2. Sentinel
Post-merge soak: probe prod /health and /api/ops/live on Fly, desktop + 390px mobile, watch 24h for event-loop wedge recurrence. #1072 closed via #1089. Regressions: open issue + draft on <issue>-<bot>, do NOT merge.

## 3. Drift/QA
Rebase #1086 (1078-drift-qa) onto new main; continue #1090 (1079-drift-qa, hour-slot tracker + loop_health registry lookup). Owned files only; CI green before Shield.

## 4. Market Desk
HOLD #1088 (1080-market-desk) at draft — behavior change (trust.ready gate), park for explicit human approval only if that gate remains necessary. Validate only; never auto-merge a live change without the gate.

## 5. Proof Scout
Continue allowlist shrink 7 -> 0 (monotonic, guard fails re-adds) with conformance fixture updates, CI green. #1087 (1081-proof-scout).

## 6. Shield
Re-audit #1086 post-rebase, final audit #1088 before any human decision if one is still needed, spot-check landed #1089. Verdicts into MC log BEFORE any merge decision.

Report: per-bot {issue, branch, PR, CI status, owned files} into cursor-agents-communication/mission-control-log.md (post-#1091 merge).

Relayed by Ditto: 2026-08-28 ~06:45Z (v3 automation-first correction).
