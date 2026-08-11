# Changelog

## v3.5.2 - 2026-08-10 (deploy marker)

### Ops
- Marker commit to re-run Fly Deploy: after boot-502 fix (0d271931), the /health
gate returned 422 during the cold boot window, skipping cache-warm + learning-loop
post-deploy steps. This re-deploy runs them so /health flips to 200 and the run
goes green.

## v3.5.1 - 2026-06-26

### Fixed
- Homepage now fetches live data from API endpoints
- Jinja templates + vanilla JS fetch `/api/subnets` for live homepage data
- Auto-refresh every 30 seconds for live updates

### API Endpoints
- `/api/subnets` - 129 subnets from taomarketcap
- `/api/simivision` - Top performers
- `/api/rotation-tokens` - Rotation tokens
- `/api/mindmap/summary` - Mindmap data
- `/api/learning/stats` - Learning stats
