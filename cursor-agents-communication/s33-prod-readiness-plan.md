# §33 — Production readiness plan

**Status:** COMPLETE  
**Updated:** 2026-07-17  
**Baseline:** `main` @ `e25ed13` (post-§32)  
**PR:** #321 merged

## Goal

Production looked thin when Fly had an empty blockmachine cache or registry-only fallback — not because graded picks were zero. Fix **ops levers** (volume, scheduler, feed warmup, cred visibility), not UI.

## Shipped

| ID | What | Status |
|----|------|--------|
| S33-1 | `GET /api/ops/readiness` — learning, resolver, feed, TaoStats, daily pick, `issues[]`, `next_levers[]` | ✅ |
| S33-2 | `/api/data-freshness` — `effective_source`, `effective_total`, cache layer counts | ✅ |
| S33-3 | Boot subnet-feed warmup thread | ✅ |
| S33-4 | `SUBNETS_LOAD_TIMEOUT_SECONDS` (25) — registry fallback on slow feed | ✅ |
| S33-5 | `verify_prod.sh` — readiness + graded/feed asserts | ✅ |
| S33-6 | `DEPLOY.md` — "Production looks thin" troubleshooting | ✅ |

## Human-only (cannot automate)

| Item | Action |
|------|--------|
| TaoStats | `flyctl secrets set TAOSTATS_API_KEY=...` |
| Fly volume | Confirm `data_volume` → `/app/data` |
| Custom domain | H1 skipped |

## Verify post-deploy

```bash
./scripts/verify_prod.sh
curl -fsS https://subnet-dashboard.fly.dev/api/ops/readiness | python3 -m json.tool
```

## After §33

Board idle. HOLD daily pick below audit gate is **honest** — next product lever is signal quality / calibration, not more shell.
