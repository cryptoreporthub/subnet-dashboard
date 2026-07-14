# Cursor handoff — 2026-07-14 (Ditto → Cursor, full ownership)

> **STATUS (2026-07-14 evening):** EXTREME audit automated queue **COMPLETE** on `main` @ `7595d60`.
> **Nothing queued** from `automated-build-plan.md`. Ditto = **read-only monitor only** — do not assign B2/A2/Phase K as open work.

## For Ditto (read this first)

| Question | Answer |
|----------|--------|
| Is there more audit-queue work? | **No** — Phase A, B1–B6, C4–C6, C1–C3, G7, G12 all merged |
| Who implements new work? | **Cursor** via git (branch → PR → merge). Ditto does not write files |
| Is B2 / A2 / Phase K open? | **No** — B2 #179, A2 #172 + `smoke` on `main`, Phase K #107, J–O on `main` |
| What should Ditto do? | Monitor CI, Fly `/health`, `/api/data-freshness`. Report regressions only |

**Canonical status:** `cursor-agents-communication/board.md` (newer than this file's history section).

---

> Ditto stepped down from GitHub MCP `create_or_update_file` writes (read-replica sha race).
> **Cursor owns all implementation via real git** (branch → commit → push → PR → merge).

## Read order (boot)

1. **`cursor-agents-communication/board.md`** — live STATUS (authoritative)
2. **This file** — handoff context + guardrails
3. `cursor-agents-communication/automated-build-plan.md` — completed queue record
4. `docs/IMPLEMENTATION_PLAN.md` — checkbox status
5. `docs/EXTREME_AUDIT.md` — findings reference (FIX lines are historical; check board for done)
6. `.cursor/rules/ponytail.mdc`

## Merged on `main` (verified 2026-07-14)

| Track | Items | PRs |
|-------|-------|-----|
| **Phase A** | A1–A4, A2 smoke + branch protection | #167–#172, #170 |
| **Phase B** | B1–B6 (feed, async I/O, scheduler, metrics, APY, rate limit) | #174–#185 |
| **Hydration** | C4–C6 | #186–#189 |
| **Experience** | C1 uPlot, C2 SSE stream, C3 a11y | #190–#192 |
| **Cleanup** | G7 Rajdhani titles, G12 favicon/fonts | #195 |
| **Plan/docs** | automated-build-plan, board sync | #183, #193–#196 |

**A2 branch protection:** `smoke` required check verified on `main` (human-confirmed in GitHub Settings).

**B1 guardrails (do not regress):**
- `AUTO_SYNC` forced **off** under `GITHUB_ACTIONS`, `PYTEST_CURRENT_TEST`, `CI`
- Chain fetch hard timeout (`LIVE_SUBNETS_SYNC_TIMEOUT_SECONDS`, default 60)
- Uses existing `internal.chain_client` (not heavy bittensor SDK)

## GitHub MCP gotcha (why Ditto lost write access)

Ditto's `read_links` / `get_contents` hit **lagged read-replicas**; `create_or_update_file` validates against the **master** node → perpetual 409 stale-sha.

**Cursor rule:** never use GitHub Contents API for multi-file or large edits. Use **git only**.

## Optional housekeeping (not blocking)

- Close superseded open PRs: #165, #166, #184 (work already on `main` via #170 / board PRs)
- Cancel orphaned CI run [#29303004001](https://github.com/cryptoreporthub/subnet-dashboard/actions/runs/29303004001) if still running (human token)
- Radar chart still lazy-loads Chart.js (C1 migrated sparklines only; intentional deferral)

## Guardrails

- **Ponytail:** reuse helpers; smallest diff; one guard at shared function not per-caller
- **`main` protected** — PRs only; merge when CI green
- **Single foundation:** `server:app` only — no Flask/Gunicorn second entrypoint
- **Conflict surface:** `server.py` router includes + `tests/test_endpoint_contract.py`
- **Tests:** `pytest` + `tests/test_endpoint_contract.py` before merge

## Ditto role going forward

**Read-only monitor.** CI status, Fly `/health`, `/api/data-freshness` after deploy. **No GitHub file writes.** Do not re-open completed B2/A2/Phase K items from July 14 morning snapshots.
