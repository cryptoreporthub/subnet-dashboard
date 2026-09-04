# Deploy vehicle — liveness status-aware revive

- **Date:** 2026-09-04
- **Deploys main SHA:** `d654aab5c764e4094a2544d7cd59cc1d53f14b5c` (short: `d654aab`)
- **Source PR:** #1182 (`fix/liveness-status-aware-revive`)
- **Authorization:** approved-by-Joshua via Mission Control prompt (2026-09-04)
- **Scope:** doc-only vehicle to trigger Fly Deploy via `fly-deploy` label after merge
- **Change deployed:** status-aware `revive_score_snapshot_scheduler()` — running when lifecycle ≠ `new` and (lifecycle == `started` OR status ∈ {failing, stale, starved})

Do not use this vehicle for any other SHA.
