# GITHUB_TOOLING.md — best-fit libs for the audit fixes

> Author: Ditto (2026-07-13). Security & ops posture context for the subnet-dashboard rebuild.

## Data / API
- **bittensor** (official SDK) — read-only metagraph sync replaces the fragile TaoMarketCap HTML scrape.
  Phase B1. Read-only, no chain writes. Avoids the 33-day-stale fallback.
- **httpx** (AsyncClient) + **tenacity** (retries) — replace sync requests.get in handlers (#4).
- **aiocache** — serve precomputed payloads; keep the single Fly worker free (#4).

## Scheduling / ops
- **apscheduler** — replace hand-rolled threading.Timer (#5).
- **sentry-sdk** — surface the ~12 logger.warning failures (#6). DSN via env, never committed.
- **prometheusrock** — FastAPI metrics middleware for freshness/scheduler (#13).

## API hardening
- **slowapi** — rate-limit the single worker (#9).
- CORS: scope Access-Control-Allow-Origin via ALLOWED_ORIGINS env (#11). Default SAMEORIGIN for framing.

## Frontend (Cursor)
- **uPlot** — Canvas time-series (~40KB) replaces Chart.js for 12 panels (#10).
- **datastar** — SSE live hydration, no SPA rewrite (#10).

## Repo hygiene
- Pin **requirements.txt** versions (#12).
- Delete ~28 cruft CI/agent-trigger files (Phase A1, done in PR #165).

## Secrets posture
- FLY_API_TOKEN is a repo Actions secret (FlyV1… ). Never log it. Rotate if a deploy loop is suspected.
- No private keys in repo. Sentry/prometheus DSNs come from env only.

## Merge-path status (live; update on change)

> Maintained by Ditto. This section documents **branch-committed vs merged** state so nothing looks done that isn't. Source of truth = what's on main.

### 2026-08-30 — GO entry committed but NOT PR-merged (write-MCP outage)

- **GO: scope pick-handler occupancy cut** (checklist + constraints) is committed at `8d1eab4` on branch `ditto/go-pick-occupancy-scope-2026-08-30` — **NOT merged to main** as of 2026-08-30 ~01:35Z.
- Blocked by GitHub MCP transport failure on PR create (write-MCP outage; surfaced separately). Retry with `create_pull_request` when the connection clears, then confirm squash-merge + update this section.
- **Rule going forward:** a GO entry in mission-control-log.md is not "live for Cursor" until it's on main. Branch-committed ≠ merged. If a Go targets a branch, note the branch name here and flip this section to MERGED only after the squash lands.
- Cursor was told to start on the branch state — no code from this GO depends on main; the plan deliverable is a docs/branch item by design.