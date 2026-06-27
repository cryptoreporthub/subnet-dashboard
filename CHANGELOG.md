# Changelog

## v3.6.0 - 2026-06-27

### Added
- Subnet state vector endpoint: `/api/subnets/{netuid}/state` returns a structured state vector with metrics, technical indicators, signal impact, prediction, social sentiment, and consensus for a single subnet.
- Top Pick endpoints: `/api/top-pick/hour` and `/api/top-pick/day` return the highest-scoring subnet for each time window.
- SimiVision clickable jargon tooltips on the homepage: terms such as *conviction*, *emission*, *APY*, *recommendation*, *HOT*, and *SELL ALERT* are wrapped in `.jargon-term` spans and reveal glossary definitions on click.
- Top Pick of the Hour / Day UI section on the homepage, populated by the new top-pick endpoints and refreshed every 60 seconds.
- FastAPI `TestClient` test coverage for the new endpoints and homepage tooltip integration in `tests/test_new_features.py`.

### API Endpoints
- `GET /api/subnets/{netuid}/state` — subnet state vector (200 on success, 404 when netuid is unknown).
- `GET /api/top-pick/hour` — highest-scoring subnet over the current hour.
- `GET /api/top-pick/day` — highest-scoring subnet over the current day.
- `GET /api/simivision` — top performers (existing; unchanged payload shape).

### Frontend
- `templates/index.html`: Top Picks section, `.jargon-term` markup, glossary-driven tooltip system, and auto top-pick fetchers.
- `static/css/style.css`: `.jargon-term` and `.simi-tooltip` styles.

### Tests
- Added `tests/test_new_features.py` covering state vector, top picks, homepage tooltip markup, and existing FastAPI health/SimiVision routes.
- Legacy Flask-style tests remain incompatible with the current FastAPI implementation and are expected to fail until migrated.

## v3.5.1 - 2026-06-26

### Fixed
- Homepage now fetches live data from API endpoints
- React frontend uses `useApiData` hook for `/api/subnets`
- Auto-refresh every 30 seconds for live updates

### API Endpoints
- `/api/subnets` - 129 subnets from taomarketcap
- `/api/simivision` - Top performers
- `/api/rotation-tokens` - Rotation tokens
- `/api/mindmap/summary` - Mindmap data
- `/api/learning/stats` - Learning stats