# EXTREME_AUDIT.md — subnet-dashboard "best website ever" audit

> Author: Ditto (2026-07-13). 16 findings ranked by (risk × blast_radius). Grounded in inspection of
> server.py, internal/cockpit/sections.py, requirements.txt, .github/workflows/*.yml, templates/*.html,
> static/js/*.js, and the 12-panel cockpit data layer.

## Tier 1 — Systemic / data-truth (fix first)
**#1 Stale data (33d) — repo-embedded registry.json is the live source.**
- _build_index_context → _load_subnets_source → fetchers.taomarketcap.get_all_subnets() is a fragile
  HTML scrape that fails, so it falls back to config/registry.json (committed 2026-06-10). The 129
  subnets are therefore up to 33 days stale on the live site.
- FIX: replace the scrape with the official bittensor SDK (read-only metagraph sync) — Phase B1.

**#2 CI deploy-gate has no required status check.** ci-smoke runs but nothing blocks merge on failure;
ci-check is not registered as a required check. FIX: make ci-check required + remove || true (Phase A2, manual setting).

**#4 Blocking I/O inside request handlers.** /api/judges, /api/council, /api/subnets do sync requests.get
during request. On Fly single worker this serializes + causes the 422s we hit. FIX: httpx AsyncClient +
aiocache + tenacity (Phase B2).

**#5 Hand-rolled scheduler instead of apscheduler.**_background_refresh / threading.Timer drift. FIX: apscheduler (B3).

**#6 Swallowed failures (logger.warning).** ~12 warning sites never surface. FIX: sentry-sdk (B3).

**#7 Synthetic candles feed real indicators.** build_market_pulse uses generated series. FIX: gate on real data (B5).

## Tier 2 — Security / robustness
**#8 Cockpit panels are NOT isolated.** Each _build_* calls its submodule with no try/except. One failure →
/api/cockpit/sections 500s → ALL 12 panels blank ("warming up forever"). FIX: wrap each _build_* (Phase A4, Cursor).

**#9 No rate limiting.** Single Fly worker, no slowapi. FIX: slowapi (B6).

**#10 Client-side bloat.** Chart.js + 14 Jinja includes; no lazy hydrate. FIX: uPlot + datastar (Phase C).

**#11 CORS wildcard + invalid X-Frame-Options: ALLOWALL.** Clickjacking exposure; ALLOWALL is not a valid value.
FIX: SAMEORIGIN + scoped ALLOWED_ORIGINS (Phase A3, Cursor — Ditto cannot rewrite server.py via its file tools).

**#12 Unpinned requirements.txt.** No versions → non-reproducible deploys. FIX: pin (Ditto Code scope).

**#13 Missing Prometheus metrics.** No freshness/scheduler instrumentation. FIX: prometheusrock (B4).

## Tier 3 — Polish
**#14 APY double-counted** (TMC 7d×52 vs registry staking APY) — reconcile (B5).
**#15 Magenta stake badge** should be amber — CSS (G6 visual, Cursor).
**#16 Fabricated sparklines** — replace with real/empty (G8, Cursor).

> Ownership split: Ditto = backend/infra/observability (audit #1,#2,#4,#5,#6,#7,#12,#13 + B-feed).
> Cursor = visual/experience (#3 A2 smoke-body, #8 A4, #9-#11, #15,#16) under human review.
> Large-file rewrites (server.py, sections.py) are Cursor-owned because Ditto's GitHub file tools
> truncate reads at 12k chars and cannot safely rewrite them.
