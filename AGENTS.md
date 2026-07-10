# AGENTS.md

## Cursor Cloud specific instructions

This repo is a single **Flask** web app, the "Subnet Dashboard" (Bittensor subnet
analytics + an AI "council" recommendation engine). It has no external database,
cache, or broker: state is committed JSON under `config/` and `data/`, plus local
SQLite files created on demand. The app degrades gracefully when the optional
external data APIs (taomarketcap / taostats / Bittensor RPC) are unreachable, so
no secrets or network access are required to run it locally.

### Python environment
- Python 3.12. Dependencies are installed into a virtualenv at `.venv` by the
  startup update script. **Activate it before running anything:**
  `source .venv/bin/activate` (or call binaries as `.venv/bin/python` / `.venv/bin/pytest`).
- App dependencies live in `requirements.txt`. `pytest` is a dev-only tool and is
  installed separately by the update script (it is not in `requirements.txt`).

### Running the app (development)
- Dev server: `python server.py` — runs Flask with `debug=True` and the auto
  reloader. It honors `$PORT` (default `50745`). Example: `PORT=5000 python server.py`.
- Production-style (matches `Procfile` / `Dockerfile`): `gunicorn server:app --bind 0.0.0.0:8080`.
- Health check: `GET /health` returns `OK`. Main UI is `GET /`.

### Testing
- Run: `pytest` (from repo root, venv activated).
- Known **pre-existing** failures/errors unrelated to environment setup (do not
  assume the suite is green):
  - 4 test modules (`test_judges.py`, `test_simivision.py`, `test_daily_pick_and_hour.py`,
    `test_learning_loop_fixes.py`, and parts of `test_phase2.py`) import
    `fastapi` / `server_original`, which are stale — the current app is Flask, not
    FastAPI, and there is no `server_original` module. `fastapi` is intentionally
    not installed.
  - Several other tests (`test_simivision_engine.py`, `test_signal_tracker.py`,
    `test_indicators.py`, `message_intel_test.py`, `test_server.py::test_subnet_route_found`)
    reference APIs/behavior that no longer match the current code.
  - The bulk of the suite (~126 tests) passes.

### Gotcha: `server.py` was corrupted
- Historically `server.py` had all route definitions after `list_subnets`
  collapsed onto one physical line (a `SyntaxError` that broke both the app and
  every test, since all tests `import server`). This has been repaired by
  restoring newlines/indentation only. If you edit `server.py`, keep it as normal
  multi-line Python.

### Not started by default (optional)
- Background schedulers (`internal/scheduler.py`, `internal/indicators/`,
  `internal/council/resolver_scheduler.py`) and the Telegram listener
  (`message_intel/telegram_listener.py`, needs `telethon` + Telegram creds) are
  optional enrichment and are not required to run or demo the dashboard.
