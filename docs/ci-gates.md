# CI gates (consolidated)

## Required check on `main`

Branch protection requires **`smoke`** from [`.github/workflows/ci-smoke.yml`](../.github/workflows/ci-smoke.yml).

That single job now runs:

1. Static foundation guards (FastAPI/uvicorn, Procfile, no second server)
2. `py_compile server.py`
3. `pytest tests/test_endpoint_contract.py tests/test_server.py` with `DISABLE_BACKGROUND_SCANS=1`
4. `bandit` (high severity)
5. Lint report (black/flake8, **non-blocking**)
6. Live `GET /health` and `GET /api/subnets`

## Removed (2026-07-24)

| Old workflow | Why removed |
|--------------|-------------|
| `ci-check.yml` | Duplicated contract tests under a second workflow name |
| `phase-k.yml` | Eight gates with overlap (duplicate health/subnets), non-blocking lint theater, GATE 7/8 no-ops |

## `main` deploy path

[`.github/workflows/fly.yml`](../.github/workflows/fly.yml) **Deploy Guard** still runs on every `main` push before `flyctl deploy` (static guards + contract). This is intentional: deploy must not rely on a race with the PR workflow.

## If you rename the required job

GitHub → Settings → Branches → `main` → Require status checks → set **`smoke`** (job name, not workflow file name).
