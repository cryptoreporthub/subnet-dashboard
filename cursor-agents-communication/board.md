# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-18T00:38:00Z  
**main:** `4ab6b2e` · **post-§34 + subnet-names plan complete**

## Active

**Phase A (prod stability — one machine)** — verify on live `/` after #333:
- `/health` < 2s · hydrate fills or fails visibly in ~30s · KPI not 0%
- See `docs/fly-web-worker-split.md` § Load-separation map

**Phase B (next slice)** — Fly **web + worker** split (#2): `docs/fly-web-worker-split.md`
- Same image, two processes; background jobs off the HTTP path
- Implementation: `internal/worker.py` + `RUN_MODE` + `fly.toml` `[processes]`

**Housekeeping / optional**
- **E1** test debt (`post-s28-backlog.md`) — broader pytest green
- **H1** custom domain — human DNS (`DEPLOY.md`)
- Prod human pass — §34 success metric on live `/`

## Done

- §34 front-door catch-up (#324/#325) — hydrate, evidence desk, whale/rug desk, Pro story
- Subnet names + on-chain investigation plan (#306, #325) — canonical names, investigate APIs, chat tools
- §27–§33 (#312–#323)
- §31 website opt · §32 trust product · §33 prod readiness

## Prod snapshot (verify_prod @ 2026-07-18)

- `ready: true` · graded **453** · feed **129** subnets (TMC) · resolver on
- HOLD daily pick (honest audit gate) · `live_subnets_cache_empty` known ops note
- Names: no `SNNone` in `/api/subnets` sample

## Skipped

- H1 custom domain (until human) · H2–H6 human infra · D1–D7 deferred
