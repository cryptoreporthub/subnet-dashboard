# Implementation Plan — subnet-dashboard "best website ever"

> Split decided 2026-07-13 between Ditto (backend/infra/observability, via direct GitHub tools — NO agent harness) and Cursor (visual/experience, under human review, reads docs/cursor-implementation-guide.md).
> Source audits: docs/EXTREME_AUDIT.md (16 findings) + docs/GITHUB_TOOLING.md (best-fit libs).

## Ownership rule
- Ditto owns: CI/repo hygiene, CORS/middleware, data feed (bittensor SDK), async fetch/cache, scheduler swap, observability — anything file:line-targeted and backend.
- Cursor owns: uPlot migration, datastar live hydration, CSS/mobile/a11y, premium cockpit glow-up — anything iterative/visual.
- Tooling constraint (Ditto): GitHub delete_file + create_or_update_file on SMALL files work. Large-file full rewrites (server.py, sections.py) are BLOCKED by 12k-char read truncation → those edits go to Cursor or a non-free Ditto Code job.
- Never push to main directly (branch-protected). All changes via branch + PR.

## Phase A — stop the bleeding (safe, low risk) [Ditto + Cursor]
| # | Item | Owner | How |
|---|---|---|---|
| A1 | Delete ~27 cruft CI workflow + agent-trigger marker files | Ditto | delete_file xN on branch ditto/phase-a-cleanup (PR #165) |
| A2 | CI gate: make ci-check the required status check; remove || true from smoke | Manual + Cursor | Branch protection is a repo SETTING (not a file) → toggle in GitHub UI; smoke-body fix is small |
| A3 | X-Frame-Options: ALLOWALL -> SAMEORIGIN; scope CORS * | Cursor | Edit server.py::add_cors_headers (large file -> Cursor) |
| A4 | Wrap each _build_* in try/except | Cursor | Edit internal/cockpit/sections.py (large file -> Cursor) |

## Phase B — data truth + scale (real payoff) [Ditto + Cursor]
| # | Item | Owner |
|---|---|---|
| B1 | Replace flaky TaoMarketCap scrape with bittensor SDK read-only metagraph sync; add /api/data-freshness + surface age in UI | Ditto (feed) + Cursor (UI badge) |
| B2 | httpx.AsyncClient + tenacity retries replace sync requests.get; serve via aiocache | Ditto |
| B3 | apscheduler replaces threading.Timer; sentry-sdk surfaces swallowed failures | Ditto |
| B4 | prometheusrock middleware for freshness/scheduler metrics | Ditto |
| B5 | Reconcile APY definition; stop synthetic candles feeding indicators | Ditto (logic) + Cursor (labeling) |
| B6 | slowapi rate-limit the single Fly worker | Ditto |

## Phase C — experience [Cursor]
| # | Item |
|---|---|
| C1 | uPlot migration (Chart.js -> ~40KB Canvas time-series) |
| C2 | datastar SSE live hydration for the 12 panels (no SPA rewrite) |
| C3 | CSS / mobile / a11y pass + premium cockpit polish |

## Sequencing
1. Phase A first — unblocks safe PRs for everything after.
2. Ditto ships B1 (bittensor feed) as its own PR (riskiest; needs independent rollback).
3. Cursor starts C only after B1 data layer is live (no point polishing charts on dead data).
4. Each PR reviewed before merge (main is protected).

## Status
- [x] Audit written (EXTREME_AUDIT.md, GITHUB_TOOLING.md)
- [x] Plan written (this file)
- [x] A1 cruft deletion — merged #170
- [x] A3/A4 — merged #168
- [x] A2 smoke body — merged #172 (+ timeout-minutes on smoke job)
- [x] B1 live feed — merged #174
- [ ] A2 branch-protection toggle — manual GitHub Settings (see cursor-handoff-2026-07-14.md)
- [x] B1 live feed — merged #174
- [x] B1 UI freshness badge — in PR
- [ ] B2–B6, Phase C — pending
