# Fly worker split v2 — LOCK

**Status:** PREP DONE (#566) · **enablement in flight** (`cursor/phase-c-enable-v2-4988`)  
**Branch:** `cursor/phase-c-enable-v2-4988`  
**Canon:** `docs/fly-web-worker-split.md` § v2 · `fly.worker-v2.toml`

## Scope

| Item | Detail |
|------|--------|
| C1 | `WORKER_SPLIT_V2=on` disables inline worker; `processes.worker` runs `fly_worker_entrypoint.sh` |
| C2 | Volume attaches to **worker** only (`fly.worker-v2.toml` `[mounts]` processes) |
| C3 | `worker_mode: split_v2` in readiness when flag on |
| C4 | Rollback: `WORKER_SPLIT_V2=off`, scale `worker=0`, redeploy `fly.toml` |
| C5 | GHA/recover skip worker destroy when `WORKER_SPLIT_V2` secret set |

## Prod default

**v1 inline worker remains default** (`fly.toml`). Enable via human:

```bash
chmod +x scripts/fly_enable_worker_v2.sh
./scripts/fly_enable_worker_v2.sh
```

## Babysit

```bash
BASE=https://subnet-dashboard.fly.dev ./scripts/babysit_phase.sh c
```

Expect `worker_mode: split_v2` on web after enable; `worker_peer.alive` may be `null` on web (no shared volume).
