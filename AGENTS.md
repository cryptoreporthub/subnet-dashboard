# AGENTS.md

## Cursor Cloud specific instructions

This repo is a single **FastAPI** (ASGI) web app, the "Subnet Dashboard" (Bittensor
subnet analytics + an AI "council" recommendation engine, branded **SimiVision** as
the intelligence layer). It has no external database, cache, or broker: state is
committed JSON under `config/` and `data/`, plus local SQLite files created on
demand. The app degrades gracefully when the optional external data APIs
(taomarketcap / taostats / Bittensor RPC) are unreachable, so no secrets or network
access are required to run it locally.

> Runtime note: the app was previously Flask/Gunicorn and was migrated to
> FastAPI/Uvicorn (the target foundation for streaming chat + a live message-intel
> feed). Do **not** reintroduce Flask/Gunicorn or a second server file — see the
> single-foundation rule below.

### Python environment
- Python 3.12. Dependencies are installed into a virtualenv at `.venv` by the
  startup update script. **Activate it before running anything:**
  `source .venv/bin/activate` (or call binaries as `.venv/bin/python` / `.venv/bin/pytest`).
- App dependencies live in `requirements.txt` (`fastapi`, `uvicorn[standard]`,
  `jinja2`, `pandas`, `requests`). `pytest` and `httpx` are dev-only tools installed
  separately by the update script (not in `requirements.txt`). `httpx` is required
  by `fastapi.testclient.TestClient`, so the test suite needs it.

### Running the app (development)
- Dev server: `python server.py` — runs Uvicorn with `--reload`. Honors `$PORT`
  (default `50745`). Example: `PORT=5000 python server.py`.
- Or directly: `uvicorn server:app --reload --port 5000`.
- Production (matches `Procfile` / `Dockerfile`): `uvicorn server:app --host 0.0.0.0 --port 8080`.
- Health check: `GET /health` returns `OK`. Main UI is `GET /`.

### Testing
- Run: `pytest` (from repo root, venv activated).
- `tests/test_endpoint_contract.py` is the **contract guard**: it asserts every
  route the app must serve returns non-5xx / 200. It also lists `NOT_YET_PORTED`
  routes from the historical monolith — add a route to `CONTRACT` when you port it.
  The Fly **Deploy Guard** runs this test and blocks any deploy that regresses it.
- Known **pre-existing** failures/errors unrelated to this work (do not assume the
  full suite is green): several modules (`test_judges.py`, `test_simivision.py`,
  `test_daily_pick_and_hour.py`, `test_learning_loop_fixes.py`, parts of
  `test_phase2.py`, `test_simivision_engine.py`, `test_signal_tracker.py`,
  `test_indicators.py`, `message_intel_test.py`) reference `server_original` or
  APIs/classes that no longer exist. These belong to the not-yet-ported feature
  slices and will be addressed as those routers are rebuilt.

### Code style

Follow [`.cursor/rules/ponytail.mdc`](.cursor/rules/ponytail.mdc) ([Ponytail](https://github.com/DietrichGebert/ponytail)): YAGNI, minimal diff, reuse existing patterns before adding files or dependencies. Do not cut validation, security, error handling, or contract-test coverage.

### Agent coordination (two Cursor agents)

**Concurrent J/H sprint (2026-07-11):** Read **`cursor-agents-communication/concurrent-protocol.md`** and **`cursor-agents-communication/board.md`** from git first. Do **not** use `fetch_memories(["f93f7202"])` for board STATUS this sprint.

**Post-H-full boot order:** `board.md` → **`model-guide.md`** (Composer vs Grok) → `shared-workspace.md` → `master-plan-merged.md`. Ditto planning: `ditto-phase-l-handoff.md`.

**Before any other rebuild work**, read the live board from Ditto using **both** search and the official artifact (do not use artifact-only — it can lag the thread):

1. **`search_memories`** query: `"Cursor Agents Communication"` (and optionally `"subnet-dashboard agent coordination"`).
2. Read the **newest** result whose body contains **`STATUS`** / **`GATE`** / **`main=`** — obey gate lines (e.g. do not start slice N while gated).
3. **`fetch_memories`** ids: **`["f93f7202"]`** — official board memory + attached `cursor-agents-communication.md` (protocol, ownership matrix, slice queue). If step 2 conflicts with the artifact, trust the **newer timestamp** or an explicit gate-clear post.
4. Optional precision: **`search_subjects`** `"Cursor Agents Communication"` → subject **`2a29897f`**, then **`search_memories_in_subjects`** with query `"STATUS main gate slice"`.
5. Repo mirror (may be stale): `docs/cursor-agents-communication.md`. Dedicated graph: `cursor-agents-communication-fd6d30`.

**After every merge or slice decision**, update **both** surfaces (keep them in sync):

1. **`save_memory`** — short STATUS post (`main=<sha>`, slice done/in progress, open PRs) with `source: cursor-agents-communication`.
2. **`update_memory`** memoryId **`f93f7202`** — refresh STATUS SNAPSHOT + your agent log on the artifact body/attachment.

**Do not ask the user to relay messages** between agents. One Ditto post is enough; do not copy-paste the board into the other agent's chat.

| Agent | Suffix | Owns | Do not touch |
|-------|--------|------|--------------|
| **A** | `-843d` | `internal/learning/*`, council slices (rotation, freshness, weights, scenario memory, pick history), Fly/CI | `internal/analytics/*`, `internal/oracle/*`, `internal/indicators/*`, `internal/ruggers/*`, `internal/whales/*` |
| **B** | `-e78a` | `internal/whales/*`, `internal/ruggers/*`, `internal/indicators/*`, `internal/oracle/*`, `internal/analytics/*` | `internal/learning/routes.py`, council rotation/freshness/weights slices |

**Conflict surface only:** `server.py` (`include_router` lines) + `tests/test_endpoint_contract.py` — rebase before merge if both agents had open PRs.

### The rebuild (Option B, FastAPI foundation)
- The current `server.py` serves a clean subset (subnets/registry/summary/stats/
  soul-map/recommendations/daily-rotation). The full product (SimiVision picks,
  council/judges, chat, message-intel) is being **ported incrementally** from the
  historical FastAPI monolith at `528ba62:server_original.py` (47-route contract).
- **Single-foundation rule:** keep exactly one server entrypoint (`server:app`).
  Never resurrect `server_original.py` or a parallel `server/` package as a second
  runtime — coexisting foundations caused the prior route-collision 422s. Port
  slice-by-slice into `server.py` (or app-internal routers imported by it), each
  with its routes added to the contract test.

### Deploy (Fly.io)
- `.github/workflows/fly.yml` deploys on push to `main`: a Deploy Guard (static
  checks + the endpoint-contract test) gates `flyctl deploy --remote-only --no-cache --yes`.
- `fly.toml` declares the persistent `[mounts]` `data_volume` → `/app/data`
  (soul-map / predictions / learning state + SQLite). Keep it declared so deploys
  reuse the volume. `flyctl` needs `FLY_API_TOKEN` (GitHub Actions secret); the
  cloud agent has no token, so volume creation (`fly volumes create`) must be done
  by a human / Ditto Code if a region/count mismatch ever arises.

### Not started by default (optional)
- Background schedulers (`internal/scheduler.py`, `internal/indicators/`,
  `internal/council/resolver_scheduler.py`) and the Telegram listener
  (`message_intel/telegram_listener.py`, needs `telethon` + Telegram creds) are
  optional enrichment and are not required to run or demo the dashboard.
