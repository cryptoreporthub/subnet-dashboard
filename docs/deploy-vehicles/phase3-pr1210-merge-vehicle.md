# Deploy Vehicle — Phase 3 (PR #1210, corrected)

Deploy vehicle for PR #1210 (fix(resolver): Phase 3 mid-guards + orphan persist bound + revive budget).

Note: first vehicle attempt (#1211) placed this receipt under docs/vehicles/ and
was correctly refused by the fly.yml docs-only guard (fail-closed). This PR
uses the required docs/deploy-vehicles/ path.

## Shipped
- Phase 3 merge commit: ba43ac42fe5ea8994761e9f077f513e3c7ac165f
- PR #1210 head merged: 1fe18c52f207789404d32a4d207775b2fc71a019
- Merge type: merge commit (not squash)

## Scope landed
1. Mid-guards in resolve_due / expire_stale (cycle_abandoned short-circuit)
2. Orphan persist bound (_persist_owner_gen + _persist_lock, timeout force=True)
3. Revive budget (full cycle ceiling on boot revive, clear_burst_counters, next_run_at re-arm)
4. Dark-region telemetry (t1_5 checkpoint, persist sub-timers rmw/mutator, enforced_budget_s)

## CI receipts
- PR head (f4dcaf26): run 34159415648 — success
- PR fix-up head (1fe18c52): run 34161771821 — success
- Main push (ba43ac42): run 34165140578 — success
- Main push (d7212aa2, first vehicle): run 34165330050 — success

## Review
Dual audit (line-by-line blob audit + design review); one required fix
(persist sub-timer double-count) resolved via option B and re-audited.
Post-deploy: verify revive arms (last_run_at advances, last_run_ok=true,
next_run_at armed) and first live t1_5 / persist sub-timer readings.
