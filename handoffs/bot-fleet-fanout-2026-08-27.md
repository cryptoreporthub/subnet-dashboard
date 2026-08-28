# SimiVision Grok Bot Fleet — Conflict-Free Fanout

**Status:** LIVE · **Date:** 2026-08-27
Source of truth: This file. Supersedes any earlier "nine-bot" planning blueprint. The fleet is exactly the six bots below; there is NO Remed/"Remedy" bot.

## The bot fleet (definitive)

Mission Control is the governor (orchestrates, gates, does not implement). All five specialist bots perform their own work; one of them (Market Desk) owns the pump/trust behavior change.

| Bot | Role | Build state |
|---|---|---|
| Mission Control | Orchestrator / CEO. Routes intents, risk-classifies, delegates to specialists, enforces approval governance. Does no hands-on coding. | Implemented |
| Sentinel | Read-only HealthReport composer. Owns site health/liveness and hotfix/deploy health routes. | Implemented |
| Drift (Drift/QA) | Observation-only QA observer. Eight read-only checks, evidence hygiene, freshness validation, shared audit logging. | Implemented, merged (PR #1068) |
| Market Desk | The pump / trading desk automation. Owns the live /pump dashboard and trading pick loop. | Live |
| Proof Scout | Evidence gathering + verification, policy-based freshness classification, read-only prediction loading. | Implemented |
| Shield | Read-only abuse/security detector. Four risk classes, approval-gated remediation, redacted audit logging. | Implemented |

## Current conflict-free fan-out (Phase 5 of LivenessTracker rollout)

LivenessTracker rollout family complete: #1028 to #1033 to #1075 to #1076 to #1077. Allowlist = 9 of 11. Open work: #1072 (live uptime) plus four Phase-5 follow-ups (#1078-#1081). Each owns disjoint file-sets -> zero merge collision.

| Bot | Issue(s) | Owned files (exclusive) | Goal |
|---|---|---|---|
| Sentinel | #1072 | Fly health, healthreport/hotfix routes, deployment | Triage + fix live uptime incident (site unhealthy 2026-08-27T05:01:38Z). |
| Drift/QA | #1078, #1079 | ops/readiness.py, /api/liveness consumers; internal/council/pick_scheduler.py (hour slot), learning/loop_health.py | Readiness reads the single registry endpoint; persist hour-slot run state via tracker; loop_health uses registry lookup (no _last_resolver_tick heuristics). |
| Market Desk | #1080 | internal/pump trust gate + probe/route | Gate trust.ready on liveness.snapshot('pump_ladder').status == 'ok'. Behavior change - park for approval before merge. |
| Proof Scout | #1081 | council/selector_scheduler.py, calibration/scheduler.py, tests/liveness_allowlist_state.json + tests | Mechanical tracker adoption with conformance fixture; allowlist shrinks 9 to empty. |
| Shield | cross-cutting | none (audits all four PRs) | Security/abuse gate for credential-bust, rate, or abuse classes across every PR. |

## Isolation rule
Each worker bot writes ONLY its owned file set above, mutually non-overlapping. No two bots touch the same path -> no merge collision.

## Mission Control gates (hard rules)
1. One PR per bot; branch <issue>-<bot>.
2. CI green before merge.
3. Allowlist must only shrink - the guard fails any re-add (monotonic).
4. Audit every PR for hand-rolled live ("ok" laundering, _running/_last_run_ok, literal status).
5. Park any behavior change (#1080) for explicit human approval - never auto-merge.
6. Report per bot: {issue, branch, PR, CI status, owned files}.

## Retired / superseded
- Any "nine approval-gated bots"/"Remedy Bot" planning text is superseded and NOT part of the fleet. Remedy Bot was never built and is not a live member.
- The prior docs/simivision-evidence-bot-blueprint.md remains as planning history; the operative roster is this file.