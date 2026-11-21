---
name: repo-context-map
description: Use to find where things live in the subnet-dashboard repo before reading or editing. Maps the FastAPI entrypoint, the council and judges packages, the persistence and lock helpers, and the Fly deploy guards. Every path here was checked with a grep or a read at commit 1234511c.
---

# Repo context map

Read this before you grep. Each row names the file and the function to anchor on.
Line numbers drift, so search by name.

## Entry and deploy

| Need | Where | Anchor |
|---|---|---|
| The one ASGI app | `server.py` | `app` (uvicorn `server:app`) |
| Contract test (every served route) | `tests/test_endpoint_contract.py` | `CONTRACT`, `NOT_YET_PORTED` |
| Deploy guards (static, run in CI) | `.github/workflows/fly.yml` | Deploy Guard steps |
| Lint and format gates | `.github/workflows/ci-smoke.yml` | `black --check --line-length 88 server.py internal tests`, flake8 |
| Persistent volume | `fly.toml` | `[mounts]` `data_volume` to `/app/data` |

Do not add a second server file or a `server/` package. Port routes into `server.py`
or app-internal routers.

## Persistence and locks

| Need | Where | Anchor |
|---|---|---|
| Atomic JSON write | `internal/file_utils.py` | `safe_write_json` (fsync, then replace) |
| Cross-process lock | `internal/file_utils.py` | `file_lock` (raises `TimeoutError`) |
| Postmortem store | `internal/judges/postmortems.py` | `_load`, `record`, `_record_locked` |
| Portfolio store | `internal/judges/portfolios.py` | `_load` (read-only), `_load_checked` (writers) |
| Watchlist store | `internal/watchlist/store.py` | `_read_document` |
| Gainers alert state | `internal/message_intel/gainers_alert.py` | `_read_state`, `_write_state` |

Before you touch a loader, read `systems-invariants-guard`. It lists which
loaders currently lose data on a corrupt file.

## Council and scoring

| Need | Where | Anchor |
|---|---|---|
| Scorer identity (digest seed) | `internal/council/scorer_identity.py` | `_SCORER_SOURCE_FILES`, `current_scorer_digest` |
| Pick history | `internal/council/pick_history.py` | `_load` |
| Scenario memory | `internal/council/scenario_memory.py` | `_load` |
| Daily pick engine | `internal/council/daily_pick_engine.py` | `_load` |
| Learning: retry pending postmortems | `internal/learning/prediction_loop.py` | `retry_pending_postmortems` |

## Dev tools in this repo

| Tool | Purpose |
|---|---|
| `scripts/check_invariants.py` | Ratchet for the two data-loss shapes. `--check`, `--list`. |
| `scripts/check_commit_hygiene.py` | Staged diff check: runtime files, scorer seed, model names in messages. |
| `tests/test_check_invariants.py`, `tests/test_commit_hygiene.py` | Behavior tests for the two scripts. |

## Commands

```bash
source .venv/bin/activate
pytest                                   # contract test is the deploy gate
python scripts/check_invariants.py --check
python scripts/check_commit_hygiene.py   # staged index
```

Known pre-existing failures are listed in `AGENTS.md`. Do not assume the full
suite is green.
