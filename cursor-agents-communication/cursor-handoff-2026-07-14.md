# Cursor handoff — 2026-07-14 (Ditto → Cursor, full ownership)

> Ditto stepped down from GitHub MCP `create_or_update_file` writes (read-replica sha race).
> **Cursor owns all implementation via real git** (branch → commit → push → PR → merge).

## Read order (boot)

1. **This file** — `cursor-agents-communication/cursor-handoff-2026-07-14.md`
2. `cursor-agents-communication/board.md` — live status
3. `docs/EXTREME_AUDIT.md` — 16 findings
4. `docs/IMPLEMENTATION_PLAN.md` — Phase A/B/C sequencing
5. `docs/GITHUB_TOOLING.md` — lib posture
6. `docs/CURSOR_PROMPTS.md` — verbatim A3/A4 prompts (done)
7. `.cursor/rules/ponytail.mdc` — reuse existing code, minimal diff, no new deps unless forced

## Current state on `main` (verified merged)

| Phase | Item | PR | Notes |
|-------|------|-----|-------|
| A | Audit docs | #167 | EXTREME_AUDIT, IMPLEMENTATION_PLAN, GITHUB_TOOLING |
| A | CORS/XFO (#11) + cockpit isolation (#8) | #168 | `server.py`, `internal/cockpit/sections.py` |
| A | Cruft cleanup + CURSOR_PROMPTS | #170 | superseded Ditto #165/#166 |
| A | CI smoke gate (#2 partial) | #172 | uvicorn + real `curl --fail`; `timeout-minutes` added |
| B | Live on-chain feed (#1) | #174 | `internal/live_subnets.py`, `/api/data-freshness`; superseded Ditto #169 |

**B1 guardrails (do not regress):**
- `AUTO_SYNC` forced **off** under `GITHUB_ACTIONS`, `PYTEST_CURRENT_TEST`, `CI`
- Chain fetch hard timeout (`LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS`, default 60)
- Uses existing `internal.chain_client` (not heavy bittensor SDK) — Ponytail-correct

## GitHub MCP gotcha (why Ditto lost)

Ditto's `read_links` / `get_contents` hit **lagged read-replicas**; `create_or_update_file` validates against the **master** node → perpetual 409 stale-sha. Probe commit left `PLACEHOLDER` in history; markdown scraper junk corrupted `taomarketcap.py` / `health/routes.py`.

**Cursor rule:** never use GitHub Contents API for multi-file or large edits. Use **git only**.

## Manual steps (repo token cannot do these — human once)

### 1. Cancel orphaned hung CI run

- **Run:** [#29303004001](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/29303004001)
- **Branch:** `ditto/phase-b1-live-feed` (closed PR #169)
- **Why stuck:** old smoke workflow curled `/health` without starting uvicorn (pre-#172)
- **Action:** GitHub → Actions → open run → **Cancel workflow**
- Cloud agent token returns `403` on `gh run cancel` — only a human/admin token can kill it.

### 2. Branch protection — A2 remainder

Smoke body is fixed (#172). Optional hardening in **GitHub → Settings → Branches → `main` → Edit**:

- Add required status check: **`CI Smoke Test`** (job name `smoke`) — already required per GATE 8
- Optionally also require: **`ci-smoke-test`** from `ci-check.yml` if you want contract+server tests blocking merge

## Cursor queue (priority order)

| # | Phase | Task | Audit | Owner |
|---|-------|------|-------|-------|
| 1 | B1 UI | Freshness badge from `GET /api/data-freshness` | #1 | Cursor |
| 2 | B2 | `httpx` AsyncClient + `tenacity` + `aiocache` for handler I/O | #4 | Cursor |
| 3 | B3 | `apscheduler` + `sentry-sdk` | #5, #6 | Cursor |
| 4 | B4–B6 | prometheus, APY reconcile, slowapi | #13, #14, #9 | Cursor |
| 5 | C | uPlot, datastar SSE, CSS/a11y | #10, #15, #16 | Cursor (after B1 live on Fly) |

## Guardrails

- **Ponytail:** reuse helpers; smallest diff; one guard at shared function not per-caller
- **`main` protected** — PRs only; merge when CI green (user standing instruction: auto-merge)
- **Do not** reintroduce Flask/Gunicorn or second server entrypoint (`server:app` only)
- **Conflict surface:** `server.py` router includes + `tests/test_endpoint_contract.py`
- **Tests:** `pytest` + contract guard before merge; add routes to `CONTRACT` when porting

## Ditto role going forward

Read-only monitor only (CI status, Fly `/health`, `/api/data-freshness` after deploy). No GitHub file writes.
