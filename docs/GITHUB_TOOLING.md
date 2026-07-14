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
- No private keys in repo. Sent
ry/prometheus
 DSNs come from env only.
