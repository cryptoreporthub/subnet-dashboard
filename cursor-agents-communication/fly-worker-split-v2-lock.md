# Fly worker split v2 — LOCK

**Status:** PREP (env-gated, **off** in prod `fly.toml`)  
**Branch:** `cursor/phase-c-worker-split-v2-1d2f`  
**Canon:** `docs/fly-web-worker-split.md` § v2

## Scope

| Item | Detail |
|------|--------|
| C1 | `WORKER_SPLIT_V2=on` disables inline worker; `processes.worker` runs `fly_worker_entrypoint.sh` |
| C2 | Volume must attach to **worker** machine only (web read-only / degraded without volume) |
| C3 | `worker_mode: split_v2` in readiness when flag on |
| C4 | Rollback: `WORKER_SPLIT_V2=off`, scale `worker=0`, redeploy |

## Prod default

**v1 inline worker remains default.** Do not set `WORKER_SPLIT_V2=on` until human confirms volume attach on worker machine.

## Babysit

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh c
```
