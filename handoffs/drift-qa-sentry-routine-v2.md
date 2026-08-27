# Drift/QA — Sentry Weekday Routine (v2, 2026-08-27)

Observation-only. Times: weekday **8am PT**. Quiet overnight unless new signal.

## Role (unchanged)
- **Observe only**: `search_issues`, `search_events`, issue links. Never mutate, never fix, never re-config.
- Fix-time debugging uses `sentry-debug-issue` — **Composer / Luna only**, and only when actually fixing a specific issue.
- No tracing: `traces_sample_rate` stays `0` on purpose. No browser SDK (P5 gated, never touch `cockpit_hydrate.js`). No Stage D alerts while timeout warnings remain the bulk of ingest.

## The report (v2 — delta-based, not re-assert)
Lead with **what changed**, not the known-alarm platitudes.

### 1. New / regressed / escalating (the headline)
Only genuinely new signal since last run leads. For each: **assign owner**, link the issue. Route, don't debug.

Current known-new (2026-08-27):
- `PYTHON-FASTAPI-Z` — resolver revive → **resolver/ops owner**, coordinate Sentinel.
- `PYTHON-FASTAPI-10` — pump-alerts FileNotFoundError → **Market Desk / pump owner**; watch for hydration-starvation recurrence (daily-pick class).

### 2. Canary — flag only on a DELTA
- `PYTHON-FASTAPI-6` (daily-pick-enrich timeout) is the **#1058 occupancy canary, not a root cause.**
- Do NOT headline it just because it's still firing (it will be, every day).
- Surface ONLY on: 24h event delta > X% vs prior 24h, OR new recurrence window. **Stable canary = in the report as one quiet status line.**

### 3. Known noise — ignore presence, flag regression
- `PYTHON-FASTAPI-5` (TaoStats `_POOL_LATEST_404` 404 noise, suppressed via #1046) is known noise.
- Ignore presence entirely. Care only if its rate **regresses** and the suppression appears broken.

### 4. Volume = deltas
- Use `vs prior 24h`, not raw 7d totals. Answers: is FASTAPI-6's share/velocity moving, or the same plateau? That's the "escalating vs stable" decision.

### 5. Keep off (do not arm)
- Stage D alerts. Browser SDK. Tracing. Any auto-deploy / self-merge.

## Out / previously-misrouted
- No daily "is FASTAPI-6 firing?" headline.
- No re-assertion of FASTAPI-5 presence.

## Companion files (source of truth)
- `handoffs/bot-fleet-fanout-2026-08-27.md` — roster + conflict-free routing.
- `_ci/mission_control_prompt.md` — Mission Control launch package.
- This file — Drift/QA Sentry routine v2.
