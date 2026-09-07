# Deploy Vehicle — Phase 3 (PR #1210)

Merge vehicle for PR #1210 (fix(resolver): Phase 3 mid-guards + orphan persist bound + revive budget).

## Shipped
- Merge commit on main: ba43ac42fe5ea8994761e9f077f513e3c7ac165f
- PR head merged: 1fe18c52f207789404d32a4d207775b2fc71a019
- Base at branch time: 31b7320553f645c528ce0a4215a2d3443ffca4c5
- Merge type: merge commit (not squash) — fix-up commit boundary preserved

## Scope landed
1. Mid-guards in resolve_due / expire_stale (cycle_abandoned short-circuit)
2. Orphan persist bound (_persist_owner_gen + _persist_lock, timeout force=True)
3. Revive budget (full cycle ceiling on boot revive, clear_burst_counters, next_run_at re-arm)
4. Dark-region telemetry (t1_5 checkpoint, persist sub-timers rmw/mutator, enforced_budget_s)

## CI receipts
- PR head (f4dcaf26): run 34159415648 — success
- PR fix-up head (1fe18c52): run 34161771821 — success
- Main push (ba43ac42): run 34165140578 — success

## Review
- Dual audit (Ditto line-by-line blob audit + Gemini design review), one required fix
  (persist sub-timer double-count) resolved via option B and re-audited on 1fe18c52.
- Post-deploy: verify revive arms (last_run_at advances, last_run_ok=true, next_run_at armed)
  and first live t1_5 / persist sub-timer readings on /api/predictions/resolver.
