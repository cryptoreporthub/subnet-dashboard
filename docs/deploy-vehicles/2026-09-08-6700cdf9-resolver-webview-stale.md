# Deploy Vehicle — resolver web-view stale blind spot (#1220)

Deploy vehicle for main @ `6700cdf935951224a0dec177717ca8303348c1ac`
("Merge PR #1220: fix(learning) yield stale web resolver view to fresher persisted truth").

Receipt path: `docs/deploy-vehicles/` (required by fly.yml docs-only guard).

## Shipped on main
- Merge commit: `6700cdf935951224a0dec177717ca8303348c1ac`
- Change: `internal/learning/loop_health.py` `_build_resolver_liveness_view`
  - Prefer persisted registry when `last_success_at` is strictly newer (`_parse_iso`)
  - Keeps prior `no_success_yet`/`failing` → `ok` yield
  - No `_freshness` (out of scope); no boot-arm / revive / timeout changes

## Intent
Worker already healthy (cycles 03:43:08Z + 03:58:14Z). Defect was web-view
blind spot masking persisted truth as `stale`. Deploy clears the view only.

## Post-deploy asserts (+5min fresh reads)
- `/api/learning/health` resolver status != `stale`
- `/api/predictions/resolver` `last_run_at` > 03:58Z, availability=available, running=true
  (lifecycle may still read `stopped` — cosmetic)
- `/api/liveness` stays green
- Closure: two green reads ~10min apart; report patch-merged ≠ web-view-cleared separately
